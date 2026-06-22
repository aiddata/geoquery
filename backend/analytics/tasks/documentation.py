import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

from datasets.models import Dataset
from analytics.models import ProcessingOption
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
        frontend_base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
        if frontend_base:
            viz_url = f"{frontend_base}/viz/{req.id}"
            rows.append(
                self._kv("Visualization", f'<a href="{self._esc(viz_url)}">{self._esc(viz_url)}</a>')
            )
        return f"<section><h2>Request Info</h2>{self._table(rows)}</section>"

    @staticmethod
    def _fmt_kwargs(kwargs: dict) -> str:
        """Convert a kwargs dict to a human-readable filter description."""
        parts = []
        for key, val in kwargs.items():
            if isinstance(val, dict):
                if val.get("type") == "range":
                    parts.append(f"{key}: {val.get('start')}–{val.get('end')}")
                elif val.get("type") == "categorical" and isinstance(val.get("selected"), list):
                    parts.append(f"{key}: {', '.join(str(s) for s in val['selected'])}")
                else:
                    parts.append(f"{key}: {json.dumps(val)}")
            else:
                parts.append(f"{key}: {val}")
        return "; ".join(parts)

    @staticmethod
    def _kwargs_hash(kwargs: dict) -> str:
        """Return the 8-char MD5 hash used to suffix output column names."""
        return hashlib.md5(
            json.dumps(kwargs, sort_keys=True).encode()
        ).hexdigest()[:8]

    @staticmethod
    def _fmt_operation(op: dict) -> str:
        t = op.get("type", "")
        p = op.get("params") or {}
        if t == "buffer":
            return f"Buffer — {p.get('distance', '')} {p.get('units', 'km')}"
        if t == "simplify":
            return f"Simplify — tolerance {p.get('tolerance', '')}°"
        if t == "union":
            return "Union features"
        return t

    def _section_selection(self) -> str:
        data = self.request.data or {}
        is_custom = data.get("is_custom_boundary", False)
        label = data.get("selection_label") or "—"
        detail = data.get("selection_detail") or ""
        feature_ids = data.get("feature_ids") or []

        heading = "Custom Boundary" if is_custom else "Geographic Selection"
        rows = [self._kv("Boundary" if is_custom else "Selection", self._esc(label))]
        if detail:
            rows.append(self._kv("Detail", self._esc(detail)))
        rows.append(self._kv("Feature count", str(len(feature_ids))))

        if is_custom and data.get("boundary_file_name"):
            rows.append(self._kv("Source file", self._esc(data["boundary_file_name"])))

        ops = data.get("boundary_operations") or []
        if ops:
            ops_html = "<ol style='margin:0;padding-left:1.2em;'>" + "".join(
                f"<li>{self._esc(self._fmt_operation(op))}</li>" for op in ops
            ) + "</ol>"
            rows.append(self._kv(f"Operations ({len(ops)})", ops_html))

        return f"<section><h2>{heading}</h2>{self._table(rows)}</section>"

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

            resource_labels = ds.get("resource_labels") or ds.get("resources") or []
            if resource_labels:
                rows.append(self._kv("Time periods", self._esc(", ".join(str(l) for l in resource_labels))))

            # pull additional metadata from the database
            try:
                db_ds = Dataset.objects.filter(name=name).first()
                if db_ds:
                    if db_ds.description:
                        rows.append(self._kv("Description", self._esc(db_ds.description)))
                    if db_ds.variable_description:
                        rows.append(self._kv("Variable", self._esc(db_ds.variable_description)))
                    if db_ds.details:
                        rows.append(self._kv("Details", self._esc(db_ds.details)))
                    if db_ds.source_name:
                        src = self._esc(db_ds.source_name)
                        if db_ds.source_url:
                            src = f'<a href="{self._esc(db_ds.source_url)}">{src}</a>'
                        rows.append(self._kv("Source", src))
                    if db_ds.temporal_name and db_ds.temporal_name != "Temporally Invariant":
                        rows.append(self._kv("Temporal coverage", self._esc(db_ds.temporal_name)))
                    if db_ds.citation:
                        rows.append(self._kv("Dataset citation", self._esc(db_ds.citation)))
                    if db_ds.date_updated:
                        rows.append(self._kv("Last updated", self._esc(str(db_ds.date_updated))))
            except Exception:
                pass

            extract_types = ds.get("extract_types") or []
            if extract_types:
                try:
                    po_desc = {
                        p["short_name"]: p["description"] or ""
                        for p in ProcessingOption.objects.filter(
                            dataset__name=name, short_name__in=extract_types
                        ).values("short_name", "description")
                    }
                except Exception:
                    po_desc = {}
                et_items = "".join(
                    f"<li><strong>{self._esc(et)}</strong>"
                    + (f" — {self._esc(po_desc[et])}" if po_desc.get(et) else "")
                    + "</li>"
                    for et in extract_types
                )
                rows.append(self._kv(
                    f"Extract types ({len(extract_types)})",
                    f"<ul style='margin:0;padding-left:1.2em;'>{et_items}</ul>",
                ))

            kwargs = ds.get("kwargs")
            if kwargs:
                kwargs_hash = self._kwargs_hash(kwargs)
                filter_desc = self._esc(self._fmt_kwargs(kwargs))
                rows.append(self._kv(
                    "Filters applied",
                    f"{filter_desc} <code style='font-size:.8em;color:#666;'>({kwargs_hash})</code>",
                ))
                rows.append(self._kv(
                    "Output column suffix",
                    f"<code>_{kwargs_hash}</code> — appended to each extract-type column name "
                    f"to distinguish this filter combination",
                ))

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
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }}
  .gh-link {{
    flex-shrink: 0;
    color: #57606a;
    opacity: 0.75;
    transition: opacity .15s;
  }}
  .gh-link:hover {{ opacity: 1; color: #24292f; }}
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
<h1>
  <span>AidData GeoQuery — Request Documentation</span>
  <a href="https://github.com/aiddata/geoquery-update" class="gh-link" target="_blank" rel="noopener noreferrer" title="GeoQuery on GitHub" aria-label="GeoQuery on GitHub">
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/>
    </svg>
  </a>
</h1>
{self._section_info()}
{self._section_selection()}
{self._section_datasets()}
{self._section_citation()}
</body>
</html>"""
