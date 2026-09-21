import os
import re
import time
from datetime import timedelta
from collections import defaultdict
from logging import getLogger
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from analytics.models import Request

# _build_output creates both orphan classes this command collects, and its
# removal helper already handles the "not actually a directory" cases that a
# plain rmtree silently ignores. Reusing it keeps the two sides of the same
# swap in agreement rather than re-deriving the rules here.
from analytics.management.commands.manage_user_requests import _remove_output_path

logger = getLogger(__name__)

# Orphans _build_output's swap can leave behind, both named after the request
# whose output they belong to:
#
#   .<request_id>.building.<uuid4 hex>[.zip]   a half-written build
#   .<request_id>.replaced.<uuid4 hex>         output displaced by a new build
#
# The 32-hex token is what makes this safe to match on: nothing else in the
# requests directory is named that way, so an operator's stray file cannot be
# mistaken for an orphan.
_ORPHAN_RE = re.compile(
    r"^\.(?P<request_id>.+)\.(?P<kind>building|replaced)\.[0-9a-f]{32}(?:\.zip)?$"
)


class Command(BaseCommand):
    help = (
        "Reset requests stranded in claimed state (status=2) by a crashed "
        "sweep back to processing (status=0) so they are retried, and collect "
        "the output directories that crashed sweep left behind."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Print what would be reset or collected without making changes.",
        )
        parser.add_argument(
            "--minutes",
            type=int,
            default=30,
            help=(
                "Number of minutes after which a claimed request is considered "
                "stale and reset for retry"
            ),
        )
        parser.add_argument(
            "--requests-dir",
            default=None,
            help=(
                "Directory holding request output. Defaults to settings.REQUESTS_DIR. "
                "Abandoned build directories under it are collected too."
            ),
        )

    def handle(self, *args, **options):
        minutes = options["minutes"]
        dry_run = options["dry_run"]
        requests_dir = options["requests_dir"] or str(settings.REQUESTS_DIR)

        result = _reset_stale_requests(minutes, dry_run=dry_run)
        unmaterialized = _redispatch_unmaterialized_requests(minutes, dry_run=dry_run)
        orphans = _clean_orphan_output_dirs(requests_dir, minutes, dry_run=dry_run)

        if dry_run:
            self.stdout.write(
                f"Would reset {result['count']} stale claimed requests, "
                f"re-dispatch {unmaterialized['count']} unmaterialized requests, "
                f"remove {orphans['removed']} abandoned output paths and restore "
                f"{orphans['restored']} displaced outputs (--dry-run)."
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Reset {result['reset']} stale claimed requests to processing, "
                    f"re-dispatched {unmaterialized['redispatched']} unmaterialized "
                    f"requests, removed {orphans['removed']} abandoned output paths "
                    f"and restored {orphans['restored']} displaced outputs."
                )
            )


def _reset_stale_requests(minutes: int, dry_run: bool = False) -> dict:
    """Return requests stranded at status=2 to status=0.

    status=2 means a sweep claimed the request and is working on it. Since
    that claim is now committed (so other sweeps skip the request rather
    than queueing on its row lock), a sweep that dies mid-build leaves the
    request claimed forever -- and the sweep's selection query only matches
    -1/0, so nothing would ever pick it up again.

    Reset to 0 rather than -1 deliberately: -1 would make the retry treat it
    as newly queued and re-send the "request received" notification.
    Retrying is safe because _build_output builds into a fresh unique
    directory and only swaps it into place at the end, so a crashed attempt's
    partial output is never what a retry merges into or what a user
    downloads.

    The NULL check is not defensive padding: ``process_time IS NULL`` is
    possible on rows that reached status=2 by some path other than
    _claim_request (a manual UPDATE, or a legacy row), and
    ``NULL < NOW() - INTERVAL ...`` evaluates to NULL rather than true, so a
    bare comparison would strand exactly the rows this reaper exists to
    rescue.

    Returns ``{"count": matched, "reset": changed}`` on both paths -- under
    dry_run nothing is changed, so ``reset`` is 0. Both keys are always
    present so a caller never has to know which path ran.

    Same job, same shape as free_stale_processing_tasks does for ExtractTask
    rows stuck at status=2.
    """
    # psycopg2 substitutes %s inside the quoted interval literal (verified:
    # mogrify renders INTERVAL '30 minutes'), which is how
    # free_stale_processing_tasks has always expressed this. minutes is
    # coerced to int so the literal can never be anything but a number.
    minutes = int(minutes)
    predicate = """
        status = 2
        AND (
            process_time IS NULL
            OR process_time < NOW() - INTERVAL '%s minutes'
        )
    """

    with connection.cursor() as cursor:
        if dry_run:
            cursor.execute(f"SELECT COUNT(*) FROM requests WHERE {predicate}", [minutes])
            return {"count": cursor.fetchone()[0], "reset": 0}

        cursor.execute(f"UPDATE requests SET status = 0 WHERE {predicate}", [minutes])
        reset = cursor.rowcount or 0

    logger.info("Reset %d stale claimed requests to processing", reset)
    return {"count": reset, "reset": reset}



def _redispatch_unmaterialized_requests(minutes: int, dry_run: bool = False) -> dict:
    """Re-dispatch materialization for requests stranded at status=4.

    status=4 means "submitted, materialization pending". It is set by
    create_request, and materialize_request_tasks is what moves it on --
    dispatched by the on_request_submitted post_save signal.

    That task already turns its *own* failures into status=-2, so a request
    only sits at 4 when it never ran at all: the signal never fired (a bulk
    UPDATE does not fire post_save), or the message was lost -- a broker
    outage, a worker killed before executing, or the 0.43.1 incident, where
    the task lived in a module analytics/tasks/__init__.py never imported so
    every worker dropped it with a KeyError and *every* submitted request
    stranded at 4.

    Nothing else looks at status=4: the completion sweep's selection query
    matches only -1 and 0. So those requests were stranded permanently and
    silently -- 4 is a normal transient state, and -2 is the only status
    monitoring reads as an error. Observed in production, where one request
    sat at 4 for four days and completed in 5 seconds once nudged.

    Re-dispatching rather than erroring is deliberate: the work is almost
    always still valid, and materialize_request is idempotent by design --
    it deletes any RequestMap rows already attached before recreating them,
    specifically so re-triggering a stuck request cannot duplicate them. If
    the retry genuinely cannot resolve, materialize_request_tasks records
    status=-2 itself, which *is* visible.

    Age is measured from submit_time. Materialization normally finishes in
    seconds, so the threshold only needs to clear a slow-but-live run rather
    than distinguish anything subtle.
    """
    from analytics.tasks.requests import materialize_request_tasks

    minutes = int(minutes)
    stuck = list(
        Request.objects.filter(
            status=4, submit_time__lt=timezone.now() - timedelta(minutes=minutes)
        ).values_list("id", flat=True)
    )

    if dry_run:
        if stuck:
            logger.warning(
                "Would re-dispatch materialization for %d stranded request(s)",
                len(stuck),
            )
        return {"count": len(stuck), "redispatched": 0, "failed": 0}

    redispatched = 0
    failed = 0
    for request_id in stuck:
        try:
            materialize_request_tasks.delay(str(request_id))
        except Exception as exc:
            # An unreachable broker must not stop us trying the rest; the
            # next pass retries whatever failed. Status is deliberately left
            # at 4 so it stays a candidate.
            logger.error(
                "Could not re-dispatch materialization for request %s: %s",
                request_id,
                exc,
            )
            failed += 1
            continue
        logger.warning(
            "Re-dispatched materialization for stranded request %s", request_id
        )
        redispatched += 1

    if stuck:
        logger.info(
            "Re-dispatched %d stranded request(s), %d failed", redispatched, failed
        )
    return {"count": len(stuck), "redispatched": redispatched, "failed": failed}


def _clean_orphan_output_dirs(requests_dir, minutes: int, dry_run: bool = False) -> dict:
    """Collect the output paths a hard-killed sweep left in requests_dir.

    _build_output removes its own build directory when a build *raises*, but
    a SIGKILL or an OOM kill gives it no chance to, so two kinds of orphan
    accumulate -- and they need opposite treatment:

    ``.<request_id>.building.<hex>`` (and its intermediate ``.zip``) is a
    half-written build. Nothing ever reads it and nothing else collects it,
    so it is always disposable.

    ``.<request_id>.replaced.<hex>`` is output moved aside by a swap that was
    about to land a new build. If the kill landed in the window between that
    move-aside and the os.replace, request_dir is *absent* and this aside is
    the only surviving copy of a completed request's output. That request is
    at status=1, so the sweep never re-selects it and nothing else rebuilds
    it -- the emailed "this link will always be available" download would
    404 forever. So it is restored when request_dir is missing and removed
    only when something valid already occupies request_dir.

    This is why the two prefixes must never be collected by one glob over
    ``.<request_id>.*`` that deletes: that glob destroys exactly the copy
    this function exists to rescue.

    Liveness is decided by the *database*, not the filesystem. Any request
    still at status=2 may have a sweep inside _build_output right now, so its
    orphans are left alone entirely. That check composes with the reset above,
    which runs first: a genuinely dead sweep's request has already been moved
    off status=2 by the time we get here, so its leftovers are collectible in
    the same pass, while a live build -- which keeps its claim fresh via
    _ClaimHeartbeat -- stays protected for as long as it runs.

    Filesystem age is a coarse backstop, deliberately NOT the liveness
    signal, because no timestamp is a sound one here. A directory's mtime
    only moves when an entry is created or removed in it, so a build sitting
    in a long merge -- or writing its zip, which lands as a *sibling* -- has
    a frozen mtime and looks abandoned. os.replace does not touch mtime at
    all, so a ".replaced." aside inherits the mtime of the output it
    displaced and can be months old the instant it is created. ctime is no
    better: it moves on any metadata change, so it makes everything look
    fresh forever. Hence the claim check above.
    """
    requests_dir = Path(requests_dir)
    removed = 0
    restored = 0

    if not requests_dir.is_dir():
        logger.warning("Requests directory %s does not exist; nothing to collect", requests_dir)
        return {"removed": removed, "restored": restored}

    cutoff = time.time() - int(minutes) * 60
    building = []
    replaced = defaultdict(list)

    # Requests a sweep may be building right now. Str-keyed because that is
    # what the directory names carry.
    live_request_ids = {
        str(request_id)
        for request_id in Request.objects.filter(status=2).values_list(
            "id", flat=True
        )
    }

    for entry in requests_dir.iterdir():
        match = _ORPHAN_RE.match(entry.name)
        if match is None:
            continue
        if match["request_id"] in live_request_ids:
            # A sweep still holds this request's claim, so this path may be
            # the build it is writing into, or output it is mid-swap on.
            continue
        try:
            # lstat, not stat: a symlink orphan is judged on itself, and a
            # dangling one must not raise here.
            stat = entry.lstat()
        except OSError as exc:
            logger.warning("Could not stat %s: %s", entry, exc)
            continue
        if stat.st_mtime > cutoff:
            # A coarse backstop only -- see the docstring. Liveness is the
            # status=2 check above, not this.
            continue
        if match["kind"] == "building":
            building.append(entry)
        else:
            replaced[match["request_id"]].append((stat, entry))

    for entry in building:
        logger.info("Removing abandoned build path %s", entry)
        if not dry_run:
            _remove_output_path(entry)
        removed += 1

    for request_id, entries in replaced.items():
        request_dir = requests_dir / request_id

        # exists() follows symlinks, matching _restore_displaced_output: a
        # *dangling* symlink at request_dir means there is nothing to
        # download there, so it must not count as output already in place.
        if request_dir.exists():
            for _, entry in entries:
                logger.info(
                    "Removing displaced output %s -- %s is occupied", entry, request_dir
                )
                if not dry_run:
                    _remove_output_path(entry)
                removed += 1
            continue

        # Newest first. mtime is the threshold this function already uses;
        # ctime breaks ties because a rename bumps it, so it tracks the order
        # the asides were displaced in when their contents share an mtime.
        entries.sort(key=lambda pair: (pair[0].st_mtime, pair[0].st_ctime, pair[1].name))
        newest = next(
            (
                entry
                for _, entry in reversed(entries)
                if entry.is_dir() and not entry.is_symlink()
            ),
            None,
        )
        if newest is None:
            # Nothing here is an output tree. Removing it anyway is not this
            # reaper's call -- it did not create it and cannot tell what it is.
            logger.warning(
                "No restorable output among the displaced copies for request %s; "
                "leaving %d path(s) in place",
                request_id,
                len(entries),
            )
            continue

        logger.warning(
            "Request %s has no output directory; restoring displaced copy %s",
            request_id,
            newest,
        )
        if not dry_run:
            try:
                os.replace(newest, request_dir)
            except OSError as exc:
                # Keep every copy rather than risk deleting the only one.
                logger.error(
                    "Could not restore displaced output %s to %s -- leaving it "
                    "in place for recovery: %s",
                    newest,
                    request_dir,
                    exc,
                )
                continue
        restored += 1

        # Whatever is left is superseded by the copy just restored.
        for _, entry in entries:
            if entry == newest:
                continue
            if not dry_run:
                _remove_output_path(entry)
            removed += 1

    logger.info(
        "Orphan output cleanup: removed %d path(s), restored %d displaced output(s)",
        removed,
        restored,
    )
    return {"removed": removed, "restored": restored}
