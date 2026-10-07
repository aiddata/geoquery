#!/usr/bin/env python3
"""Load requests.parquet into pandas as a flat, analysis-ready frame.

Running it prints an overview; importing it gives you `load_flat()` and the
pieces it is built from.

The simple nesting is flattened into real columns:
  boundary (struct)            -> boundary_title, boundary_group, ...
  stage    (list[{name,time}]) -> t_submitted, t_prepared, t_processed,
                                  t_completed (UTC) + duration_s
The irregular nesting is left as JSON strings, since its shape varies per
request (release filter keys differ by dataset, raster datasets carry their own
file lists):
  info, release_data, raster_data

Alongside the JSON, a few scalar summaries make the common questions cheap to
ask without parsing it back: n_release, n_raster, n_raster_files,
release_datasets, raster_datasets.

Usage: read_requests.py [PARQUET]
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    HERE = Path(__file__).resolve().parent
    SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "requests.parquet"
except Exception as e:
    HERE = Path(".")
    SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "requests.parquet"

# Every record carries all four, in this order.
STAGES = ("submitted", "prepared", "processed", "completed")

# Flattened out into their own columns, so they are dropped from the flat frame.
FLATTENED = ["boundary", "stage"]
# Kept, but serialized to JSON text.
AS_JSON = ["info", "release_data", "raster_data"]


def load(path=SRC, columns=None):
    """Read the Parquet file. Pass `columns` to skip decoding the big nested
    ones -- raster_data alone is most of the file."""
    return pd.read_parquet(path, columns=columns)


def plain(obj):
    """Make Arrow-derived objects JSON-serializable.

    pyarrow hands back ndarrays for lists, and a Parquet map arrives as a list
    of (key, value) pairs -- which round-trips much more usefully as an object.
    """
    if isinstance(obj, np.ndarray):
        obj = obj.tolist()
    if isinstance(obj, (list, tuple)):
        items = list(obj)
        if items and all(isinstance(i, tuple) and len(i) == 2
                         and isinstance(i[0], str) for i in items):
            return {k: plain(v) for k, v in items}
        return [plain(i) for i in items]
    if isinstance(obj, dict):
        return {k: plain(v) for k, v in obj.items()}
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def to_json(series):
    """Serialize a nested column to compact JSON text."""
    return series.map(lambda v: json.dumps(plain(v), separators=(",", ":")))


def with_boundary(df):
    """Explode the boundary struct into boundary_* columns."""
    b = pd.json_normalize(df["boundary"]).set_index(df.index).add_prefix("boundary_")
    return df.join(b)


def with_stage_times(df):
    """One UTC timestamp column per stage, plus end-to-end duration.

    Stage times are unix seconds. NOTE: in ~9.7k records the prepared/processed
    times precede submitted, so duration_s goes negative; that is in the source
    data, not an artifact of the conversion. Filter on duration_s >= 0 if you
    are measuring throughput.
    """
    times = pd.DataFrame(
        [{s["name"]: s["time"] for s in row} for row in df["stage"]],
        index=df.index,
    )
    out = df.copy()
    for s in STAGES:
        if s in times:
            out[f"t_{s}"] = pd.to_datetime(times[s], unit="s", utc=True)
    if {"t_submitted", "t_completed"} <= set(out.columns):
        out["duration_s"] = (out["t_completed"] - out["t_submitted"]).dt.total_seconds()
    return out


def with_summaries(df):
    """Scalar roll-ups of the JSON columns, so common filters stay cheap."""
    out = df.copy()
    out["n_release"] = df["release_data"].str.len()
    out["n_raster"] = df["raster_data"].str.len()
    out["n_raster_files"] = [sum(len(d["files"]) if d["files"] is not None else 0
                                 for d in row) for row in df["raster_data"]]
    # Pipe-delimited rather than JSON: these are what you group and filter on.
    # A couple of documents hold an empty dataset entry, hence the None guard.
    out["release_datasets"] = ["|".join(r["dataset"] for r in row if r["dataset"])
                               for row in df["release_data"]]
    out["raster_datasets"] = ["|".join(d["name"] for d in row if d["name"])
                              for row in df["raster_data"]]
    return out


def load_flat(path=SRC):
    """The analysis-ready frame: flat scalars + JSON text for the rest."""
    df = load(path)
    df = with_summaries(with_stage_times(with_boundary(df)))
    for c in AS_JSON:
        df[c] = to_json(df[c])
    return df.drop(columns=FLATTENED)


# --- optional long-form views, if you'd rather join than parse JSON ---------

def releases(df):
    """One row per (request, release dataset). Takes the raw frame."""
    s = df["release_data"].explode().dropna()
    return pd.DataFrame(
        [{"request_id": df.at[i, "request_id"], "dataset": r["dataset"],
          "custom_name": r["custom_name"], "hash": r["hash"],
          "filters": plain(r["filters"])}
         for i, r in s.items()])


def rasters(df):
    """One row per (request, raster dataset). Takes the raw frame."""
    s = df["raster_data"].explode().dropna()
    return pd.DataFrame(
        [{"request_id": df.at[i, "request_id"], "name": d["name"],
          "title": d["title"], "temporal_type": d["temporal_type"],
          "extract_types": list(d["extract_types"]), "n_files": len(d["files"])}
         for i, d in s.items()])


def main():
    df = load_flat()
    print(f"loaded {SRC.name}: {len(df):,} rows x {df.shape[1]} cols, "
          f"{df.memory_usage(deep=True).sum() / 1e6:,.0f} MB in memory\n")

    print("--- columns ---")
    print(df.dtypes.to_string(), "\n")

    print("--- submitted range ---")
    print(f"  {df['t_submitted'].min()}  ->  {df['t_submitted'].max()}\n")

    print("--- requests per year ---")
    print(df["t_submitted"].dt.year.value_counts().sort_index().to_string(), "\n")

    print("--- status ---")
    print(df["status"].value_counts().sort_index().to_string(), "\n")

    neg = (df["duration_s"] < 0).sum()
    print(f"--- duration_s (excluding {neg:,} negative source rows) ---")
    print(df.loc[df["duration_s"] >= 0, "duration_s"].describe().to_string(), "\n")

    print("--- top 10 requesters ---")
    print(df["email"].value_counts().head(10).to_string(), "\n")

    print("--- top 10 boundaries ---")
    print(df["boundary_name"].value_counts().head(10).to_string(), "\n")

    print("--- request size ---")
    print(df[["n_release", "n_raster", "n_raster_files"]].describe().to_string(), "\n")

    print("--- sample JSON column (raster_data, truncated) ---")
    print(" ", df["raster_data"].iloc[0][:300], "...\n")

    print("--- round-trip check ---")
    one = json.loads(df["raster_data"].iloc[0])
    print(f"  parsed {len(one)} raster dataset(s); "
          f"first = {one[0]['name']} with {len(one[0]['files'])} file(s)")

    return df

if __name__ == "__main__":
    df = main()
