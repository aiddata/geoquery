"""Simplified-geometry reads, and which tier they come from."""

from django.test import TestCase

from mcp_server.data.geometry import (
    _COARSE_TABLE,
    _FINE_TABLE,
    bbox_for,
    geometries_for,
    pick_table,
)

from .factories import World, make_fc, square


class PickTableTests(TestCase):
    """A continent-wide view wants the coarse tier; a district does not.

    Reading the fine tier for a whole-world selection is the difference
    between a payload a chat client can hold and one it cannot.
    """

    def test_a_small_extent_uses_the_fine_tier(self):
        self.assertEqual(pick_table([0, 0, 3, 2]), _FINE_TABLE)

    def test_a_continental_extent_uses_the_coarse_tier(self):
        self.assertEqual(pick_table([-20, -35, 55, 38]), _COARSE_TABLE)

    def test_the_longer_side_decides(self):
        self.assertEqual(pick_table([0, 0, 40, 1]), _COARSE_TABLE)
        self.assertEqual(pick_table([0, 0, 1, 40]), _COARSE_TABLE)

    def test_an_unknown_extent_falls_back_to_the_fine_tier(self):
        self.assertEqual(pick_table(None), _FINE_TABLE)


class GeometriesForTests(TestCase):
    def setUp(self):
        self.world = World().simplify()
        self.geom_ids = [f.id for f in self.world.features]

    def test_returns_geojson_geometry_per_feature(self):
        geometries = geometries_for(
            [self.world.fc.id], self.geom_ids, [0, 0, 3, 1]
        )

        self.assertEqual(set(geometries), set(self.geom_ids))
        for geometry in geometries.values():
            self.assertEqual(geometry["type"], "Polygon")

    def test_coordinates_come_back_in_lon_lat(self):
        """The simplified tables store EPSG:3857; without the transform these
        would be in the millions."""
        geometries = geometries_for([self.world.fc.id], self.geom_ids)

        for geometry in geometries.values():
            for lon, lat in geometry["coordinates"][0]:
                self.assertLess(abs(lon), 180)
                self.assertLess(abs(lat), 90)

    def test_a_feature_outside_the_collection_is_not_returned(self):
        other = make_fc(name="other_fc")
        from features.models import Feature, FeatMap

        stranger = Feature.objects.create(shape=square(50.0, 50.0))
        FeatMap.objects.create(fc=other, geom=stranger, name="Elsewhere")

        geometries = geometries_for(
            [self.world.fc.id], [*self.geom_ids, stranger.id]
        )

        self.assertNotIn(stranger.id, geometries)

    def test_empty_inputs_short_circuit(self):
        self.assertEqual(geometries_for([], self.geom_ids), {})
        self.assertEqual(geometries_for([self.world.fc.id], []), {})

    def test_a_collection_with_no_simplified_rows_yields_nothing(self):
        """features.matviews drops geometry that simplified to something empty
        or invalid; callers must cope with a feature having none."""
        fc = make_fc(name="unsimplified")
        from features.models import Feature, FeatMap

        feature = Feature.objects.create(shape=square(5.0, 5.0))
        FeatMap.objects.create(fc=fc, geom=feature, name="Nowhere")

        self.assertEqual(geometries_for([fc.id], [feature.id]), {})


class BboxForTests(TestCase):
    def setUp(self):
        self.world = World()

    def test_covers_every_feature(self):
        self.assertEqual(
            bbox_for([f.id for f in self.world.features]), [0.0, 0.0, 3.0, 1.0]
        )

    def test_no_features_means_no_bbox(self):
        self.assertIsNone(bbox_for([]))
