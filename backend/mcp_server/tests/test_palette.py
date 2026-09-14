"""The palette port must agree with frontend/src/lib/viz.ts.

The expected values below were produced by running the TypeScript functions
themselves under bun and diffing the output against this port -- the map
rendered in a chat client and the map behind the "Open in GeoQuery" link next
to it have to be the same picture, and the break points are where the two
would silently drift. Math.round vs Python round() is the trap.
"""

from django.test import SimpleTestCase

from mcp_server.data.palette import (
    DEFAULT_PALETTE,
    NO_DATA_COLOR,
    PALETTES,
    color_for,
    compute_breaks,
    compute_stats,
    equal_breaks,
    quantile_breaks,
    resolve_palette,
)


class QuantileBreaksTests(SimpleTestCase):
    def test_matches_the_typescript_for_a_simple_range(self):
        self.assertEqual(quantile_breaks([1, 2, 3, 4, 5], 5), [1, 2, 3, 3, 4, 5])

    def test_rounds_half_up_like_Math_round(self):
        # i/n * (len - 1) lands on x.5 for i=2, n=5 over nine values.
        # Python's round() rounds half to even and picks index 3; JS
        # Math.round rounds half up and picks index 4 -- a different break.
        self.assertEqual(
            quantile_breaks([0, 1, 1, 2, 3, 5, 8, 13, 21], 5), [0, 1, 2, 5, 8, 21]
        )

    def test_constant_column_collapses_instead_of_dividing_a_zero_range(self):
        self.assertEqual(quantile_breaks([5, 5, 5, 5], 3), [5, 5, 5, 5])

    def test_fewer_values_than_classes_still_yields_n_plus_one_breaks(self):
        self.assertEqual(quantile_breaks([1, 2], 5), [1, 1, 1, 2, 2, 2])

    def test_no_values_yields_no_breaks(self):
        self.assertEqual(quantile_breaks([], 5), [])


class EqualBreaksTests(SimpleTestCase):
    def test_equal_intervals_span_min_to_max(self):
        self.assertEqual(equal_breaks([1, 2, 3, 4, 5], 4), [1, 2, 3, 4, 5])

    def test_handles_negatives_and_floats(self):
        breaks = equal_breaks([-3.5, 0, 2.25, 7, 100], 3)

        self.assertEqual(breaks[0], -3.5)
        self.assertEqual(breaks[-1], 100)
        self.assertAlmostEqual(breaks[1] - breaks[0], breaks[2] - breaks[1])

    def test_no_values_yields_no_breaks(self):
        self.assertEqual(equal_breaks([], 5), [])


class ComputeBreaksTests(SimpleTestCase):
    def test_dispatches_on_classification_and_defaults_to_quantile(self):
        values = [1, 2, 3, 4, 5]

        self.assertEqual(compute_breaks(values, "equal", 4), equal_breaks(values, 4))
        self.assertEqual(
            compute_breaks(values, "quantile", 4), quantile_breaks(values, 4)
        )
        self.assertEqual(
            compute_breaks(values, "nonsense", 4), quantile_breaks(values, 4)
        )


class ColorForTests(SimpleTestCase):
    def setUp(self):
        self.colors = PALETTES["YlOrRd"]["colors"]
        self.breaks = quantile_breaks([1, 2, 3, 4, 5], 5)

    def test_value_lands_in_the_first_bucket_it_is_below(self):
        # breaks are [1, 2, 3, 3, 4, 5]; 2.5 and 3 both fall at index 2.
        self.assertEqual(color_for(2.5, self.breaks, self.colors), "#fecc5c")
        self.assertEqual(color_for(3, self.breaks, self.colors), "#fecc5c")

    def test_repeated_break_never_indexes_past_the_palette(self):
        """A duplicated break -- common when a column is mostly one value --
        makes the bucket index run past the last colour; it must clamp rather
        than raise."""
        self.assertEqual(color_for(5, [0, 0, 0, 0, 0, 0, 5], self.colors), "#bd0026")

    def test_above_the_top_break_takes_the_last_colour(self):
        self.assertEqual(color_for(99, self.breaks, self.colors), "#bd0026")

    def test_below_the_first_break_takes_the_first_colour(self):
        self.assertEqual(color_for(-5, self.breaks, self.colors), "#ffffb2")

    def test_no_data_values_take_the_no_data_grey(self):
        for value in (None, float("nan"), "forest"):
            self.assertEqual(color_for(value, self.breaks, self.colors), NO_DATA_COLOR)

    def test_no_breaks_means_no_data(self):
        self.assertEqual(color_for(1, [], self.colors), NO_DATA_COLOR)


class ResolvePaletteTests(SimpleTestCase):
    def test_known_name_round_trips_with_its_colours(self):
        palette = resolve_palette("Blues")

        self.assertEqual(palette["name"], "Blues")
        self.assertEqual(palette["colors"], PALETTES["Blues"]["colors"])

    def test_unknown_or_missing_name_degrades_to_the_default(self):
        """A model naming a palette that does not exist should still get a
        map, not an error it cannot act on."""
        for name in ("Viridis", None, ""):
            self.assertEqual(resolve_palette(name)["name"], DEFAULT_PALETTE)


class ComputeStatsTests(SimpleTestCase):
    def test_min_max_mean_and_count(self):
        self.assertEqual(
            compute_stats([1, 2, 3, 4]), {"min": 1, "max": 4, "mean": 2.5, "n": 4}
        )

    def test_no_values_yields_none(self):
        self.assertIsNone(compute_stats([]))
