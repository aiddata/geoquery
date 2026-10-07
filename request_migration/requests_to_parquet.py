#!/usr/bin/env python3
"""Convert the MongoDB requests.json export to Parquet.

The source is a single-line JSON array (~520 MB) of GeoQuery request documents
in MongoDB extended JSON. It was exported from the DB with the below command and zipped
for transfer. (Raw export is ~520MB, zipped is ~36MB. Resulting parquet file is ~8MB.)
`mongoexport --db=asdf --collection=det --jsonArray --out=requests.json`

It is streamed with ijson rather than json.load so
that memory stays flat and so that a truncated tail -- an earlier export was
cut off mid-record -- still yields every complete record before the break.

Mongo wrappers ($oid, $numberLong) are unwrapped, Angular's $$hashKey is
dropped, and the nested request structure is preserved as real Parquet
structs/lists/maps rather than JSON strings, so the output stays queryable.

Usage: requests_to_parquet.py [SRC] [DST]
"""

import sys
from pathlib import Path

import ijson
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
SRC = sys.argv[1] if len(sys.argv) > 1 else HERE / "requests.json"
DST = sys.argv[2] if len(sys.argv) > 2 else HERE / "requests.parquet"
BATCH = 2000

# Angular's $$hashKey leaks into these documents; it carries no information.
JUNK = {"$$hashKey"}

BOUNDARY = pa.struct([(k, pa.string()) for k in
                      ("title", "group", "name", "description", "path")])
STAGE = pa.list_(pa.struct([("name", pa.string()), ("time", pa.int64())]))
FILTERS = pa.map_(pa.string(), pa.list_(pa.string()))
RELEASE = pa.list_(pa.struct([
    ("dataset", pa.string()),
    ("custom_name", pa.string()),
    ("hash", pa.string()),
    ("filters", FILTERS),
]))
# A handful of files carry byte-range metadata alongside the usual fields.
RASTER_FILE = pa.struct([("name", pa.string()), ("path", pa.string()),
                         ("display", pa.string()), ("bytes", pa.int64()),
                         ("start", pa.int64()), ("end", pa.int64())])
RASTER = pa.list_(pa.struct([
    ("name", pa.string()),
    ("title", pa.string()),
    ("base", pa.string()),
    ("type", pa.string()),
    ("custom_name", pa.string()),
    ("temporal_type", pa.string()),
    ("extract_types", pa.list_(pa.string())),
    ("files", pa.list_(RASTER_FILE)),
]))

SCHEMA = pa.schema([
    ("request_id", pa.string()),
    ("email", pa.string()),
    ("custom_name", pa.string()),
    ("status", pa.int64()),
    ("priority", pa.int64()),
    ("contact_flag", pa.int64()),
    ("comments_requested", pa.int64()),
    ("submit_time", pa.int64()),
    ("attempts", pa.int64()),
    ("info", pa.list_(pa.string())),
    ("boundary", BOUNDARY),
    ("stage", STAGE),
    ("release_data", RELEASE),
    ("raster_data", RASTER),
])


def as_int(v):
    """Unwrap Mongo {$numberLong: "1"} / tolerate floats and strings."""
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("$numberLong", v.get("$numberInt"))
    if v is None or v == "":
        return None
    return int(float(v))


def as_str_list(v):
    """Scalars become one-element lists; empty strings become []."""
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple)):
        return [x if isinstance(x, str) else str(x) for x in v]
    return [v if isinstance(v, str) else str(v)]


def pick(d, keys):
    return {k: d.get(k) for k in keys}


def convert(rec):
    oid = rec.get("_id")
    return {
        "request_id": oid.get("$oid") if isinstance(oid, dict) else oid,
        "email": rec.get("email"),
        "custom_name": rec.get("custom_name"),
        "status": as_int(rec.get("status")),
        "priority": as_int(rec.get("priority")),
        "contact_flag": as_int(rec.get("contact_flag")),
        "comments_requested": as_int(rec.get("comments_requested")),
        "submit_time": as_int(rec.get("submitTime")),
        "attempts": as_int(rec.get("attempts")),
        "info": as_str_list(rec.get("info")),
        "boundary": pick(bd if isinstance(bd := rec.get("boundary"), dict) else {},
                         ("title", "group", "name", "description", "path")),
        "stage": [{"name": s.get("name"), "time": as_int(s.get("time"))}
                  for s in rec.get("stage") or [] if isinstance(s, dict)],
        "release_data": [{
            "dataset": r.get("dataset"),
            "custom_name": r.get("custom_name"),
            "hash": r.get("hash"),
            # map_ wants an item list, and filter values are always lists
            "filters": [(k, as_str_list(v))
                        for k, v in (r.get("filters") or {}).items()],
        } for r in rec.get("release_data") or [] if isinstance(r, dict)],
        "raster_data": [{
            "name": d.get("name"),
            "title": d.get("title"),
            "base": d.get("base"),
            "type": d.get("type"),
            "custom_name": d.get("custom_name"),
            "temporal_type": d.get("temporal_type"),
            "extract_types": as_str_list((d.get("options") or {}).get("extract_types")),
            "files": [{"name": f.get("name"), "path": f.get("path"),
                       "display": f.get("display"), "bytes": as_int(f.get("bytes")),
                       "start": as_int(f.get("start")), "end": as_int(f.get("end"))}
                      for f in d.get("files") or [] if isinstance(f, dict)],
        } for d in rec.get("raster_data") or [] if isinstance(d, dict)],
    }


def main():
    rows, n, dropped, truncated = [], 0, set(), False
    writer = pq.ParquetWriter(DST, SCHEMA, compression="zstd")
    try:
        with open(SRC, "rb") as f:
            try:
                for rec in ijson.items(f, "item", use_float=True):
                    dropped |= (set(rec) - set(SCHEMA.names)
                                - {"_id", "submitTime"}) - JUNK
                    rows.append(convert(rec))
                    n += 1
                    if len(rows) >= BATCH:
                        writer.write_table(pa.Table.from_pylist(rows, schema=SCHEMA))
                        rows.clear()
            except ijson.common.IncompleteJSONError:
                truncated = True
        if rows:
            writer.write_table(pa.Table.from_pylist(rows, schema=SCHEMA))
    finally:
        writer.close()

    print(f"wrote {n} records -> {DST}")
    if truncated:
        print("WARNING: source JSON is truncated; wrote all complete records "
              "before the break (the final partial record is not recoverable).")
    if dropped:
        print(f"NOTE: unmapped top-level keys ignored: {sorted(dropped)}")


if __name__ == "__main__":
    main()
