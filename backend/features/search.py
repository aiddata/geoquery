"""Finding features by name across feature collections.

Collection search (``FeatureCollection.search_active_public`` and friends)
matches titles like "geoBoundaries v6 - Ghana ADM2", so it finds countries
but never the districts inside them. This searches the districts themselves.

Matching is case- and accent-insensitive ("sao tome" finds "São Tomé") and
runs on ``idx_feat_map_name_trgm``. Substring matches win outright; fuzzy
trigram matches are only offered when there are none, because they are
always noisy ("Kumasi" also fuzzily matches "Kumasgam") and only worth
showing when the caller has misspelled something.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Case, IntegerField, Value, When

from .models import FeatMap, NormalizedName

# Below three characters a trigram index cannot narrow anything, and the
# matches would be meaningless anyway.
MIN_QUERY_LENGTH = 3


@dataclass(frozen=True)
class FeatureNameMatches:
    matches: list[FeatMap]
    truncated: bool
    # True when nothing contained the query and these are closest spellings.
    approximate: bool


def search_feature_names(collections, query: str, limit: int = 20) -> FeatureNameMatches:
    """Features whose name matches ``query``, within ``collections``.

    ``collections`` is a FeatureCollection queryset that has already had
    access control applied -- this does none of its own. Each returned
    FeatMap has ``fc`` loaded.
    """
    query = (query or "").strip()
    if len(query) < MIN_QUERY_LENGTH:
        return FeatureNameMatches([], truncated=False, approximate=False)

    # Normalised in SQL, not Python, so both sides go through exactly the
    # same unaccent rules as the index. It is a constant expression, so the
    # planner folds it before choosing the index.
    needle = NormalizedName(Value(query))
    base = FeatMap.objects.filter(fc__in=collections).annotate(
        normalized=NormalizedName("name")
    )

    rows = _ranked(
        base.filter(normalized__contains=needle).annotate(
            closeness=Case(
                When(normalized=needle, then=Value(0)),
                When(normalized__startswith=needle, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ),
        limit,
    )
    approximate = False
    if not rows:
        rows = _ranked(
            base.filter(normalized__trigram_word_similar=needle).annotate(
                closeness=-TrigramWordSimilarity(needle, "normalized")
            ),
            limit,
        )
        approximate = bool(rows)

    return FeatureNameMatches(
        rows[:limit], truncated=len(rows) > limit, approximate=approximate
    )


def _ranked(qs, limit: int) -> list[FeatMap]:
    # One extra row tells us whether there were more, without a count().
    return list(
        qs.select_related("fc").order_by(
            "closeness", "fc__group_level", "name", "fc__name"
        )[: limit + 1]
    )
