import json
import pathlib
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

import lzstring
from django.conf import settings

TEMPLATES_DIR = pathlib.Path(__file__).parent / "notebook_templates"

# All gists we create carry this description prefix so the cleanup sweep can
# identify them without per-request bookkeeping.
GIST_DESCRIPTION_PREFIX = "GeoQuery —"

_lz = lzstring.LZString()


def _gist_auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class GistExporter:
    _COLAB_BASE = "https://colab.research.google.com/gist"
    _MOLAB_BASE = "https://molab.marimo.io/new/wasm"

    def __init__(self, request_id: str, request_name: str, download_url: str):
        self.request_id = request_id
        self.request_name = request_name or f"Request {request_id[:8]}"
        self.download_url = download_url

    def export(self, fmt: str) -> str:
        if fmt == "colab":
            content = self._render("colab_template.ipynb")
            return self._colab_url(content)
        elif fmt == "marimo":
            content = self._render("marimo_template.py")
            return self._molab_url(content)
        else:
            raise ValueError(f"Unknown export format: {fmt!r}")

    def _colab_url(self, content: str) -> str:
        token = getattr(settings, "GITHUB_GIST_TOKEN", "")
        if not token:
            raise RuntimeError("GITHUB_GIST_TOKEN is not configured")
        gist = self._post_gist(token, "geoquery_analysis.ipynb", content)
        owner = gist["owner"]["login"]
        gist_id = gist["id"]
        return f"{self._COLAB_BASE}/{owner}/{gist_id}"

    def _molab_url(self, content: str) -> str:
        compressed = _lz.compressToEncodedURIComponent(content)
        return f"{self._MOLAB_BASE}/#code/{compressed}"

    # ── Template rendering ───────────────────────────────────────────────────

    def _render(self, template_filename: str) -> str:
        template = (TEMPLATES_DIR / template_filename).read_text()
        return (
            template
            .replace("{{REQUEST_ID}}", self.request_id)
            .replace("{{REQUEST_NAME}}", self.request_name)
            .replace("{{DOWNLOAD_URL}}", self.download_url)
            .replace("{{DATE}}", date.today().isoformat())
        )

    # ── GitHub Gist API ──────────────────────────────────────────────────────

    def _post_gist(self, token: str, filename: str, content: str) -> dict:
        payload = json.dumps({
            "description": f"{GIST_DESCRIPTION_PREFIX} {self.request_name} ({self.request_id})",
            "public": False,
            "files": {filename: {"content": content}},
        }).encode()

        req = urllib.request.Request(
            "https://api.github.com/gists",
            data=payload,
            headers={**_gist_auth_headers(token), "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"GitHub Gist API error {e.code}: {body}") from e

    # ── Cleanup sweep ────────────────────────────────────────────────────────

    @classmethod
    def sweep_old_gists(cls, max_age_seconds: int) -> dict:
        """Delete GeoQuery-created gists older than ``max_age_seconds``.

        Colab loads a notebook from its gist server-side after the user's
        browser is redirected, so gists can't be deleted immediately. This
        best-effort sweep removes them once the load-and-save window has
        passed. Individual delete failures are counted, not raised, so one bad
        gist doesn't abort the run.
        """
        token = getattr(settings, "GITHUB_GIST_TOKEN", "")
        if not token:
            raise RuntimeError("GITHUB_GIST_TOKEN is not configured")

        cutoff = datetime.now(timezone.utc).timestamp() - max_age_seconds
        deleted = failed = 0
        for gist in cls._list_gists(token):
            description = gist.get("description") or ""
            if not description.startswith(GIST_DESCRIPTION_PREFIX):
                continue
            created = gist.get("created_at")
            if not created:
                continue
            created_ts = (
                datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
            if created_ts > cutoff:
                continue
            try:
                cls._delete_gist(token, gist["id"])
                deleted += 1
            except urllib.error.URLError:
                failed += 1
        return {"deleted": deleted, "failed": failed}

    @staticmethod
    def _list_gists(token: str):
        """Yield the authenticated user's gists, paging through all results."""
        page = 1
        while True:
            req = urllib.request.Request(
                f"https://api.github.com/gists?per_page=100&page={page}",
                headers=_gist_auth_headers(token),
                method="GET",
            )
            with urllib.request.urlopen(req) as resp:
                batch = json.loads(resp.read())
            if not batch:
                break
            yield from batch
            if len(batch) < 100:
                break
            page += 1

    @staticmethod
    def _delete_gist(token: str, gist_id: str) -> None:
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gist_id}",
            headers=_gist_auth_headers(token),
            method="DELETE",
        )
        with urllib.request.urlopen(req) as resp:
            resp.read()
