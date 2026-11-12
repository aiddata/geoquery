"""Which docs page each boundary collection goes on.

Rules, decided 2026-11-12:

- A collection's page key is its group_name, or its own name when it has none.
- geoBoundaries group names (gb_v<N>_<iso3>) drop the release, so gb_v6_npl
  becomes gb_npl and every release of a country shares one page.
- The page's URL slug is slug(key): gb-npl, tiger, atlasofurbanexpansion2016.
- Collections whose keys give the same slug share a page.
- A page that would mix collections from different sources is an error, so
  two unrelated ingests that happen to collide can't merge silently.
"""

import re
from dataclasses import dataclass

from .text import slug

GB_GROUP = re.compile(r"^gb_v\d+_([a-z]{3})$", re.IGNORECASE)
GB_NAME = re.compile(r"^gB_([^_]+)_[A-Za-z]{3}_ADM\d+$")
CANONICAL = re.compile(r"\(([^()]+)\)\s*$")


class GroupingError(ValueError):
    pass


def page_key(fc) -> str:
    key = fc.group_name or fc.name
    match = GB_GROUP.match(key)
    return f"gb_{match.group(1).lower()}" if match else key


def is_geoboundaries(fc) -> bool:
    return bool(GB_GROUP.match(fc.group_name or ""))


def gb_version(fc):
    """The geoBoundaries build a collection came from: gB_57dcd43_NPL_ADM1 -> 57dcd43."""
    match = GB_NAME.match(fc.name)
    return match.group(1) if match else None


def level_label(fc) -> str:
    """'ADM1 (Provinces)' for geoBoundaries, 'Level 2' otherwise, '' with no level."""
    if fc.group_level is None:
        return ""
    if is_geoboundaries(fc):
        base = f"ADM{fc.group_level}"
        match = CANONICAL.search(fc.title or "")
        return f"{base} ({match.group(1)})" if match else base
    return f"Level {fc.group_level}"


def _ordered(collections):
    # Stable sorts, least significant key first: title, time period, newest
    # added, then level (missing levels last).
    out = sorted(collections, key=lambda fc: (
        fc.temporal_start.isoformat() if fc.temporal_start else "", fc.title or fc.name,
    ))
    out = sorted(out, key=lambda fc: fc.date_added, reverse=True)
    return sorted(out, key=lambda fc: (fc.group_level is None, fc.group_level or 0))


@dataclass
class Page:
    slug: str
    collections: list

    @property
    def geoboundaries(self) -> bool:
        return all(is_geoboundaries(fc) for fc in self.collections)

    @property
    def _newest(self):
        return max(self.collections, key=lambda fc: fc.date_added)

    @property
    def place(self) -> str:
        """The country for a geoBoundaries page ("Nepal"), else the group's title."""
        newest = self._newest
        if self.geoboundaries:
            return (newest.group_title or "").split(" - ")[0].strip() or page_key(newest)[3:].upper()
        return newest.group_title or newest.group_name or newest.title or newest.name

    @property
    def title(self) -> str:
        return f"{self.place} boundaries" if self.geoboundaries else self.place

    def sections(self):
        """[(heading, [collections])], in page order. A '' heading means the
        collections have no level, and each gets a section of its own."""
        out = []
        last_key = None
        for fc in self.collections:
            label = level_label(fc)
            # Releases may disagree on a geoBoundaries level's canonical name,
            # so those merge by level and take the newest collection's heading.
            if is_geoboundaries(fc) and fc.group_level is not None:
                key = ("level", fc.group_level)
            else:
                key = ("label", label)
            if label and out and last_key == key:
                out[-1][1].append(fc)
            else:
                out.append((label, [fc]))
            last_key = key
        return out


def build_pages(collections) -> list:
    by_slug = {}
    for fc in collections:
        by_slug.setdefault(slug(page_key(fc)), []).append(fc)
    pages = []
    for page_slug, members in by_slug.items():
        names = sorted(fc.name for fc in members)
        if not page_slug:
            raise GroupingError(f"collections {names} have a group name with no usable characters")
        sources = sorted({fc.source_name or "" for fc in members})
        if len(sources) > 1:
            raise GroupingError(
                f"boundaries/{page_slug}/ would mix sources {sources}: {names}. "
                "Give one of these ingests a different group_name."
            )
        pages.append(Page(page_slug, _ordered(members)))
    return sorted(pages, key=lambda page: (page.title.lower(), page.slug))
