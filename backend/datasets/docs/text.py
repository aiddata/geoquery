"""Text helpers shared by the data documentation pages."""

import json
import re

# Search engines show roughly this many characters of a meta description.
DESCRIPTION_LIMIT = 160


def slug(value) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def one_line(text) -> str:
    return " ".join(str(text or "").split())


def cell(text) -> str:
    """A Markdown table cell: one line, pipes escaped, a dash when empty."""
    return one_line(text).replace("|", "\\|") or "—"


def absolute_url(url) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


def link(label, url) -> str:
    url = absolute_url(url)
    return f"[{label}]({url})" if url else label


def license_text(obj) -> str:
    """Always says something. GeoQuery redistributes other people's data under
    their terms, so "not recorded, check the source" is information the reader
    needs, not a row to drop."""
    if not obj.license:
        return "Not recorded — see the source link"
    return link(cell(obj.license), obj.license_url)


def year_range(start, end) -> str:
    """'2000–2020', '2015' when both fall in one year, or '—' with neither."""
    first, last = (f"{d:%Y}" if d else "" for d in (start, end))
    if first and last and first != last:
        return f"{first}–{last}"
    return first or last or "—"


def date_range(start, end) -> str:
    first, last = (f"{d:%Y-%m-%d}" if d else "—" for d in (start, end))
    return f"{first} – {last}"


def join_words(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def meta_description(lead, detail=None, suffix: str = "") -> str:
    """A page's meta description, at most DESCRIPTION_LIMIT characters: ``lead``
    then ``suffix``, with as much of ``detail`` between them as fits whole --
    all of it, else its first sentence, else none. Only an overlong ``lead`` is
    ever cut mid-text, at a word."""
    lead, detail = one_line(lead), one_line(detail)
    room = DESCRIPTION_LIMIT - len(suffix)
    if len(lead) > room:
        lead = lead[: room - 1].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    first_sentence = re.split(r"(?<=[a-z0-9)][.!?])\s+(?=[A-Z])", detail, maxsplit=1)[0]
    for candidate in (detail, first_sentence):
        if candidate and len(lead) + 1 + len(candidate) <= room:
            lead = f"{lead} {candidate}"
            break
    return (lead + suffix).strip()


def front_matter(description: str) -> str:
    """YAML front matter setting the page's meta description. JSON string
    syntax is valid YAML, and quoting keeps colons and hashes literal."""
    return f"---\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n"
