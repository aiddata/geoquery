"""
Manage processing of user requests
Includes: updating status, handling errors, queue management and task submissions, doc/request building, emails, etc.)
"""

import json
import os
import shutil
import textwrap
import time
import zipfile
from collections import defaultdict
from datetime import datetime
from logging import getLogger
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

from datasets.models import Dataset, DatasetResource
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone
from features.models import FeatMap, Feature, FeatureCollection

from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from analytics.tasks.documentation import DocBuilder
from analytics.tasks.email import GeoEmail
from analytics.tasks.merge import merge_task_features, merge_task_results

logger = getLogger(__name__)

# How many times _build_output retries swapping its finished output into
# place. Each retry costs two renames, and only a concurrent build landing
# inside a sub-millisecond window forces one, so a small bound is plenty.
_OUTPUT_SWAP_ATTEMPTS = 3


class Command(BaseCommand):
    help = "Handles the generation of extract tasks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Whether to run the command without making any changes to the database (for testing)",
        )
        parser.add_argument(
            "--id",
            default=False,
            help="The ID of a specific request to process",
        )
        parser.add_argument(
            "--download-server",
            default=None,
            help="Base URL for file downloads (default: settings.DOWNLOAD_BASE_URL)",
        )
        parser.add_argument(
            "--frontend-base",
            default=None,
            help="Base URL for the frontend (default: settings.FRONTEND_BASE_URL)",
        )
        parser.add_argument(
            "--requests-dir",
            default=None,
            help="The directory containing results for the request (default: settings.REQUESTS_DIR)",
        )
        parser.add_argument(
            "--assets-dir",
            default=None,
            help="The directory containing assets for the request (default: settings.ASSETS_DIR)",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        _manage_user_requests(
            request_id=options["id"] or None,
            download_base=options["download_server"] or getattr(settings, "DOWNLOAD_BASE_URL", "").rstrip("/"),
            frontend_base=options["frontend_base"] or getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/"),
            requests_dir=options["requests_dir"] or str(settings.REQUESTS_DIR),
            assets_dir=options["assets_dir"] or str(settings.ASSETS_DIR),
            dry_run=options["dry_run"],
        )


def _manage_user_requests(
    request_id=None,
    download_base="",
    frontend_base="",
    requests_dir="/requests",
    assets_dir="../assets",
    dry_run=False,
):
    logger.info(
        "Starting User Request Management Script %s", time.strftime("%Y-%m-%d %H:%M:%S")
    )

    if request_id:
        logger.info("Processing request with id: %s", request_id)
    else:
        logger.info("Processing all requests in queue")

    request_objects = []

    if request_id:
        request = Request.objects.get(id=request_id)
        if not request:
            logger.error("Error finding request with id (%s)", request_id)
            return
        request_objects.append(request)
    else:
        request_objects += list(
            Request.objects.filter(status=-1).order_by("-priority", "submit_time")
        )
        request_objects += list(
            Request.objects.filter(status=0).order_by("-priority", "submit_time")
        )

    if not request_objects:
        logger.warning("Request queue is empty")
        return

    for request_obj in request_objects:
        request_id = str(request_obj.id)
        logger.info("Request (id: %s)\n%s", request_id, request_obj)

        completed_request_obj = None
        # The claim the error handler fences its status write on, or None when
        # this iteration never got one (dry_run, or a failure before the
        # claim). Reset every iteration and kept separate from `claim` below:
        # `claim` survives into the next iteration, so reusing it here would
        # let a *previous* request's claim_time fence this request's error
        # write and silently swallow it. The error handler must never raise
        # NameError either -- it runs while already handling a failure.
        error_claim = None
        # `claim` is deliberately left unbound here: it exists only on the
        # non-dry-run path, and the fences below read claim.claim_time. If a
        # future edit ever reaches them without a claim, NameError is the
        # right outcome -- a None claim_time would render as
        # "process_time IS NULL" and quietly match a never-claimed row.

        try:
            if not request_obj.data:
                _request_error(request_id, "Invalid request (missing items field)")
                continue
            if not request_obj.data["feature_ids"]:
                _request_error(request_id, "Invalid request (missing features)")
                continue
            if not request_obj.data["datasets"]:
                _request_error(
                    request_id, "Invalid request (missing dataset details)"
                )
                continue

            logger.info(
                "Features: %s (%s)",
                request_obj.data["selection_label"],
                request_obj.data["selection_label"],
            )

            # Phase 1 -- claim. dry_run takes no locks and writes no status;
            # it just reports on what it finds.
            if not dry_run:
                claim = _claim_request(request_id)
                if not claim.claimed:
                    logger.info(
                        "Request (id: %s) claimed by another sweep or no longer "
                        "queued -- skipping",
                        request_id,
                    )
                    continue
                error_claim = claim

                # Send the "received" acknowledgement as soon as the claim
                # commits, not at the end of the iteration: a crash mid-build
                # would otherwise lose it for good, because the reaper resets
                # the request to status=0 and the retry would see it as
                # already acknowledged. It is also the right semantics --
                # "we received your request" should arrive before a
                # multi-hour build, not after it. Gated on first_claim (see
                # _claim_request) so a re-claim never re-sends it.
                if claim.first_claim:
                    try:
                        _notify_user(
                            request_id, request_obj.contact, 0, download_base, frontend_base
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to send received notification for request (id: %s): %s",
                            request_id,
                            e,
                        )

            # Phase 2 -- the expensive part, deliberately outside any
            # transaction. _build_output writes files (CSV, HTML, JSON, PDF,
            # GeoPackage, zip); holding a requests row lock across that is
            # what let one slow request stack every other sweep behind it.
            missing_items, merge_map = _check_request_tasks(
                request_obj, dry_run=dry_run
            )

            if missing_items > 0:
                if not dry_run:
                    with transaction.atomic():
                        updated = Request.objects.filter(
                            id=request_id, status=2, process_time=claim.claim_time
                        ).update(status=0)
                    if not updated:
                        logger.warning(
                            "Lost claim on request (id: %s) before finalize "
                            "(reaped or taken over by another sweep) -- skipping",
                            request_id,
                        )
                        continue
                logger.warning(
                    f"Request not ready (id: {request_id}) - missing {missing_items} items"
                )
            else:
                updated_request_obj = Request.objects.get(id=request_id)
                _build_output(
                    updated_request_obj,
                    merge_map,
                    download_base,
                    requests_dir,
                    assets_dir,
                )
                # Phase 3 -- finalize. Both terminal writes are fenced on
                # still holding the claim (status=2 with our process_time):
                # the reaper can reset a long-running build's request to 0 and
                # let another sweep re-claim it, and _build_output opens by
                # rmtree-ing the request dir. Without the fence this sweep
                # would mark a request complete and email a download link
                # while another sweep is still writing that same zip.
                if not dry_run:
                    with transaction.atomic():
                        updated = Request.objects.filter(
                            id=request_id, status=2, process_time=claim.claim_time
                        ).update(status=1, complete_time=timezone.now())
                    if not updated:
                        logger.warning(
                            "Lost claim on request (id: %s) before finalize "
                            "(reaped or taken over by another sweep) -- not "
                            "sending completion email",
                            request_id,
                        )
                        continue
                    completed_request_obj = updated_request_obj
                logger.info("Request completed (id: %s)", request_id)

        except Exception as e:
            # include full traceback in the log for debugging purposes
            logger.exception(
                "Unhandled exception while processing request (id: %s): %s",
                request_id,
                e,
            )
            try:
                _request_error(
                    request_id, f"Unhandled exception: {e}", claim=error_claim
                )
            except Exception as err:
                logger.error(
                    "Failed to set error status for request (id: %s): %s",
                    request_id,
                    err,
                )
            logger.error("Skipping request (id: %s) due to error", request_id)
            continue

        # Send the completion notification after the transaction commits so a
        # notification failure cannot roll back committed request state or
        # mask a success.
        if completed_request_obj is not None and not dry_run:
            try:
                _notify_user(
                    request_id, completed_request_obj.contact, 1, download_base, frontend_base
                )
            except Exception as e:
                # Data is built but user was never notified — mark as error so it surfaces for manual intervention.
                logger.error(
                    "Failed to send completion notification for request (id: %s): %s",
                    request_id,
                    e,
                )
                try:
                    # Deliberately unfenced: this is only reachable once the
                    # finalize fence above passed, which means this sweep held
                    # the claim and just moved the row to status=1. Fencing on
                    # status=2 would match nothing and silently drop the error
                    # that makes an undelivered-but-built request visible.
                    _request_error(
                        request_id,
                        f"Completion notification failed (data is ready): {e}",
                    )
                except Exception as err:
                    logger.error(
                        "Failed to set error status for request (id: %s): %s",
                        request_id,
                        err,
                    )

    logger.info(
        "Finished User Request Management Script %s", time.strftime("%Y-%m-%d %H:%M:%S")
    )


def _request_error(request_id, message, claim=None):
    """Mark a request failed.

    With a claim, the write is fenced on still owning it, exactly like the
    terminal writes in _manage_user_requests. Once the reaper can reset a
    running build, a sweep that lost its claim and then hits any exception
    would otherwise clobber the new owner's in-progress status=2 -- or a
    status=1 the winner already completed and emailed a download link for.

    Without a claim (the validation failures, which happen before any claim
    exists) the write is unconditional, as it has always been.
    """
    logger.error("Error with request (id: %s): %s", request_id, message)

    if claim is None:
        Request.objects.filter(id=request_id).update(status=-2)
        return

    updated = Request.objects.filter(
        id=request_id, status=2, process_time=claim.claim_time
    ).update(status=-2)
    if not updated:
        logger.warning(
            "Lost claim on request (id: %s) (reaped or taken over by another "
            "sweep) -- not marking it failed; the current owner's status "
            "stands",
            request_id,
        )


def _notify_user(request_id, mail_to, status, download_base, frontend_base):
    """Send email that request was received (status=0) or completed (status=1)."""
    if status not in [0, 1]:
        raise ValueError(
            f"Invalid status for _notify_user: {status}. Status must be 0 or 1."
        )

    status_text = "Received" if status == 0 else "Completed"
    mail_subject = f"AidData GeoQuery- Request {request_id[:7]}.. {status_text}"

    received_message = textwrap.dedent(f"""
        Thanks for using GeoQuery. This is an automated email to let you
        know that we received your request and will process your data as
        soon as we can. We will send another email when your data is ready.

        You can view the status of this data request here:
        \t{frontend_base}/requests/{request_id}

        You can also keep track of all of the data requests you've
        submitted with this email address here:
        \t{frontend_base}/requests

        Thank you,
        \tAidData's GeoQuery Team
    """)

    completed_message = textwrap.dedent(f"""
        Thanks again for using GeoQuery. This is another automated email to let you know that
        your data is ready.

        You can review your request, and download the results and documentation here:
        \t{frontend_base}/requests/{request_id}

        Or download the results directly (this link will always be available):
        \t{download_base}/requests/{request_id}/{request_id}.zip

        You can also view all your current and previous requests using:
        \t{frontend_base}/requests

        Also, one quick reminder about citations. Don't forget to cite both AidData's GeoQuery
        tool as well as each dataset you selected within GeoQuery. All citations can be found
        in the Documentation PDF at the link above. Here's the correct citation for GeoQuery:

            Goodman, S., BenYishay, A., Lv, Z., & Runfola, D. (2019).
            GeoQuery: Integrating HPC systems and public web-based
            geospatial data tools. Computers & Geosciences, 122, 103-112.

        Thank you in advance for citing us when you publish your research.
        This helps us to demonstrate how GeoQuery is making a difference
        as a freely available public good.

        Thank you,
        \tAidData's GeoQuery Team
    """)

    mail_message = received_message if status == 0 else completed_message

    mail_status = GeoEmail().send_email(mail_to, mail_subject, mail_message)
    if not mail_status[0]:
        raise Exception(f"Email send failed: {mail_status[1]}: {mail_status[2]}")


class RequestClaim(NamedTuple):
    """The outcome of one attempt to claim a request for processing."""

    claimed: bool
    original_status: int | None = None
    claim_time: datetime | None = None
    first_claim: bool = False


def _claim_request(request_id):
    """Claim a request for processing, in its own short committed transaction.

    Returns a :class:`RequestClaim`. ``RequestClaim(False)`` means the claim
    failed -- because another sweep already holds the row, or because the
    request's status moved out of -1/0 between selection and now.

    ``claim_time`` is the process_time written here, and doubles as a claim
    fence: the terminal status writes filter on it, so a sweep whose claim was
    taken over mid-build (the reaper resets a stale status=2 to 0, and another
    sweep re-claims) cannot finalize a request it no longer owns.

    ``first_claim`` reports whether prepare_time was NULL before this claim,
    i.e. whether the user has ever been sent the "we received your request"
    acknowledgement. It gates that email. Status is the wrong gate: the
    separate reset_errored_requests command blanket-resets status -2 -> -1
    with raw SQL and never touches prepare_time, so gating on status would
    re-send the acknowledgement once per error/reset cycle, unbounded.

    NOTE: this atomic() must be the outermost transaction for the claim to
    commit. If a future caller ever wraps _manage_user_requests in its own
    transaction.atomic(), this degrades silently to a savepoint -- the claim
    never commits, the row lock is held across the whole build, and the
    original pileup bug returns with nothing to signal it.

    status=2 has always meant "a sweep is working on this" -- the selection
    query in _manage_user_requests deliberately matches only -1 and 0. It
    could never actually work, because it used to be written inside the same
    transaction that did all the work, so it stayed invisible to every other
    sweep until that work was already finished. Committing it here is what
    makes the claim real.

    skip_locked=True is what removes the pileup: a request another sweep is
    mid-claim on is skipped outright rather than queued behind its row lock.
    The status re-check inside the lock matters because request_objects is
    built as a list up front, so a row's status can change between selection
    and this call.
    """
    with transaction.atomic():
        row = (
            Request.objects.select_for_update(skip_locked=True)
            .filter(id=request_id, status__in=(-1, 0))
            .values("id", "status", "prepare_time")
            .first()
        )
        if row is None:
            return RequestClaim(False)

        original_status = row["status"]
        # prepare_time marks first acknowledgement, so it is written once and
        # never overwritten on a later re-claim (reaped, or error-and-reset).
        first_claim = row["prepare_time"] is None
        claim_time = timezone.now()
        updates = {"status": 2, "process_time": claim_time}
        if first_claim:
            updates["prepare_time"] = claim_time
        Request.objects.filter(id=request_id).update(**updates)
        return RequestClaim(True, original_status, claim_time, first_claim)


def _check_request_tasks(request, dry_run=False):
    """Check entire request for completion.

    Returns count of tasks still pending and a {task_id: dataset_id} map of
    completed extract tasks.

    Every extract_tasks query here is grouped by dataset_id first. The table
    is LIST partitioned on dataset_id with PRIMARY KEY (dataset_id, id), so
    id is the *second* PK column: a filter on id alone can't seek the PK
    index at all and degrades to scanning every partition. At request scale
    (tens of thousands of task ids) that took hours and held this request's
    row lock the whole time, stacking up every subsequent sweep pass behind
    it -- confirmed in production via pg_stat_activity. RequestMap already
    carries dataset_id per row, so the grouping is free.
    """
    logger.info("Checking status of processing tasks (dry_run=%s)...", dry_run)

    task_rows = list(
        RequestMap.objects.filter(request=request.id).values_list(
            "task_id", "dataset_id"
        )
    )
    total = len(task_rows)

    tasks_by_dataset = defaultdict(list)
    for task_id, dataset_id in task_rows:
        tasks_by_dataset[dataset_id].append(task_id)

    existing_ids = set()
    completed_task_map = {}
    for dataset_id, ds_task_ids in tasks_by_dataset.items():
        existing_ids.update(
            ExtractTask.objects.filter(
                dataset_id=dataset_id, id__in=ds_task_ids
            ).values_list("id", flat=True)
        )
        completed_task_map.update(
            {
                task_id: dataset_id
                for task_id in ExtractTask.objects.filter(
                    dataset_id=dataset_id, id__in=ds_task_ids, status=1
                ).values_list("id", flat=True)
            }
        )

        # Bump priority on pending tasks so workers pick them up before
        # background tasks
        if not dry_run:
            ExtractTask.objects.filter(
                dataset_id=dataset_id, id__in=ds_task_ids, priority=0
            ).exclude(status=1).update(priority=1)

    missing_ids = {task_id for task_id, _ in task_rows} - existing_ids
    if missing_ids:
        logger.error(
            "%d extract task(s) not found for request %s: %s",
            len(missing_ids), request.id, missing_ids,
        )

    pending_task_count = total - len(completed_task_map)
    logger.info("Processing tasks pending: %d/%d", pending_task_count, total)

    return pending_task_count, completed_task_map


def _build_output(request, task_map, download_server, requests_dir, assets_dir):
    """Merge extracts, generate documentation, build zip."""
    requests_dir = Path(requests_dir)
    assets_dir = Path(assets_dir)

    request_id = str(request.id)
    request_dir = requests_dir / request_id

    # Build into a unique directory and only swap it into place at the very
    # end. Two sweeps can be inside _build_output for the same request at once
    # (a reaper resets a claim while the original build is still running), and
    # the old rmtree-then-write-in-place approach let one build delete or
    # interleave with the other's files -- producing a zip that is a mix of
    # both builds, which the download email then advertises as finished
    # output.
    #
    # The build directory has to be a *sibling* of request_dir so the final
    # swap is a same-filesystem rename: os.replace raises OSError across
    # devices, and tempfile.mkdtemp() may well land on a different one.
    build_dir = requests_dir / f".{request_id}.building.{uuid4().hex}"
    build_dir.mkdir(parents=True, exist_ok=True)

    # make_zipfile writes to base_name + ".zip"; with the build directory as
    # base_name that is a uniquely-named sibling, so concurrent builds do not
    # fight over one intermediate zip path either. The archive's internal
    # paths depend only on base_dir, so they are unchanged.
    build_zip = Path(str(build_dir) + ".zip")

    try:
        request_csv = build_dir / f"{request_id}_results.csv"
        request_documentation = build_dir / f"{request_id}_documentation.html"
        request_json = build_dir / "request_details.json"

        merge_status, merge_df = merge_task_results(task_map)
        if merge_status != "Success":
            raise Exception(
                f"No extracts merged for request {request_id}. Merge status: {merge_status}"
            )
        logger.info("Merge completed for request %s", request_id)
        merge_df.to_csv(request_csv, index=False)

        doc = DocBuilder(request, request_documentation, download_server)
        bd_status = doc.build_doc()
        if bd_status != "Success":
            raise Exception(
                f"Error building documentation for request {request_id}. Status: {bd_status}"
            )
        logger.info("Documentation generated for request %s", request_id)

        with open(request_json, "w") as rdoc_file:
            json.dump(
                {k: v for k, v in request.__dict__.items() if not k.startswith("_")},
                rdoc_file,
                indent=4,
                default=str,
            )

        pdf_src = assets_dir / "other/GeoQuery_Goodman2019.pdf"
        pdf_dst = build_dir / "GeoQuery_Goodman2019.pdf"
        shutil.copyfile(pdf_src, pdf_dst)

        features_status, features_gdf = merge_task_features(task_map)
        if features_status == "Success":
            features_gdf.to_file(build_dir / "request_features.gpkg", driver="GPKG")
        elif features_status == "Empty":
            logger.info("No features to merge for request %s", request_id)
        else:
            raise Exception(
                f"Error merging features for request {request_id}. Status: {features_status}"
            )

        make_zipfile(build_dir, build_dir)
        # The zip's *name* comes from base_name, which is now the temp
        # directory, so name the destination explicitly -- the download URL
        # points at <request_id>/<request_id>.zip.
        shutil.move(str(build_zip), str(build_dir / f"{request_id}.zip"))
        os.remove(pdf_dst)

        os.chmod(build_dir, 0o775)
        for ro, di, fi in os.walk(build_dir):
            for d in di:
                os.chmod(os.path.join(ro, d), 0o775)
            for f in fi:
                os.chmod(os.path.join(ro, f), 0o664)

        # os.replace onto a *non-empty* directory raises ENOTEMPTY, so the old
        # output is moved aside atomically rather than deleted in place.
        # Deleting it first leaves a gap in which a concurrent build can land
        # its own result at request_dir, and our replace would then raise --
        # which the caller turns into _request_error's unfenced
        # update(status=-2) for a request whose output is in fact complete.
        # Moving aside and retrying makes a losing swap a no-op instead: the
        # last successful replace wins, each build's output is whole, and both
        # builds return normally.
        #
        # The remaining window is between the move-aside and the replace,
        # where nothing exists at request_dir -- sub-millisecond, down from
        # the minutes the whole build used to take. Closing it entirely would
        # mean making request_dir a symlink and flipping it, which is not
        # worth the complexity here.
        displaced = []
        try:
            for attempt in range(_OUTPUT_SWAP_ATTEMPTS):
                aside = requests_dir / f".{request_id}.replaced.{uuid4().hex}"
                try:
                    os.replace(request_dir, aside)
                except FileNotFoundError:
                    # Nothing to displace, or a concurrent build moved the old
                    # output aside itself and has not landed its own yet.
                    pass
                else:
                    displaced.append(aside)

                try:
                    os.replace(build_dir, request_dir)
                except OSError:
                    # A concurrent build repopulated request_dir in the gap
                    # above. Its output is as valid as ours, so displace it
                    # and try again rather than failing the request.
                    if attempt == _OUTPUT_SWAP_ATTEMPTS - 1:
                        raise
                    continue
                break
        finally:
            for aside in displaced:
                shutil.rmtree(aside, ignore_errors=True)
    except Exception:
        shutil.rmtree(build_dir, ignore_errors=True)
        build_zip.unlink(missing_ok=True)
        raise


def make_zipfile(base_name, base_dir):
    """Create a zip file from all the files under 'base_dir'.

    The output zip file will be named 'base_name' + ".zip".

    *** Modified from shutil.make_archive
    """
    zip_filename = Path(str(base_name) + ".zip")
    archive_dir = zip_filename.parent
    archive_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        zip_filename, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as zf:
        length = len(str(base_dir))
        for dirpath, dirnames, filenames in os.walk(base_dir):
            folder = dirpath[length:]
            for name in filenames:
                actual_path = os.path.normpath(os.path.join(dirpath, name))
                zip_path = os.path.normpath(os.path.join(folder, name))
                if os.path.isfile(actual_path):
                    zf.write(actual_path, zip_path)
    return zip_filename
