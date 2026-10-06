"""Dataset ingest JSON → model field mapping."""

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from datasets.ingest import _dataset_fields_from_json


class DatasetFieldsFromJsonTests(SimpleTestCase):
    def test_attribution_keys_are_kept(self):
        """license/license_url are Dataset fields, so ingest JSONs carrying
        them persist rather than being logged-and-dropped as unknown keys."""
        fields = _dataset_fields_from_json(
            {
                "name": "ds",
                "path": "/data/rasters/ds",
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "citation": "Author, A. (2020).",
                "source_name": "Agency",
                "source_url": "https://agency.test",
            }
        )

        self.assertEqual(fields["license"], "CC BY 4.0")
        self.assertEqual(
            fields["license_url"], "https://creativecommons.org/licenses/by/4.0/"
        )
        self.assertEqual(fields["citation"], "Author, A. (2020).")

    def test_unknown_keys_are_still_dropped(self):
        fields = _dataset_fields_from_json(
            {"name": "ds", "path": "/data/rasters/ds", "not_a_field": 1}
        )

        self.assertNotIn("not_a_field", fields)

    def test_mapped_is_derived_from_mappings(self):
        base = {"name": "ds", "path": "/data/rasters/ds"}

        self.assertFalse(_dataset_fields_from_json(base)["mapped"])
        self.assertTrue(
            _dataset_fields_from_json({**base, "mappings": {"a": 1}})["mapped"]
        )


class MetadataUpdatePlanTests(SimpleTestCase):
    """_metadata_update_plan decides what a --metadata-only run applies.

    The logic is a pure function so it can be exercised without a database:
    it takes the parsed ingest JSON plus the stored row's structural values,
    and returns the fields to write and any structural drift it refused to
    write. See docs/superpowers/specs/2026-10-06-metadata-only-ingest-design.md
    """

    # A row whose structural fields match STORED below, so the default case
    # has no drift and tests can focus on one thing at a time.
    STORED = {
        "path": "/data/datasets/ds",
        "type": "raster",
        "file_extension": ".tif",
        "file_mask": "ds_YYYY.tif",
    }

    def _json(self, **overrides):
        data = {
            "name": "ds",
            **self.STORED,
            "license": "CC-BY-4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "source_name": "Agency",
            "source_url": "https://agency.test",
            "citation": "Author, A. (2020).",
            "title": "A dataset",
            "tags": ["one", "two"],
        }
        data.update(overrides)
        return data

    def test_applies_descriptive_metadata(self):
        from datasets.ingest import _metadata_update_plan

        fields, _ = _metadata_update_plan(self._json(), self.STORED)

        self.assertEqual(fields["license"], "CC-BY-4.0")
        self.assertEqual(fields["source_name"], "Agency")
        self.assertEqual(fields["source_url"], "https://agency.test")
        self.assertEqual(fields["citation"], "Author, A. (2020).")
        self.assertEqual(fields["title"], "A dataset")
        self.assertEqual(fields["tags"], ["one", "two"])

    def test_never_writes_structural_fields(self):
        from datasets.ingest import _metadata_update_plan

        fields, _ = _metadata_update_plan(self._json(), self.STORED)

        for key in ("path", "type", "file_extension", "file_mask"):
            self.assertNotIn(key, fields)

    def test_never_writes_name(self):
        """name is the lookup key, not a field to update."""
        from datasets.ingest import _metadata_update_plan

        fields, _ = _metadata_update_plan(self._json(), self.STORED)

        self.assertNotIn("name", fields)

    def test_never_writes_derived_fields(self):
        from datasets.ingest import _metadata_update_plan

        data = self._json(
            spatial_extent="POLYGON((0 0,1 0,1 1,0 1,0 0))",
            temporal_start="2000-01-01T00:00:00Z",
            temporal_end="2020-01-01T00:00:00Z",
            temporal_name="year",
            temporal_type="yearly",
        )

        fields, _ = _metadata_update_plan(data, self.STORED)

        for key in (
            "spatial_extent",
            "temporal_start",
            "temporal_end",
            "temporal_name",
            "temporal_type",
        ):
            self.assertNotIn(key, fields)

    def test_never_writes_mapped_flag(self):
        """mapped is derived from mappings, which this mode does not sync."""
        from datasets.ingest import _metadata_update_plan

        fields, _ = _metadata_update_plan(
            self._json(mappings={"a": 1}), self.STORED
        )

        self.assertNotIn("mapped", fields)

    def test_reports_no_drift_when_structural_fields_match(self):
        from datasets.ingest import _metadata_update_plan

        _, drift = _metadata_update_plan(self._json(), self.STORED)

        self.assertEqual(drift, {})

    def test_reports_drift_when_structural_field_differs(self):
        from datasets.ingest import _metadata_update_plan

        data = self._json(path="/data/datasets/ds/moved")

        fields, drift = _metadata_update_plan(data, self.STORED)

        self.assertEqual(
            drift, {"path": ("/data/datasets/ds", "/data/datasets/ds/moved")}
        )
        # the metadata update still proceeds
        self.assertEqual(fields["license"], "CC-BY-4.0")

    def test_reports_drift_for_every_differing_structural_field(self):
        from datasets.ingest import _metadata_update_plan

        data = self._json(file_extension=".nc", file_mask="ds_YYYYMM.nc")

        _, drift = _metadata_update_plan(data, self.STORED)

        self.assertEqual(
            drift,
            {
                "file_extension": (".tif", ".nc"),
                "file_mask": ("ds_YYYY.tif", "ds_YYYYMM.nc"),
            },
        )

    def test_absent_structural_key_is_not_drift(self):
        """A JSON that omits a structural field is not claiming a change."""
        from datasets.ingest import _metadata_update_plan

        data = self._json()
        del data["file_mask"]

        _, drift = _metadata_update_plan(data, self.STORED)

        self.assertEqual(drift, {})


class MetadataOnlyFlagTests(SimpleTestCase):
    """--metadata-only is incompatible with the full-ingest update flags."""

    def test_rejects_combination_with_update(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("ingest_dataset", "acled", metadata_only=True, update=True)

        self.assertIn("--metadata-only", str(ctx.exception))

    def test_rejects_combination_with_update_or_insert(self):
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "ingest_dataset",
                "acled",
                metadata_only=True,
                update_or_insert=True,
            )

        self.assertIn("--metadata-only", str(ctx.exception))


class LoadJsonTests(SimpleTestCase):
    """_load_json is shared by ingest_dataset and update_dataset_metadata."""

    def test_returns_dict_unchanged(self):
        from datasets.ingest import _load_json

        data = {"name": "ds"}

        self.assertIs(_load_json(data), data)

    def test_reads_a_path(self):
        import json
        import tempfile
        from pathlib import Path

        from datasets.ingest import _load_json

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ds.json"
            p.write_text(json.dumps({"name": "ds", "license": "CC0-1.0"}))

            self.assertEqual(
                _load_json(p), {"name": "ds", "license": "CC0-1.0"}
            )

    def test_rejects_other_types(self):
        from datasets.ingest import _load_json

        with self.assertRaises(TypeError):
            _load_json("/not/a/path/object")


class UpdateDatasetMetadataTests(TestCase):
    """update_dataset_metadata applies metadata without reading data files.

    Requires a database, so it does not run on a host without Docker access;
    see docs/superpowers/specs/2026-10-06-metadata-only-ingest-design.md
    """

    def setUp(self):
        from datasets.models import Dataset

        self.dataset = Dataset.objects.create(
            name="ds",
            path="/data/datasets/ds",
            type="raster",
            file_extension=".tif",
            file_mask="ds_YYYY.tif",
            title="Old title",
        )

    def _json(self, **overrides):
        data = {
            "name": "ds",
            "path": "/data/datasets/ds",
            "type": "raster",
            "file_extension": ".tif",
            "file_mask": "ds_YYYY.tif",
            "license": "CC-BY-4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "source_name": "Agency",
            "source_url": "https://agency.test",
            "title": "New title",
        }
        data.update(overrides)
        return data

    def test_applies_metadata_to_existing_dataset(self):
        from datasets.ingest import update_dataset_metadata

        update_dataset_metadata(self._json())

        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.license, "CC-BY-4.0")
        self.assertEqual(self.dataset.source_name, "Agency")
        self.assertEqual(self.dataset.title, "New title")

    def test_raises_when_dataset_does_not_exist(self):
        from datasets.ingest import update_dataset_metadata

        with self.assertRaises(ValueError):
            update_dataset_metadata(self._json(name="nope"))

    def test_does_not_write_structural_fields(self):
        from datasets.ingest import update_dataset_metadata

        update_dataset_metadata(self._json(path="/data/datasets/ds/moved"))

        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.path, "/data/datasets/ds")

    def test_leaves_mappings_untouched(self):
        from datasets.ingest import update_dataset_metadata
        from datasets.models import Mapping

        Mapping.objects.create(dataset=self.dataset, map_name="a", map_val=1)

        update_dataset_metadata(self._json(mappings={"b": 2}))

        self.assertEqual(
            list(self.dataset.mappings.values_list("map_name", flat=True)), ["a"]
        )

    def test_leaves_processing_options_untouched(self):
        from analytics.models import ProcessingOption
        from datasets.ingest import update_dataset_metadata

        ProcessingOption.objects.create(
            dataset=self.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
        )

        update_dataset_metadata(
            self._json(
                processing_options=[
                    {"short_name": "sum", "function": "rasterstats_default_sum"}
                ]
            )
        )

        self.assertEqual(
            list(
                ProcessingOption.objects.filter(
                    dataset=self.dataset
                ).values_list("short_name", flat=True)
            ),
            ["mean"],
        )

    def test_does_not_require_the_data_files_to_exist(self):
        """The whole point: no filesystem access, so a bogus path is fine."""
        from datasets.ingest import update_dataset_metadata

        Dataset = self.dataset.__class__
        Dataset.objects.filter(name="ds").update(path="/nonexistent/path")

        update_dataset_metadata(self._json(path="/nonexistent/path"))

        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.license, "CC-BY-4.0")
