
import json
from pathlib import Path

from utils.db import insert_dataset as insd



json_path = Path("../data/esa_lc/raster_ingest.json")

json_data = json.loads(json_path.read_text())


DS = insd.Dataset(**json_data)

insd.insert_dataset(DS)
insd.update_dataset(DS)
