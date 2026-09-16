"""Argument shapes shared across tools.

FastMCP derives each tool's JSON schema from its signature, so these types are
what the model actually sees. They are kept small and flat on purpose: a
nested, optional-heavy schema is one a model fills in wrong.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

Format = Literal["table", "geojson"]
Shape = Literal["wide", "long"]
Classification = Literal["quantile", "equal"]
CitationStyle = Literal["apa", "plain"]


class DatasetSpec(TypedDict, total=False):
    """One dataset within an export request.

    Mirrors the web app's submission shape (``datasetName``/``extractTypes``/
    ``resources``/``kwargs``) but in snake_case, because that is what reads
    naturally to a model. ``analytics.services`` still speaks the camelCase
    form, so ``tools.requests`` translates between the two -- deliberately in
    one place, so the web contract is not reshaped to suit the MCP server.
    """

    name: Annotated[str, Field(description="Dataset name, e.g. 'esa_landcover'.")]
    extract_types: Annotated[
        list[str],
        Field(description="Extract types to run, e.g. ['mean']. Empty = all available."),
    ]
    resources: Annotated[
        list[str],
        Field(description="Resource names to include. Empty = every year/file."),
    ]
    kwargs: Annotated[
        dict | None,
        Field(description="Dataset-specific filter arguments, if the dataset takes any."),
    ]


# Recurring argument descriptions. Written once so the same wording reaches the
# model from get_data, show_map, get_citations and the CSV resource -- a
# selection argument that means something subtly different in two tools is a
# reliable source of wrong calls.
BOUNDARIES_DESC = (
    "Feature collection names from search_boundaries, e.g. ['gB_v6_GHA_ADM2']. "
    "All must come from the same query about the same place."
)
DATASET_DESC = (
    "Dataset name from list_available_data or search_datasets, e.g. 'esa_landcover'."
)
EXTRACT_TYPE_DESC = (
    "Which summary to read, e.g. 'mean'. Omit for every extract type the "
    "dataset offers, which is usually more columns than you want."
)
YEARS_DESC = "Restrict to these years, e.g. [2015, 2020]. Omit for every year."
RESOURCES_DESC = (
    "Restrict to specific resource names. Prefer `years` unless you already "
    "have exact resource names from get_dataset."
)
REQUEST_ID_DESC = (
    "Read a finished export instead of live pre-processed data. Mutually "
    "exclusive with boundaries/dataset."
)
SHAPE_DESC = (
    "'wide' gives one row per feature with a column per year. 'long' gives "
    "tidy rows -- feature_id, name, series, year, value -- one per feature per "
    "column, plus first-to-last `series_change`. Use 'long' for a time series "
    "or a chart; it saves you pivoting the wide table. Table format only."
)
FORMULA_DESC = (
    "Derived column over the selected columns, e.g. "
    "'[esa_lc_2020.mean] - [esa_lc_2015.mean]'. Supports + - * / and "
    "parentheses; column names go in square brackets."
)


class StructuredOutput(BaseModel):
    """Base schema for the small catalog and request result objects."""

    model_config = ConfigDict(extra="allow")


class DataOutput(StructuredOutput):
    """The fields clients can rely on in every get_data result."""

    source: str
    format: Format
    fc_names: list[str]
    columns: list[dict[str, Any]]
    columns_omitted: int
    attribution: dict[str, Any]
    truncated: bool
    content_truncated: bool
    viz_url: str | None


class MapOutput(StructuredOutput):
    """The model-facing portion of show_map; display data lives in result _meta."""

    source: str
    title: str
    viz_url: str | None
    columns: list[dict[str, Any]]
    column: str | None
    palette: dict[str, Any]
    classification: Classification
    classes: int
    breaks: list[float]
    stats: dict[str, Any] | None
    bbox: list[float] | tuple[float, float, float, float] | None
    feature_count: int
    truncated: bool
    attribution: dict[str, Any]


GENERIC_OUTPUT_SCHEMA = StructuredOutput.model_json_schema()
DATA_OUTPUT_SCHEMA = DataOutput.model_json_schema()
MAP_OUTPUT_SCHEMA = MapOutput.model_json_schema()
