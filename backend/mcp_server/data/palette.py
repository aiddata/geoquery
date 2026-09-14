"""Choropleth palettes and class breaks: a port of ``frontend/src/lib/viz.ts``.

The map app renders inside the chat client rather than in the SvelteKit app,
but it has to produce the same picture: the "Open in GeoQuery" link next to
every map takes the user to ``/viz/...`` with the same palette and
classification, and a map that recolours on arrival would make the two look
like different data.

Only the parts the server needs live here -- palettes, the two break methods,
and the value→colour lookup. The app's own JavaScript re-implements the same
two functions so switching column or year inside the iframe costs no round
trip; see ``apps/static/map.html``.
"""

from __future__ import annotations

# Keep in lockstep with PALETTES in frontend/src/lib/viz.ts.
PALETTES: dict[str, dict] = {
    "YlOrRd": {
        "label": "Yellow → Orange → Red",
        "colors": ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],
    },
    "Blues": {
        "label": "Blues",
        "colors": ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
    },
    "Greens": {
        "label": "Greens",
        "colors": ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
    },
    "Purples": {
        "label": "Purples",
        "colors": ["#f2f0f7", "#cbc9e2", "#9e9ac8", "#756bb1", "#54278f"],
    },
    "Oranges": {
        "label": "Oranges",
        "colors": ["#feedde", "#fdbe85", "#fd8d3c", "#e6550d", "#a63603"],
    },
    "YlGn": {
        "label": "Yellow → Green",
        "colors": ["#ffffcc", "#c2e699", "#78c679", "#31a354", "#006837"],
    },
    "RdYlGn": {
        "label": "Red → Yellow → Green ↔",
        "colors": ["#d7191c", "#fdae61", "#ffffbf", "#a6d96a", "#1a9641"],
    },
    "RdBu": {
        "label": "Red → Blue ↔",
        "colors": ["#ca0020", "#f4a582", "#f7f7f7", "#92c5de", "#0571b0"],
    },
    "PuOr": {
        "label": "Purple → Orange ↔",
        "colors": ["#5e3696", "#b2abd2", "#f7f7f7", "#fdb863", "#e66101"],
    },
    "BrBG": {
        "label": "Brown → Blue-Green ↔",
        "colors": ["#8c510a", "#d8b365", "#f5f5f5", "#5ab4ac", "#01665e"],
    },
}

DEFAULT_PALETTE = "YlOrRd"

# What the web app paints a feature with no value. Reused here so a null on the
# MCP map is the same grey as a null in the app.
NO_DATA_COLOR = "#cbd5e1"

CLASSIFICATIONS = ("quantile", "equal")


def resolve_palette(name: str | None) -> dict:
    """``{"name", "label", "colors"}`` for a palette, falling back to the default.

    An unknown name degrades rather than erroring: the model picking a palette
    that does not exist should still get a map.
    """
    key = name if name in PALETTES else DEFAULT_PALETTE
    return {"name": key, **PALETTES[key]}


def quantile_breaks(values: list[float], n: int) -> list[float]:
    """``n + 1`` break points at equal counts. Port of ``quantileBreaks``.

    A constant column collapses to a flat list rather than dividing by a zero
    range, which is what the TypeScript does too.
    """
    ordered = sorted(values)
    if not ordered:
        return []
    if ordered[0] == ordered[-1]:
        return [ordered[0]] * (n + 1)
    breaks = [ordered[0]]
    for i in range(1, n + 1):
        # round() here must match JS Math.round, which rounds .5 *up* rather
        # than to even the way Python's built-in round does.
        breaks.append(ordered[_js_round(i / n * (len(ordered) - 1))])
    return breaks


def equal_breaks(values: list[float], n: int) -> list[float]:
    """``n + 1`` break points at equal intervals. Port of ``equalBreaks``."""
    if not values:
        return []
    low, high = min(values), max(values)
    step = (high - low) / n
    return [low + i * step for i in range(n + 1)]


def compute_breaks(values: list[float], classification: str, classes: int) -> list[float]:
    if classification == "equal":
        return equal_breaks(values, classes)
    return quantile_breaks(values, classes)


def color_for(value, breaks: list[float], colors: list[str]) -> str:
    """Colour for one value. Port of ``getColor``."""
    if value is None or not breaks:
        return NO_DATA_COLOR
    try:
        number = float(value)
    except (TypeError, ValueError):
        return NO_DATA_COLOR
    if number != number:  # NaN
        return NO_DATA_COLOR
    for i in range(1, len(breaks)):
        if number <= breaks[i]:
            return colors[min(i - 1, len(colors) - 1)]
    return colors[-1]


def compute_stats(values: list[float]) -> dict | None:
    """``{min, max, mean, n}``, or ``None`` when nothing is numeric."""
    if not values:
        return None
    return {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "n": len(values),
    }


def _js_round(x: float) -> int:
    """JavaScript's ``Math.round``: halves go up, not to even.

    Python's ``round(0.5)`` is 0 and ``round(2.5)`` is 2; JS gives 1 and 3.
    Using the built-in would shift a quantile break by one sample on exactly
    the inputs where the two implementations are compared.
    """
    from math import floor

    return int(floor(x + 0.5))
