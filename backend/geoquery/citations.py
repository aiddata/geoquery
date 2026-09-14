"""Citation primitives shared across apps.

GeoQuery redistributes other people's open data, so the source's citation and
licence have to travel with the data through every surface: the REST API, the
STAC catalog, the generated documentation site, the results zip, and the MCP
server. The pieces that every one of those needs -- how to cite GeoQuery
itself, and how to pull a DOI out of a free-text citation string -- live here
so no surface has to import another app's internals to get them.

``Dataset.citation`` / ``FeatureCollection.citation`` are free-text, so a DOI
can only be recovered by pattern match. Structured citation fields are a
follow-up; until then this is the seam.
"""

from __future__ import annotations

import re

GEOQUERY_DOI = "10.1016/j.cageo.2018.10.009"
GEOQUERY_URL = "https://www.geoquery.org"

# Plain-text twin of analytics.tasks.documentation.GEOQUERY_CITATION, which is
# HTML-escaped for the results documentation page. Everything that emits JSON
# or Markdown wants this one.
GEOQUERY_CITATION = (
    "Goodman, S., BenYishay, A., Lv, Z., & Runfola, D. (2019). "
    "GeoQuery: Integrating HPC systems and public web-based geospatial data tools. "
    "Computers & Geosciences, 122, 103–112. "
    f"https://doi.org/{GEOQUERY_DOI}"
)

# DOIs are "10." + registrant code + "/" + an opaque suffix. The suffix may
# contain almost anything, so the match is ended on whitespace or on trailing
# punctuation that is far more likely to be sentence punctuation than part of
# the identifier.
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:)]}"


def doi_from_citation(citation: str | None) -> str | None:
    """Return the first DOI in a free-text citation, or ``None``.

    Accepts a bare DOI, a ``doi:`` prefix, or a resolver URL -- all three
    contain the identifier itself, which is what is returned (never the URL).
    """
    if not citation:
        return None
    match = _DOI_RE.search(citation)
    if not match:
        return None
    return match.group(1).rstrip(_TRAILING_PUNCTUATION)


def doi_url(doi: str | None) -> str | None:
    """Resolver URL for a DOI, or ``None`` when there is no DOI."""
    return f"https://doi.org/{doi}" if doi else None
