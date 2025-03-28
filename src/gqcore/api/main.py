"""
sudo apt install uvicorn

uvicorn main:app --reload

http://127.0.0.1:8000/
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/redoc
http://127.0.0.1:8000/openapi.json
"""

from fastapi import FastAPI
import json
import aiofiles

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
            return xs

@app.get("/info", methods=["GET"])
async def root():
    try:
        async with aiofiles.open('src/gqcore/api/info_resp.json', 'r') as json_file:
            data = await json_file.read()
            info_json_object = json.loads(data)
        return info_json_object 
    except Exception as e:
        return {"error": str(e)}

# fake_items_db = [{"item_name": "Foo"}, {"item_name": "Bar"}, {"item_name": "Baz"}]


# @app.get("/items/")
# async def read_item(skip: int = 0, limit: int = 10):
#     return fake_items_db[skip : skip + limit]


# @app.get("/items/{item_id}")
# async def read_item(item_id: str, q: str | None = None):
#     if q:
#         return {"item_id": item_id, "q": q}
#     return {"item_id": item_id}
