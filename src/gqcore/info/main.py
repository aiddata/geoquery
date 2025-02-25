from fastapi import FastAPI
import json

from gqcore.utils.db.conn import get_conn

app = FastAPI()


@app.get("/")
async def root():
    with open('resp.json', 'r') as json_file:
        info_json_object = json.load(json_file)
    
    return [
        json.dumps(info_json_object, indent=1)
    ]