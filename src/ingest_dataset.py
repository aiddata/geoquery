
import json
from pathlib import Path

from src.utils.db import dataset as dutils



json_path = Path("../data/esa_lc/raster_ingest.json")

json_data = json.loads(json_path.read_text())


DS = dutils.Dataset(**json_data)

dutils.insert_dataset(DS)
dutils.update_dataset(DS)
