"""show_map: the choropleth, plus the resource that renders it.

The tool and its UI resource are registered together because they are one
thing: the tool's ``AppConfig`` names the resource, and the resource is
useless without the tool's payload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastmcp.apps import AppConfig, ResourceCSP, UI_MIME_TYPE
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_server.apps.map import (
    APP_CONNECT_DOMAINS,
    APP_RESOURCE_DOMAINS,
    MAP_APP_URI,
    build_map_payload,
)
from mcp_server.data.palette import PALETTES
from mcp_server.schemas import (
    BOUNDARIES_DESC,
    Classification,
    DATASET_DESC,
    EXTRACT_TYPE_DESC,
    FORMULA_DESC,
    MAP_OUTPUT_SCHEMA,
    REQUEST_ID_DESC,
    RESOURCES_DESC,
    YEARS_DESC,
)

from .common import fmt_count, fmt_number, result, tool_body

_APP_HTML = Path(__file__).resolve().parent.parent / "apps" / "static" / "map-v1.html"


def register(mcp, user_dep):
    @mcp.resource(
        MAP_APP_URI,
        name="GeoQuery map",
        description="Interactive choropleth for a GeoQuery data selection.",
        mime_type=UI_MIME_TYPE,
        app=AppConfig(
            csp=ResourceCSP(
                resourceDomains=APP_RESOURCE_DOMAINS,
                connectDomains=APP_CONNECT_DOMAINS,
            ),
            prefersBorder=True,
        ),
    )
    def map_app() -> str:
        """The map app's HTML. Read from disk on each call so editing it in
        development takes effect on reload, exactly like the Django views the
        rest of this project serves."""
        return _APP_HTML.read_text(encoding="utf-8")

    @mcp.tool(
        name="show_map",
        output_schema=MAP_OUTPUT_SCHEMA,
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
        app=AppConfig(resourceUri=MAP_APP_URI),
        meta={
            "openai/outputTemplate": MAP_APP_URI,
            "openai/toolInvocation/invoking": "Building map…",
            "openai/toolInvocation/invoked": "Map ready",
        },
    )
    @tool_body
    def show_map(
        boundaries: Annotated[
            list[str] | None, Field(description=BOUNDARIES_DESC)
        ] = None,
        dataset: Annotated[str | None, Field(description=DATASET_DESC)] = None,
        extract_type: Annotated[
            str | None, Field(description=EXTRACT_TYPE_DESC)
        ] = None,
        years: Annotated[list[int] | None, Field(description=YEARS_DESC)] = None,
        resources: Annotated[
            list[str] | None, Field(description=RESOURCES_DESC)
        ] = None,
        request_id: Annotated[str | None, Field(description=REQUEST_ID_DESC)] = None,
        column: Annotated[
            str | None,
            Field(
                description=(
                    "Which column to colour by. Omit for the first numeric one; "
                    "the user can switch columns in the map itself."
                )
            ),
        ] = None,
        formula: Annotated[str | None, Field(description=FORMULA_DESC)] = None,
        palette: Annotated[
            str,
            Field(description="Colour scheme: " + ", ".join(PALETTES) + "."),
        ] = "YlOrRd",
        classification: Annotated[
            Classification,
            Field(
                description=(
                    "'quantile' puts equal numbers of features in each class; "
                    "'equal' uses equal value intervals."
                )
            ),
        ] = "quantile",
        classes: Annotated[
            int, Field(description="Number of colour classes.", ge=2, le=9)
        ] = 5,
        include_geometry: Annotated[
            bool,
            Field(
                description=(
                    "Draw the boundaries. Set false for a summary with no map."
                )
            ),
        ] = True,
        user=user_dep,
    ):
        """Show a data selection as an interactive choropleth in the chat.

        Pass several years at once and the map gets a year slider; the user
        can also switch column, palette and classification inside it without
        another tool call, so ask for the whole selection rather than one map
        per year.

        If the client cannot render the map, the text summary and `viz_url`
        still describe the selection. Results include `attribution`; relay
        the sources, licenses and citations to the user.
        """
        payload = build_map_payload(
            user,
            boundaries=boundaries,
            dataset=dataset,
            extract_type=extract_type,
            years=years,
            resources=resources,
            request_id=request_id,
            column=column,
            formula=formula,
            palette=palette,
            classification=classification,
            classes=classes,
            include_geometry=include_geometry,
        )

        stats = payload["stats"]
        lines = [
            f"{payload['title']} — {fmt_count(payload['feature_count'], 'feature')}, "
            f"coloured by {payload['column'] or '(no numeric column)'}.",
        ]
        if stats:
            lines.append(
                f"min {fmt_number(stats['min'])}, mean {fmt_number(stats['mean'])}, "
                f"max {fmt_number(stats['max'])} over {stats['n']:,} features "
                "with data."
            )
        if payload["truncated"]:
            lines.append(
                "Too many features to draw inline; the summary above still "
                "describes the whole selection."
            )
        if payload["viz_url"]:
            lines.append(f"Open in GeoQuery: {payload['viz_url']}")
        model_payload = {
            key: payload[key]
            for key in (
                "source",
                "title",
                "viz_url",
                "columns",
                "column",
                "palette",
                "classification",
                "classes",
                "breaks",
                "stats",
                "bbox",
                "feature_count",
                "truncated",
                "attribution",
            )
        }
        return result(lines, model_payload, meta={"geoquery/map": payload})
