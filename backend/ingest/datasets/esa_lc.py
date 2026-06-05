from gqcore.utils.logs import get_logger
from gqcore.utils.ingest.ingest_dataset import ingest_dataset

get_logger("ingest")

ingest_dataset(json_path="/tmp/geoquery-update/data/esa_lc/raster_ingest.json", update_or_insert=True)
