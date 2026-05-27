from datetime import datetime, timezone
from pathlib import Path

from datasets.models import Dataset
from analytics.models import Request

GEOQUERY_CITATION = (
    "Goodman, S., BenYishay, A., Lv, Z., &amp; Runfola, D. (2019). "
    "GeoQuery: Integrating HPC systems and public web-based geospatial data tools. "
    "<em>Computers &amp; Geosciences</em>, 122, 103–112. "
    "https://doi.org/10.1016/j.cageo.2018.10.009"
)


class DocBuilder:
    """Generate an HTML documentation file for a completed GeoQuery request.

    The output is a self-contained HTML file that renders in any browser and
    prints cleanly to PDF via the browser's print dialog (or a headless tool
    such as weasyprint if added later).
    """

    def __init__(self, request: Request, output_path, download_server: str):
        self.request = request
        self.output_path = Path(output_path).with_suffix(".html")
        self.download_server = download_server

    # ── public ───────────────────────────────────────────────────────────────

    def build_doc(self) -> str:
        html = self._render()
        with open(self.output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return "Success"

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _esc(text) -> str:
        if text is None:
            return ""
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @staticmethod
    def _fmt_dt(dt) -> str:
        if dt is None:
            return "—"
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except ValueError:
                return dt
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")

    def _kv(self, label: str, value: str) -> str:
        return f"<tr><th>{self._esc(label)}</th><td>{value}</td></tr>"

    def _table(self, rows: list[str]) -> str:
        return f'<table class="kv">{"".join(rows)}</table>'

    # ── sections ─────────────────────────────────────────────────────────────

    def _section_info(self) -> str:
        req = self.request
        dl_url = (
            f"http://{self.download_server}/data/geoquery_results"
            f"/{req.id}/{req.id}.zip"
        )
        rows = [
            self._kv("Request Name", self._esc(req.custom_name or "—")),
            self._kv("Request ID", f"<code>{req.id}</code>"),
            self._kv("Email", self._esc(req.contact or "—")),
            self._kv("Submitted", self._fmt_dt(req.submit_time)),
            self._kv("Completed", self._fmt_dt(req.complete_time)),
            self._kv("Download", f'<a href="{self._esc(dl_url)}">{self._esc(dl_url)}</a>'),
        ]
        return f"<section><h2>Request Info</h2>{self._table(rows)}</section>"

    def _section_selection(self) -> str:
        data = self.request.data or {}
        label = data.get("selection_label") or "—"
        detail = data.get("selection_detail") or ""
        feature_ids = data.get("feature_ids") or []

        rows = [self._kv("Selection", self._esc(label))]
        if detail:
            rows.append(self._kv("Detail", self._esc(detail)))
        rows.append(self._kv("Feature count", str(len(feature_ids))))
        return f"<section><h2>Geographic Selection</h2>{self._table(rows)}</section>"

    def _section_datasets(self) -> str:
        datasets = (self.request.data or {}).get("datasets") or []
        if not datasets:
            return ""

        cards = []
        for i, ds in enumerate(datasets, 1):
            name = ds.get("dataset_name") or "—"
            rows = [
                self._kv("Dataset", self._esc(name)),
                self._kv("Type", self._esc(ds.get("dataset_type") or "—")),
            ]

            extract_types = ds.get("extract_types") or []
            if extract_types:
                rows.append(self._kv("Extract types", self._esc(", ".join(extract_types))))

            resource_labels = ds.get("resource_labels") or ds.get("resources") or []
            if resource_labels:
                rows.append(self._kv("Time periods", self._esc(", ".join(str(l) for l in resource_labels))))

            # pull additional metadata from the database
            try:
                db_ds = Dataset.objects.filter(name=name).first()
                if db_ds:
                    if db_ds.description:
                        rows.append(self._kv("Description", self._esc(db_ds.description)))
                    if db_ds.source_name:
                        src = self._esc(db_ds.source_name)
                        if db_ds.source_url:
                            src = f'<a href="{self._esc(db_ds.source_url)}">{src}</a>'
                        rows.append(self._kv("Source", src))
                    if db_ds.temporal_name and db_ds.temporal_name != "Temporally Invariant":
                        rows.append(self._kv("Temporal coverage", self._esc(db_ds.temporal_name)))
                    if db_ds.date_updated:
                        rows.append(self._kv("Last updated", self._esc(str(db_ds.date_updated))))
            except Exception:
                pass

            cards.append(
                f'<div class="dataset-card">'
                f"<h3>{i}. {self._esc(name)}</h3>"
                f"{self._table(rows)}"
                f"</div>"
            )

        return (
            f"<section>"
            f"<h2>Datasets ({len(datasets)})</h2>"
            f'{"".join(cards)}'
            f"</section>"
        )

    def _section_citation(self) -> str:
        return (
            "<section>"
            "<h2>Citation</h2>"
            "<p>When publishing results generated with GeoQuery, please cite:</p>"
            f"<blockquote>{GEOQUERY_CITATION}</blockquote>"
            "<p>Individual dataset citations can be found in the source links above.</p>"
            "</section>"
        )

    # ── full document ─────────────────────────────────────────────────────────

    def _render(self) -> str:
        title = self._esc(self.request.custom_name or "Unnamed Request")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GeoQuery Documentation — {title}</title>
<style>
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    max-width: 860px;
    margin: 2rem auto;
    padding: 0 1.5rem;
    color: #1a1a1a;
    line-height: 1.5;
  }}
  h1 {{
    font-size: 1.6rem;
    border-bottom: 2px solid #003087;
    padding-bottom: .5rem;
    margin-bottom: 1.5rem;
  }}
  h2 {{ font-size: 1.1rem; color: #003087; margin: 2rem 0 .5rem; }}
  h3 {{ font-size: 1rem; margin: .75rem 0 .25rem; }}
  section {{ margin-bottom: 1.5rem; }}
  table.kv {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
  table.kv th {{
    text-align: left;
    width: 28%;
    padding: .4rem .7rem;
    background: #f3f4f6;
    font-weight: 600;
    border: 1px solid #d1d5db;
    white-space: nowrap;
    vertical-align: top;
  }}
  table.kv td {{ padding: .4rem .7rem; border: 1px solid #d1d5db; vertical-align: top; }}
  .dataset-card {{
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: .75rem 1rem;
    margin: .75rem 0;
  }}
  blockquote {{
    border-left: 3px solid #003087;
    margin: .5rem 0;
    padding: .5rem 1rem;
    background: #f8f9fa;
    font-size: .9rem;
  }}
  code {{
    font-size: .85em;
    background: #f3f4f6;
    padding: .1em .3em;
    border-radius: 3px;
    word-break: break-all;
  }}
  a {{ color: #003087; }}
  @media print {{
    body {{ max-width: none; margin: 0; padding: 1cm; font-size: 11pt; }}
    h2 {{ color: #000; }}
    a {{ color: #000; text-decoration: none; }}
    .dataset-card {{ break-inside: avoid; }}
  }}
</style>
</head>
<body>
<h1>AidData GeoQuery — Request Documentation</h1>
{self._section_info()}
{self._section_selection()}
{self._section_datasets()}
{self._section_citation()}
</body>
</html>"""
