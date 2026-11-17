"""Measure labels for raster extract options, carried in the description.

A raster processing option's description reads "Label {{{detail}}}", e.g.
"Minimum temperature {{{The lowest temperature found anywhere in the feature,
in degrees Celsius.}}}". The label names what the option measures; the text in
braces explains it. A description without braces has no label.
"""

import re

_MEASURE = re.compile(r"^\s*(?P<label>.*?)\s*\{\{\{(?P<detail>.*?)\}\}\}\s*$", re.DOTALL)


def split_measure(description: str | None) -> tuple[str | None, str]:
    """(label, detail) from a processing option description.

    Without the "{{{...}}}" form the label is None and the detail is the
    description as it is.
    """
    text = description or ""
    match = _MEASURE.match(text)
    if not match:
        return None, text.strip()
    return match["label"] or None, match["detail"].strip()


def measure_label(short_name: str, description: str | None) -> str:
    """The option's label, falling back to its short name (e.g. "mean")."""
    label, _ = split_measure(description)
    return label or short_name
