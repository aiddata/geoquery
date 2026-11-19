"""Share links (GEO-126): POST /api/analytics/shares/ saves a recipe, GET
/api/analytics/shares/<id>/ returns it checked against the catalog."""

from django.core.cache import cache
from django.test import TestCase

from analytics.models import SharedRecipe
from analytics.recipe import MAX_RECIPE_BYTES, share_id, normalize_recipe
from analytics.tests.test_request_recipe import make_set, raster
from geoquery.testing import ReplicaReadsTestMixin


def item(name, measures=("mean",), years=("2020",), **extra):
    return {"customName": f"My {name}", "datasetName": name, "datasetTitle": name, "datasetType": "raster",
            "processingClass": "zonal_stats", "extractTypes": list(measures),
            "resources": [f"{name}_{y}" for y in years], "resourceLabels": list(years), **extra}


class ShareLinkTests(ReplicaReadsTestMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.adm1, self.adm1_features = make_set("gha_adm1")
        self.adm2, self.adm2_features = make_set("gha_adm2", n=3)
        raster("ntl")

    def recipe(self, fc_ids=None, feature_ids=(), datasets=None):
        return {"v": 1, "boundaries": {"fcIds": fc_ids or [self.adm1.id], "featureIds": list(feature_ids)},
                "datasets": datasets if datasets is not None else [item("ntl")]}

    def share(self, recipe, expect=201):
        response = self.client.post("/api/analytics/shares/", {"recipe": recipe}, content_type="application/json")
        self.assertEqual(response.status_code, expect, response.content)
        return response.json()

    def open(self, sid, expect=200):
        response = self.client.get(f"/api/analytics/shares/{sid}/")
        self.assertEqual(response.status_code, expect, response.content)
        return response.json()

    def test_share_and_open(self):
        link = self.share(self.recipe())
        self.assertEqual(len(link["id"]), 10)
        self.assertEqual(link["path"], f"/s/{link['id']}")
        body = self.open(link["id"])
        self.assertEqual(body["recipe"]["boundaries"], {"fcIds": [self.adm1.id], "featureIds": []})
        [ds] = body["recipe"]["datasets"]
        # A raster's name given on Review is kept
        self.assertEqual((ds["customName"], ds["datasetTitle"]), ("My ntl", "ntl title"))
        self.assertEqual([fc["id"] for fc in body["boundary_sets"]], [self.adm1.id])
        self.assertEqual(body["dropped"], {"features": 0, "datasets": [], "options": []})

    def test_the_same_recipe_gives_the_same_link(self):
        first = self.share(self.recipe())
        again = self.share(self.recipe(), expect=200)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(SharedRecipe.objects.count(), 1)
        other = self.share(self.recipe(fc_ids=[self.adm2.id]))
        self.assertNotEqual(other["id"], first["id"])

    def test_unknown_fields_are_not_stored(self):
        recipe = self.recipe(datasets=[item("ntl", secret="x")])
        recipe["email"] = "a@example.org"
        link = self.share(recipe)
        stored = SharedRecipe.objects.get(id=link["id"]).recipe
        self.assertNotIn("email", stored)
        self.assertNotIn("secret", stored["datasets"][0])

    def test_features_kept_for_one_set_only(self):
        some = self.adm2_features[:2]
        link = self.share(self.recipe(fc_ids=[self.adm2.id], feature_ids=some + [self.adm1_features[0]]))
        body = self.open(link["id"])
        self.assertEqual(body["recipe"]["boundaries"]["featureIds"], some)
        self.assertEqual(body["dropped"]["features"], 1)
        # Several sets: features don't apply and aren't stored
        recipe = normalize_recipe(self.recipe(fc_ids=[self.adm1.id, self.adm2.id], feature_ids=some))
        self.assertEqual(recipe["boundaries"]["featureIds"], [])

    def test_opening_lists_what_no_longer_applies(self):
        link = self.share(self.recipe(fc_ids=[self.adm1.id, 999999],
                                      datasets=[item("ntl", years=("2020", "1999")), item("gone")]))
        body = self.open(link["id"])
        # The gone boundary set stays in the recipe for the loader to report
        self.assertEqual(body["recipe"]["boundaries"]["fcIds"], [self.adm1.id, 999999])
        self.assertEqual([fc["id"] for fc in body["boundary_sets"]], [self.adm1.id])
        self.assertEqual(body["dropped"]["datasets"], [{"name": "gone", "title": "gone", "reason": "unavailable"}])
        self.assertEqual(body["dropped"]["options"][0]["periods"], ["1999"])

    def test_invalid_recipes_are_refused(self):
        for bad in [None, {"v": 2}, {"v": 1, "boundaries": {"fcIds": []}, "datasets": []},
                    {"v": 1, "boundaries": {"fcIds": ["x"]}, "datasets": []},
                    {"v": 1, "boundaries": {"fcIds": [1]}, "datasets": [{"customName": "x"}]}]:
            self.share(bad, expect=400)

    def test_too_large_to_share(self):
        big = [item("ntl", years=[str(y) for y in range(MAX_RECIPE_BYTES // 5)])]
        self.share(self.recipe(datasets=big), expect=400)

    def test_unknown_link(self):
        self.open("nope", expect=404)

    def test_share_id_is_stable(self):
        recipe = normalize_recipe(self.recipe())
        self.assertEqual(share_id(recipe), share_id(dict(reversed(list(recipe.items())))))

    def test_creating_links_is_rate_limited(self):
        from unittest import mock

        from analytics.throttles import ShareCreateThrottle

        with mock.patch.object(ShareCreateThrottle, "THROTTLE_RATES", {"share_create": "2/hour"}):
            self.share(self.recipe())
            self.share(self.recipe(fc_ids=[self.adm2.id]))
            self.share(self.recipe(fc_ids=[self.adm1.id, self.adm2.id]), expect=429)
