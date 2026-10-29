"""Import completed requests from the previous version of GeoQuery.

Reads the Parquet produced by ``request_migration/requests_to_parquet.py``
(itself a conversion of ``mongoexport --db=asdf --collection=det --jsonArray``)
and upserts them into ``analytics.LegacyRequest``.

The old system is still accepting submissions, so this is expected to run
twice: once now against a fixed ``--submitted-before`` date, and again when
that system is retired. Upserting on the preserved Mongo ObjectId makes the
second run safe -- it adds what is new and leaves everything else as it was.

Only completed requests are imported. Records missing a contact address, a
boundary, or any dataset are skipped and counted: they cannot be rendered
usefully, and the old system's own data has at least one of each.
"""

from collections import Counter
from datetime import datetime, timezone as dt_timezone

import pyarrow.parquet as pq
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.functions import Lower
from django.utils.dateparse import parse_date

from analytics.models import LegacyRequest

# Columns the command reads. Named explicitly so the Parquet can grow new
# ones without this command loading them.
COLUMNS = [
    "request_id",
    "email",
    "custom_name",
    "status",
    "stage",
    "boundary",
    "release_data",
    "raster_data",
]

COMPLETED = 1

# Fields written on conflict. `id` is the conflict target, so it is not
# listed. `imported_at` IS listed: with update_conflicts, Django writes only
# the fields named here, so leaving it out would keep the original timestamp
# and the column would mean "first imported" rather than "last run that
# touched this row", which is what the model documents.
UPDATE_FIELDS = [
    "contact",
    "custom_name",
    "submit_time",
    "complete_time",
    "boundary_title",
    "boundary_name",
    "boundary_group",
    "dataset_titles",
    "dataset_count",
    "data",
    "imported_at",
]

MAX_LENGTHS = {
    "contact": 100,
    "custom_name": 100,
    "boundary_title": 100,
    "boundary_name": 64,
    "boundary_group": 32,
}


def _plain(obj):
    """Make pyarrow output JSON-serializable.

    A Parquet map arrives from ``to_pylist`` as a list of (key, value) pairs;
    it round-trips far more usefully as an object.
    """
    if isinstance(obj, (list, tuple)):
        items = list(obj)
        if items and all(
            isinstance(i, tuple) and len(i) == 2 and isinstance(i[0], str)
            for i in items
        ):
            return {k: _plain(v) for k, v in items}
        return [_plain(i) for i in items]
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    return obj


def _stage_times(stage):
    """``(submit_time, complete_time)`` as aware datetimes, or ``(None, None)``.

    Only these two stages are read. ``prepared`` and ``processed`` are
    deliberately ignored: in 9,716 of the exported completed rows they precede
    ``submitted``.
    """
    times = {s["name"]: s["time"] for s in stage or [] if s and s.get("name")}
    submitted, completed = times.get("submitted"), times.get("completed")
    if submitted is None or completed is None:
        return None, None
    return (
        datetime.fromtimestamp(submitted, tz=dt_timezone.utc),
        datetime.fromtimestamp(completed, tz=dt_timezone.utc),
    )


class Command(BaseCommand):
    help = (
        "Import completed requests from the previous version of GeoQuery out of "
        "a Parquet export. Upserts on the Mongo ObjectId, so it is safe to "
        "re-run; expected to run once now and again at cutover."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--parquet",
            required=True,
            help="Path to the Parquet file from requests_to_parquet.py.",
        )
        parser.add_argument(
            "--submitted-before",
            required=True,
            help=(
                "Import only requests submitted strictly before this ISO date "
                "(YYYY-MM-DD). Required so that no run depends on when it ran."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be imported without writing.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Rows per upsert batch (default 2000).",
        )

    def handle(self, *args, **options):
        cutoff_date = parse_date(options["submitted_before"])
        if cutoff_date is None:
            raise CommandError(
                f"--submitted-before must be an ISO date (YYYY-MM-DD), "
                f"got {options['submitted_before']!r}"
            )
        cutoff = datetime(
            cutoff_date.year,
            cutoff_date.month,
            cutoff_date.day,
            tzinfo=dt_timezone.utc,
        )

        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        verbosity = options["verbosity"]

        try:
            parquet = pq.ParquetFile(options["parquet"])
        except Exception as exc:
            raise CommandError(f"Could not open {options['parquet']}: {exc}") from exc

        # Row count before, so created-vs-updated is a measured delta rather
        # than a guess: bulk_create(update_conflicts=True) cannot report it.
        before = 0 if dry_run else LegacyRequest.objects.count()

        skipped = Counter()
        truncated = Counter()
        contacts = set()
        batch = []
        written = 0

        for arrow_batch in parquet.iter_batches(batch_size=batch_size, columns=COLUMNS):
            for rec in arrow_batch.to_pylist():
                obj = self._build(rec, cutoff, skipped, truncated)
                if obj is None:
                    continue
                batch.append(obj)
                contacts.add(obj.contact.lower())
                if len(batch) >= batch_size:
                    written += self._flush(batch, dry_run)
                    batch = []

        written += self._flush(batch, dry_run)

        created = 0 if dry_run else LegacyRequest.objects.count() - before

        claimed = 0
        if not dry_run and contacts:
            claimed = self._claim(contacts)

        if verbosity:
            self._report(
                written, created, skipped, truncated, claimed, dry_run
            )

    # ── internals ────────────────────────────────────────────────────────────

    def _build(self, rec, cutoff, skipped, truncated):
        """A LegacyRequest for this record, or None if it is filtered out."""
        if rec.get("status") != COMPLETED:
            skipped["not completed"] += 1
            return None

        submit_time, complete_time = _stage_times(rec.get("stage"))
        if submit_time is None:
            skipped["missing submit/complete time"] += 1
            return None
        if submit_time >= cutoff:
            skipped["at or after cutoff"] += 1
            return None

        contact = (rec.get("email") or "").strip()
        if not contact:
            skipped["empty contact"] += 1
            return None

        boundary = rec.get("boundary") or {}
        title = (boundary.get("title") or "").strip()
        name = (boundary.get("name") or "").strip()
        if not title or not name:
            skipped["empty boundary"] += 1
            return None

        releases = [r for r in (rec.get("release_data") or []) if r]
        rasters = [d for d in (rec.get("raster_data") or []) if d]
        # `count` counts entries; `titles` holds only those that carry a
        # display name. The two can legitimately differ -- the export has
        # entries with a null title -- so dataset_count is the number of
        # datasets requested, not the length of dataset_titles.
        titles = [r["custom_name"] for r in releases if r.get("custom_name")]
        titles += [d["title"] for d in rasters if d.get("title")]
        count = len(releases) + len(rasters)
        if count == 0:
            skipped["no datasets"] += 1
            return None

        values = {
            "contact": contact,
            "custom_name": (rec.get("custom_name") or "").strip(),
            "boundary_title": title,
            "boundary_name": name,
            "boundary_group": (boundary.get("group") or "").strip(),
        }
        for field, limit in MAX_LENGTHS.items():
            values[field] = self._trunc(values[field], limit, field, truncated)

        return LegacyRequest(
            id=rec["request_id"],
            submit_time=submit_time,
            complete_time=complete_time,
            dataset_titles=[
                self._trunc(t, 200, "dataset_titles", truncated) for t in titles
            ],
            dataset_count=count,
            data={
                "release_data": _plain(releases),
                "raster_data": _plain(rasters),
            },
            **values,
        )

    @staticmethod
    def _trunc(value, limit, field, truncated):
        """Cut `value` to `limit`, counting the cut.

        Array elements go through this too. Postgres raises
        `value too long for type character varying(200)` on an over-long
        element of `dataset_titles` -- it does NOT silently truncate -- so
        without this a single long title would abort the whole batch rather
        than lose characters. Truncating here keeps the import running and
        counts what it cut.
        """
        if value is not None and len(value) > limit:
            truncated[field] += 1
            return value[:limit]
        return value

    def _flush(self, batch, dry_run):
        if not batch or dry_run:
            return len(batch)
        with transaction.atomic():
            LegacyRequest.objects.bulk_create(
                batch,
                update_conflicts=True,
                unique_fields=["id"],
                update_fields=UPDATE_FIELDS,
            )
        return len(batch)

    def _claim(self, contacts):
        """Attach imported rows to accounts that already verified the address.

        Without this, a user who signed in before the import would see nothing
        until they next logged in and the login sweep ran.

        Deliberately does NOT call ``claim_requests_for_email``, even though it
        implements exactly these semantics: that helper claims ``Request`` rows
        too, so an archive import would quietly mutate the live requests table
        and report a figure covering both. Those rows get claimed by the login
        sweep anyway. The unclaimed-only filter is duplicated here instead, so
        the count this command prints means what it says.
        """
        from allauth.account.models import EmailAddress
        from django.contrib.auth import get_user_model

        owners = (
            EmailAddress.objects.filter(verified=True)
            .annotate(lowered=Lower("email"))
            .filter(lowered__in=contacts)
            .values_list("user_id", "email")
        )
        users = get_user_model().objects.in_bulk([uid for uid, _ in owners])
        claimed = 0
        for user_id, email in owners:
            user = users.get(user_id)
            if user is not None:
                claimed += LegacyRequest.objects.filter(
                    contact__iexact=email, user__isnull=True
                ).update(user=user)
        return claimed

    def _report(self, written, created, skipped, truncated, claimed, dry_run):
        verb = "would import" if dry_run else "imported"
        self.stdout.write(self.style.SUCCESS(f"{verb} {written} legacy requests"))
        if not dry_run:
            # The split is what tells a cutover run apart from a re-run: an
            # upsert reports the same total either way.
            self.stdout.write(
                f"  created {created}, updated {written - created}"
            )
        for reason, n in sorted(skipped.items()):
            self.stdout.write(f"  skipped {n}: {reason}")
        for field, n in sorted(truncated.items()):
            self.stdout.write(self.style.WARNING(f"  truncated {n}: {field}"))
        if not dry_run:
            self.stdout.write(f"  claimed by verified email: {claimed}")
