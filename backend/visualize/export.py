import json
import pathlib
import urllib.error
import urllib.request
from datetime import date

import lzstring
from django.conf import settings

TEMPLATES_DIR = pathlib.Path(__file__).parent / "notebook_templates"

_lz = lzstring.LZString()


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
            "description": f"GeoQuery — {self.request_name} ({self.request_id})",
            "public": False,
            "files": {filename: {"content": content}},
        }).encode()

        req = urllib.request.Request(
            "https://api.github.com/gists",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"GitHub Gist API error {e.code}: {body}") from e
