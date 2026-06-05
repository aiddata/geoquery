from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from django.conf import settings
from django.contrib.gis.db.models import Extent

from features.models import Feature, FeatMap, FeatureCollection


class VizBuilder:
    """Generate a self-contained interactive HTML visualization for a completed request.

    Uses MapLibre GL JS + the existing MVT tile endpoint to render a choropleth
    map of the merged extract results.  All interactivity (column selection,
    color scheme, classification method) is client-side JavaScript.
    """

    def __init__(self, request, merged_df: pd.DataFrame, output_path, base_url: str | None = None):
        self.request = request
        self.df = merged_df
        self.output_path = Path(output_path).with_suffix(".html")
        self.base_url = (
            base_url or getattr(settings, "DOWNLOAD_BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        self.protomaps_api_key = getattr(settings, "PROTOMAPS_API_KEY", "")

    def build_viz(self) -> str:
        try:
            data = self._build_data()
            html = self._render(data)
            with open(self.output_path, "w", encoding="utf-8") as f:
                f.write(html)
            return "Success"
        except Exception as e:
            return f"Error: {e}"

    # ── private ───────────────────────────────────────────────────────────────

    def _build_data(self) -> dict:
        df = self.df
        meta_cols = {"feature_collection", "geom_id"}
        data_cols = [c for c in df.columns if c not in meta_cols and not c.startswith("boundary.")]

        fc_names: list[str] = df["feature_collection"].dropna().unique().tolist()
        geom_ids: list[int] = df["geom_id"].dropna().astype(int).tolist()

        # Look up display names (geom_id, fc_name) → feature name
        fc_id_map = {
            fc.name: fc.id
            for fc in FeatureCollection.objects.filter(name__in=fc_names)
        }
        fm_lookup: dict[tuple[int, str], str] = {}
        for fm in (
            FeatMap.objects.filter(
                geom_id__in=geom_ids, fc_id__in=list(fc_id_map.values())
            ).select_related("fc")
        ):
            fm_lookup[(int(fm.geom_id), fm.fc.name)] = fm.name or f"Feature {fm.geom_id}"

        # Build per-feature records keyed by geom_id string
        features: dict[str, dict] = {}
        for _, row in df.iterrows():
            geom_id = int(row["geom_id"])
            fc = row["feature_collection"]
            record: dict = {
                "name": fm_lookup.get((geom_id, fc)) or f"Feature {geom_id}",
                "fc": fc,
            }
            for col in data_cols:
                val = row[col]
                if pd.notna(val):
                    record[col] = float(val) if isinstance(val, (int, float)) else str(val)
                else:
                    record[col] = None
            features[str(geom_id)] = record

        # Group columns by resource name (part before first '.')
        col_groups: dict[str, list[str]] = {}
        for col in data_cols:
            group = col.split(".", 1)[0]
            col_groups.setdefault(group, []).append(col)

        # Bounding box from Feature geometries for auto-zoom
        bbox = None
        extent = Feature.objects.filter(id__in=geom_ids).aggregate(
            extent=Extent("shape")
        )["extent"]
        if extent:
            bbox = list(extent)  # [xmin, ymin, xmax, ymax]

        req_data = self.request.data or {}
        return {
            "request_id": str(self.request.id),
            "request_name": self.request.custom_name or str(self.request.id)[:8],
            "selection_label": req_data.get("selection_label") or "",
            "fc_names": fc_names,
            "columns": data_cols,
            "col_groups": col_groups,
            "features": features,
            "bbox": bbox,
            "tile_base_url": self.base_url,
            "protomaps_api_key": self.protomaps_api_key,
        }

    @staticmethod
    def _render(data: dict) -> str:
        from .template import TEMPLATE
        return TEMPLATE.replace("__GQ_DATA__", json.dumps(data, default=str))
