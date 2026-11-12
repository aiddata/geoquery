from django.test import TestCase

from datasets.models import Dataset
from datasets.serializers import DatasetDetailSerializer


def detail(**kwargs):
    kwargs.setdefault("name", "ds")
    kwargs.setdefault("path", f"/data/rasters/{kwargs['name']}")
    kwargs.setdefault("type", "raster")
    return DatasetDetailSerializer(Dataset.objects.create(**kwargs)).data


class DatasetDetailMetadataTests(TestCase):
    def test_metadata_fields_are_exposed(self):
        data = detail(
            details="Rasterization of point based data.",
            variable_description="deaths per 1,000 child-years",
            is_global=True,
            other={"resolution": "0.008333333333333", "version": "v301"},
        )
        self.assertEqual(data["details"], "Rasterization of point based data.")
        self.assertEqual(data["variable_description"], "deaths per 1,000 child-years")
        self.assertTrue(data["is_global"])
        self.assertAlmostEqual(data["resolution"], 0.008333333333333)
        self.assertEqual(data["version"], "v301")
        self.assertIsNotNone(data["date_added"])

    def test_missing_or_unusable_values_are_null(self):
        for i, other in enumerate(
            [None, {}, {"resolution": ""}, {"resolution": "n/a"}, {"resolution": "0"},
             {"version": "  "}]
        ):
            data = detail(name=f"ds{i}", other=other)
            self.assertIsNone(data["resolution"], other)
            self.assertIsNone(data["version"], other)
