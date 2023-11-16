
import json
from pathlib import Path

from utils.db import insert_dataset as id



json_path = Path("../data/esa_lc/raster_ingest.json")

json_data = json.loads(json_path.read_text())


DS = id.Dataset(**json_data)

id.insert_dataset(DS)
id.update_dataset(DS)
