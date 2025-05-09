"""
sudo apt install uvicorn

uvicorn main:app --reload

http://127.0.0.1:8000/
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/redoc
http://127.0.0.1:8000/openapi.json
"""

from fastapi import FastAPI, HTTPException
import json
from pathlib import Path
from datetime import datetime

from gqcore.utils.db.conn import get_conn

app = FastAPI()


@app.get("/")
async def root():
    return [
        "/datasets",
        "/get_dataset/{dataset_id}",
        "/dataset_resources/{dataset_id}",
        "/feature_collections",
        "/feature_collections/{fc_id}",
        "/feat_map/{fc_id}",
        "/features/{feature_id}",
        "/info"
    ]


@app.get("/datasets")
async def get_datasets():
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM datasets WHERE active = true AND public = true"""
            ).fetchall()
            dataset_list = [
                {
                    "id": i["id"],
                    "name": i["name"],
                    "title": i["title"],
                    "description": i["description"],
                }
                for i in x
            ]
            return dataset_list
        
@app.get("/get_dataset/{dataset_id}") #performs same function as /datasets/{dataset_id}
async def get_dataset(dataset_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM datasets WHERE active = true AND public = true AND id = %s""",
                (dataset_id,),
            ).fetchone()
            return x

@app.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM datasets WHERE active = true AND public = true AND id = %s""",
                (dataset_id,),
            ).fetchone()
            return x


@app.get("/dataset_resources/{dataset_id}")
async def get_dataset_resources(dataset_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM dataset_resources WHERE dataset_id = %s""",
                (dataset_id,),
            ).fetchall()
            return x


@app.get("/feature_collections")
async def get_feature_collections():
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM feature_collections WHERE active = false AND public = false"""
            ).fetchall()
            feature_collection_list = [
                {
                    "id": i["id"],
                    "name": i["name"],
                    "title": i["title"],
                    "description": i["description"],
                }
                for i in x
            ]
            return feature_collection_list


@app.get("/feature_collections/{feature_collection_id}")
async def get_feature_collection(feature_collection_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM feature_collections WHERE active = true AND public = true AND id = %s""",
                (feature_collection_id,),
            ).fetchone()
            return x


@app.get("/feat_map/{fc_id}")
async def get_feat_map(fc_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM feat_map WHERE fc_id = %s""", (fc_id,)
            ).fetchall()
            return x


@app.get("/features/{feature_id}")
async def get_feature(feature_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM features WHERE id = %s""", (feature_id,)
            ).fetchone()
            return x


@app.get("/coverage")
async def get_coverage():
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute("""SELECT * FROM coverage WHERE status = 1""").fetchall()
            return x


@app.get("/coverage/features/{feature_id}")
async def get_coverage(feature_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM coverage WHERE geom_id = %s AND status = 1""",
                (feature_id,),
            ).fetchall()
            return x


@app.get("/coverage/datasets/{dataset_id}")
async def get_coverage(dataset_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            x = cur.execute(
                """SELECT * FROM coverage WHERE dataset_id = %s AND status = 1""",
                (dataset_id,),
            ).fetchall()
            return x


@app.post("/info")
async def root():
    try:
        with open('src/gqcore/api/info_resp.json', 'r') as json_file:
            info_json_object = json.load(json_file)
        return info_json_object 
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# helper function for /boundaries endpoint, consider putting in utils
def convert_sql_row_to_subboundary(row: dict) -> dict:
    other_raw = row.get("other", {})
    if isinstance(other_raw, str):
        try:
            other = json.loads(other_raw)
        except json.JSONDecodeError:
            other = {}
    elif isinstance(other_raw, dict):
        other = other_raw
    else:
        other = {}

    try:
        start = int(row.get("temporal_start") or "10000101")
    except ValueError:
        start = 10000101

    try:
        end = int(row.get("temporal_end") or "99991231")
    except ValueError:
        end = 99991231

    name = row.get("name", "")
    path = row.get("path", "")
    file_name = Path(path).name
    base_path = str(Path(path).parent)

    sub_boundary = {
        "name": other.get("boundaryName", name),
        "boundaryId": other.get("boundaryID", name),
        "temporal": {
            "start": start,
            "end": end,
            "type": row.get("temporal_type", "None"),
            "name": row.get("temporal_name", "Temporally Invariant"),
            "format": "None"
        },
        "file_format": "vector",
        "file_extension": row.get("file_extension", "").lstrip("."),
        "title": row.get("title", ""),
        "extras": {
            "sources_name": row.get("source_name", ""),
            "citation": row.get("citation", ""),
            "sources_web": row.get("source_url", ""),
            "tags": row.get("tags", "").strip("{}").split(",") if row.get("tags") else []
        },
        "resources": [
            {
                "path": file_name,
                "start": start,
                "end": end,
                "name": name,
                "bytes": None
            }
        ],
        "base": base_path,
        "scale": "global" if row.get("is_global", False) else "national",
        "version": "1",
        "spatial": {
            "type": "Polygon",
            "coordinates": []  
        },
        "active": int(row.get("active", 0)),
        "type": "boundary",
        "options": {
            "group": row.get("group_name", ""),
            "group_title": row.get("group_title", ""),
            "group_class": row.get("group_class", "")
        },
        "asdf": {
            "date_updated": str(row.get("date_updated", datetime.today().date())),
            "date_added": str(row.get("date_added", datetime.today().date())),
            "version": "1.0",
            "generator": "sql_to_json_script",
            "script": "convert_sql_boundaries.py"
        },
        "description": row.get("description", "")
    }

    return sub_boundary

    
@app.post("/boundaries")
def get_boundaries():
    x = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM feature_collections WHERE other IS NOT NULL")
            rows = cur.fetchall()
            for row in rows:
                try:
                    sub_boundary = convert_sql_row_to_subboundary(row)
                    x.append(sub_boundary)
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))

    return x

# fake_items_db = [{"item_name": "Foo"}, {"item_name": "Bar"}, {"item_name": "Baz"}]


# @app.get("/items/")
# async def read_item(skip: int = 0, limit: int = 10):
#     return fake_items_db[skip : skip + limit]


# @app.get("/items/{item_id}")
# async def read_item(item_id: str, q: str | None = None):
#     if q:
#         return {"item_id": item_id, "q": q}
#     return {"item_id": item_id}
