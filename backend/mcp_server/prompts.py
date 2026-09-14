"""Prompts: starting points a user can pick from their client's prompt menu.

Each one encodes the tool order that actually works, because the failure mode
without them is a model that guesses a boundary name, gets nothing, and gives
up -- or that submits an export to answer a question that live data would have
answered instantly.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field


def register(mcp):
    @mcp.prompt
    def explore_place(
        place: Annotated[
            str, Field(description="A country, region or district, e.g. 'Ghana'.")
        ],
    ) -> str:
        """Find and visualise what GeoQuery already has for a place."""
        return (
            f"I want to see what GeoQuery has for {place}.\n\n"
            "Work through this in order:\n"
            f"1. search_boundaries to find the boundary sets for {place}. If "
            "there are several administrative levels, say what each one "
            "covers and pick the most useful for an overview.\n"
            "2. list_available_data for that boundary. Summarise what is "
            "ready to read now, and flag anything whose coverage_fraction is "
            "well under 1.0.\n"
            "3. Pick the most interesting dataset and show_map it. If it "
            "spans several years, include them all so the map gets a year "
            "slider.\n"
            "4. Tell me what the map shows, and name the data source, its "
            "license and its citation from the attribution.\n\n"
            "Do not submit an export unless I ask for a download."
        )

    @mcp.prompt
    def summarize_request(
        request_id: Annotated[str, Field(description="A GeoQuery export id.")],
    ) -> str:
        """Describe what a finished export contains and what it shows."""
        return (
            f"Summarise GeoQuery export {request_id} for me.\n\n"
            "1. get_request_status to see whether it is finished and to get "
            "its links.\n"
            "2. If it is finished, get_data with request_id to read the "
            "values, and describe what varies across the features — the "
            "extremes, the spread, anything that looks like an artifact.\n"
            "3. show_map it so I can see the pattern.\n"
            "4. End with the download link and the full citation and license "
            "list from the attribution."
        )

    @mcp.prompt
    def cite_sources(
        request_id: Annotated[
            str, Field(description="An export id, or leave blank and name datasets.")
        ] = "",
        datasets: Annotated[
            str, Field(description="Comma-separated dataset names.")
        ] = "",
        boundaries: Annotated[
            str, Field(description="Comma-separated boundary names.")
        ] = "",
    ) -> str:
        """Produce a reference list for GeoQuery data used in a publication."""
        target = (
            f"export {request_id}"
            if request_id
            else f"datasets [{datasets}] and boundaries [{boundaries}]"
        )
        return (
            f"I am writing up work that uses GeoQuery data from {target}.\n\n"
            "Call get_citations for it and give me:\n"
            "- the full reference list, including GeoQuery itself;\n"
            "- the license of each dataset and boundary, with its link;\n"
            "- an explicit warning about anything whose citation or license "
            "is not recorded, so I know to check the source before I "
            "publish."
        )
