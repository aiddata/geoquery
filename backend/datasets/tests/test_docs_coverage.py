from django.test import TestCase

from analytics.models import Coverage
from datasets.docs.coverage import FULL, PARTIAL, page_coverage
from datasets.docs.grouping import build_pages
from datasets.models import Dataset
from features.models import Feature, FeatMap, FeatureCollection
from geoquery.testing import ReplicaReadsTestMixin


def dataset(name, is_global):
    return Dataset.objects.create(name=name, path=f"/{name}", type="raster", title=name,
                                  is_global=is_global, active=True, public=True)


class PageCoverageTests(ReplicaReadsTestMixin, TestCase):
    def setUp(self):
        self.fc = FeatureCollection.objects.create(
            name="gB_x_NPL_ADM1", path="/npl1", group_name="gb_v6_npl", group_level=1,
            source_name="geoBoundaries", active=True, public=True,
        )
        self.features = []
        for _ in range(2):
            feature = Feature.objects.create(shape="POINT(0 0)")
            FeatMap.objects.create(fc=self.fc, geom=feature)
            self.features.append(feature)
        self.pages = build_pages([self.fc])

    def test_global_dataset_covers_every_page_in_full(self):
        world = dataset("world", True)
        self.assertEqual(page_coverage(self.pages, [world]), {"gb-npl": {world.id: FULL}})

    def test_regional_dataset_full_partial_and_absent(self):
        full, partial, absent = dataset("full", False), dataset("partial", False), dataset("absent", False)
        for feature in self.features:
            Coverage.objects.create(dataset=full, geom=feature, status=1)
        Coverage.objects.create(dataset=partial, geom=self.features[0], status=1)
        Coverage.objects.create(dataset=absent, geom=self.features[0], status=0)

        result = page_coverage(self.pages, [full, partial, absent])

        self.assertEqual(result["gb-npl"], {full.id: FULL, partial.id: PARTIAL})
