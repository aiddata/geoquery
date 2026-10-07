import io
import tempfile
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from analytics.models import LegacyRequest

User = get_user_model()

# Only the columns the command reads, matching the types that
# request_migration/requests_to_parquet.py writes.
SCHEMA = pa.schema(
    [
        ("request_id", pa.string()),
        ("email", pa.string()),
        ("custom_name", pa.string()),
        ("status", pa.int64()),
        ("stage", pa.list_(pa.struct([("name", pa.string()), ("time", pa.int64())]))),
        (
            "boundary",
            pa.struct(
                [
                    ("title", pa.string()),
                    ("group", pa.string()),
                    ("name", pa.string()),
                    ("description", pa.string()),
                    ("path", pa.string()),
                ]
            ),
        ),
        (
            "release_data",
            pa.list_(
                pa.struct(
                    [
                        ("dataset", pa.string()),
                        ("custom_name", pa.string()),
                        ("hash", pa.string()),
                        ("filters", pa.map_(pa.string(), pa.list_(pa.string()))),
                    ]
                )
            ),
        ),
        (
            "raster_data",
            pa.list_(
                pa.struct(
                    [
                        ("name", pa.string()),
                        ("title", pa.string()),
                        ("base", pa.string()),
                        ("type", pa.string()),
                        ("custom_name", pa.string()),
                        ("temporal_type", pa.string()),
                        ("extract_types", pa.list_(pa.string())),
                        (
                            "files",
                            pa.list_(
                                pa.struct(
                                    [
                                        ("name", pa.string()),
                                        ("path", pa.string()),
                                        ("display", pa.string()),
                                        ("bytes", pa.int64()),
                                        ("start", pa.int64()),
                                        ("end", pa.int64()),
                                    ]
                                )
                            ),
                        ),
                    ]
                )
            ),
        ),
    ]
)

TS_2017 = int(datetime(2017, 3, 15, 18, 20, tzinfo=dt_timezone.utc).timestamp())
TS_2021 = int(datetime(2021, 6, 1, 9, 0, tzinfo=dt_timezone.utc).timestamp())


def record(
    oid,
    *,
    email="alice@example.com",
    name="Request 03-15-17 18:20",
    status=1,
    submitted=TS_2017,
    boundary_title="Tanzania ADM3 Boundary - GADM 2.8",
    boundary_name="tza_adm3_gadm28",
    releases=("World Bank Geocoded Aid Data v1.4.1",),
    rasters=("Population (GPW V4, UN Adjusted)",),
):
    return {
        "request_id": oid,
        "email": email,
        "custom_name": name,
        "status": status,
        "stage": [
            {"name": "submitted", "time": submitted},
            {"name": "completed", "time": submitted + 3600},
        ],
        "boundary": {
            "title": boundary_title,
            "group": "tza_gadm28",
            "name": boundary_name,
            "description": "GADM boundary",
            "path": "/data/TZA_adm3.geojson",
        },
        "release_data": [
            {"dataset": f"ds_{i}", "custom_name": t, "hash": "h", "filters": []}
            for i, t in enumerate(releases)
        ],
        "raster_data": [
            {
                "name": f"r_{i}",
                "title": t,
                "base": "/data",
                "type": "raster",
                "custom_name": t,
                "temporal_type": "year",
                "extract_types": ["mean"],
                "files": [],
            }
            for i, t in enumerate(rasters)
        ],
    }


def write_parquet(records, directory):
    path = Path(directory) / "requests.parquet"
    pq.write_table(pa.Table.from_pylist(records, schema=SCHEMA), path)
    return str(path)


class ImportLegacyRequestsTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_import(self, records, before="2026-01-01", **kwargs):
        path = write_parquet(records, self.tmp.name)
        call_command(
            "import_legacy_requests",
            parquet=path,
            submitted_before=before,
            verbosity=0,
            **kwargs,
        )

    def test_imports_a_completed_record(self):
        self.run_import([record("a" * 24)])

        obj = LegacyRequest.objects.get(pk="a" * 24)
        self.assertEqual(obj.contact, "alice@example.com")
        self.assertEqual(obj.boundary_name, "tza_adm3_gadm28")
        self.assertEqual(obj.dataset_count, 2)
        self.assertEqual(
            obj.dataset_titles,
            ["World Bank Geocoded Aid Data v1.4.1", "Population (GPW V4, UN Adjusted)"],
        )
        self.assertEqual(
            obj.submit_time,
            datetime(2017, 3, 15, 18, 20, tzinfo=dt_timezone.utc),
        )

    def test_excludes_rows_at_or_after_cutoff(self):
        self.run_import(
            [record("a" * 24, submitted=TS_2017), record("b" * 24, submitted=TS_2021)],
            before="2021-01-01",
        )
        self.assertEqual(
            list(LegacyRequest.objects.values_list("pk", flat=True)), ["a" * 24]
        )

    def test_excludes_non_completed(self):
        self.run_import([record("a" * 24, status=-2), record("b" * 24, status=1)])
        self.assertEqual(
            list(LegacyRequest.objects.values_list("pk", flat=True)), ["b" * 24]
        )

    def test_skips_empty_contact_boundary_and_datasets(self):
        self.run_import(
            [
                record("a" * 24, email=""),
                record("b" * 24, boundary_title="", boundary_name=""),
                record("c" * 24, releases=(), rasters=()),
                record("d" * 24),
            ]
        )
        self.assertEqual(
            list(LegacyRequest.objects.values_list("pk", flat=True)), ["d" * 24]
        )

    def test_rerun_is_idempotent(self):
        records = [record("a" * 24)]
        self.run_import(records)
        first = LegacyRequest.objects.get(pk="a" * 24)
        before = first.imported_at

        self.run_import(records)

        self.assertEqual(LegacyRequest.objects.count(), 1)
        again = LegacyRequest.objects.get(pk="a" * 24)
        self.assertEqual(again.custom_name, first.custom_name)
        self.assertEqual(again.dataset_titles, first.dataset_titles)
        # Strictly greater: imported_at is in UPDATE_FIELDS precisely so a
        # re-import records that it ran. assertGreaterEqual would pass even if
        # the field were never written.
        self.assertGreater(again.imported_at, before)

    def test_later_cutoff_adds_only_newer_rows(self):
        records = [record("a" * 24, submitted=TS_2017), record("b" * 24, submitted=TS_2021)]
        self.run_import(records, before="2021-01-01")
        self.run_import(records, before="2026-01-01")
        self.assertEqual(LegacyRequest.objects.count(), 2)

    def test_dry_run_writes_nothing(self):
        self.run_import([record("a" * 24)], dry_run=True)
        self.assertEqual(LegacyRequest.objects.count(), 0)

    def test_truncates_overlong_values(self):
        self.run_import([record("a" * 24, name="x" * 250)])
        self.assertEqual(len(LegacyRequest.objects.get(pk="a" * 24).custom_name), 100)

    def test_claims_verified_email_owners(self):
        user = User.objects.create_user(username="alice", email="alice@example.com")
        EmailAddress.objects.create(
            user=user, email="alice@example.com", verified=True, primary=True
        )

        self.run_import([record("a" * 24)])

        self.assertEqual(LegacyRequest.objects.get(pk="a" * 24).user, user)

    def test_truncates_and_counts_overlong_dataset_titles(self):
        path = write_parquet([record("a" * 24, releases=("y" * 250,))], self.tmp.name)
        out = io.StringIO()
        call_command(
            "import_legacy_requests",
            parquet=path,
            submitted_before="2026-01-01",
            stdout=out,
        )
        titles = LegacyRequest.objects.get(pk="a" * 24).dataset_titles
        self.assertEqual(len(titles[0]), 200)
        self.assertIn("truncated 1: dataset_titles", out.getvalue())
