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

    def test_supplied_feature_counts_replace_the_featmap_query(self):
        a = dataset("a", False)
        for feature in self.features:
            Coverage.objects.create(dataset=a, geom=feature, status=1)
        counts = {self.fc.id: 2}
        with self.assertNumQueries(1):  # coverage rows only, no feat_map count
            result = page_coverage(self.pages, [a], feature_counts=counts)
        self.assertEqual(result, page_coverage(self.pages, [a]))
        self.assertEqual(result["gb-npl"], {a.id: FULL})

    def test_regional_dataset_full_partial_and_absent(self):
        full, partial, absent = dataset("full", False), dataset("partial", False), dataset("absent", False)
        for feature in self.features:
            Coverage.objects.create(dataset=full, geom=feature, status=1)
        Coverage.objects.create(dataset=partial, geom=self.features[0], status=1)
        Coverage.objects.create(dataset=absent, geom=self.features[0], status=0)

        result = page_coverage(self.pages, [full, partial, absent])

        self.assertEqual(result["gb-npl"], {full.id: FULL, partial.id: PARTIAL})


class PageCoverageAcrossCollectionsTests(ReplicaReadsTestMixin, TestCase):
    def collection(self, name, group, level, path):
        return FeatureCollection.objects.create(
            name=name, path=path, group_name=group, group_level=level,
            source_name="geoBoundaries", active=True, public=True,
        )

    def test_counts_are_summed_across_collections_and_pages(self):
        npl0 = self.collection("gB_x_NPL_ADM0", "gb_v6_npl", 0, "/npl0")
        npl1 = self.collection("gB_x_NPL_ADM1", "gb_v6_npl", 1, "/npl1")
        ind0 = self.collection("gB_x_IND_ADM0", "gb_v6_ind", 0, "/ind0")
        shared = Feature.objects.create(shape="POINT(0 0)")
        npl_only = Feature.objects.create(shape="POINT(1 1)")
        ind_only = Feature.objects.create(shape="POINT(2 2)")
        FeatMap.objects.create(fc=npl0, geom=shared)
        FeatMap.objects.create(fc=npl1, geom=shared)
        FeatMap.objects.create(fc=npl1, geom=npl_only)
        FeatMap.objects.create(fc=ind0, geom=ind_only)
        pages = build_pages([npl0, npl1, ind0])

        a, b = dataset("a", False), dataset("b", False)
        Coverage.objects.create(dataset=a, geom=shared, status=1)
        Coverage.objects.create(dataset=a, geom=npl_only, status=1)
        Coverage.objects.create(dataset=b, geom=shared, status=1)

        result = page_coverage(pages, [a, b])

        self.assertEqual(result["gb-npl"], {a.id: FULL, b.id: PARTIAL})
        self.assertEqual(result["gb-ind"], {})
