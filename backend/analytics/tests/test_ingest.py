from django.test import TestCase

from analytics.ingest import ingest_custom_boundary
from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from datasets.models import Dataset, DatasetResource


def make_geojson_fc(n=1):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(i), float(i)]},
                "properties": {"name": f"feat-{i}"},
            }
            for i in range(n)
        ],
    }


class IngestCustomBoundaryTest(TestCase):
    """ingest_custom_boundary's on-demand ExtractTask creation.

    Covers ExtractTask rows built with dataset_id/resource_ids against the
    new schema, RequestMap rows carrying the matching dataset_id, and that
    bulk_create(ignore_conflicts=True) still dedupes via the migration 0022
    unique indexes now that they're keyed on dataset_id/resource_ids instead
    of the old resource FK.
    """

    def setUp(self):
        self.dataset = Dataset.objects.create(
            name="ds", path="/data/ds", active=True, public=True
        )
        self.resource = DatasetResource.objects.create(
            dataset=self.dataset, name="ds-r1", path="r1.tif"
        )
        self.po = ProcessingOption.objects.create(
            dataset=self.dataset,
            short_name="mean",
            function="rasterstats_default_mean",
            active=True,
            public=True,
        )

    def make_request(self):
        return Request.objects.create(
            contact="a@example.com",
            source="web_custom",
            status=3,
            data={"upload_metadata": {}},
        )

    def test_creates_tasks_with_dataset_id_and_resource_ids(self):
        req = self.make_request()
        geojson = make_geojson_fc(2)

        task_count, warnings = ingest_custom_boundary(
            geojson, [{"datasetName": "ds"}], req, user=None
        )

        self.assertEqual(warnings, [])
        self.assertEqual(task_count, 2)  # 2 features x 1 resource x 1 po
        tasks = list(ExtractTask.objects.all())
        self.assertEqual(len(tasks), 2)
        for task in tasks:
            self.assertEqual(task.dataset_id, self.dataset.id)
            self.assertEqual(task.resource_ids, [self.resource.id])
            self.assertEqual(task.priority, 1)

    def test_request_map_rows_carry_dataset_id(self):
        req = self.make_request()
        geojson = make_geojson_fc(1)

        ingest_custom_boundary(geojson, [{"datasetName": "ds"}], req, user=None)

        maps = list(RequestMap.objects.filter(request=req))
        self.assertEqual(len(maps), 1)
        self.assertEqual(maps[0].dataset_id, self.dataset.id)
        self.assertEqual(maps[0].task.dataset_id, self.dataset.id)

    def test_duplicate_dataset_entry_in_one_payload_does_not_duplicate_tasks(self):
        # Same dataset named twice in one submission (e.g. distinct extract
        # types resolving to the same resource/po) must dedupe through the
        # unique index + ignore_conflicts, not create two ExtractTask rows
        # for the same (dataset_id, fm, po, resource_ids, kwargs).
        req = self.make_request()
        geojson = make_geojson_fc(1)

        task_count, _ = ingest_custom_boundary(
            geojson, [{"datasetName": "ds"}, {"datasetName": "ds"}], req, user=None
        )

        self.assertEqual(task_count, 1)
        self.assertEqual(ExtractTask.objects.count(), 1)
        self.assertEqual(RequestMap.objects.filter(request=req).count(), 1)

    def test_raises_when_no_dataset_resolves(self):
        req = self.make_request()
        geojson = make_geojson_fc(1)

        with self.assertRaises(ValueError):
            ingest_custom_boundary(
                geojson, [{"datasetName": "does-not-exist"}], req, user=None
            )
