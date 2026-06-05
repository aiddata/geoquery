from pathlib import Path

from gqcore.utils.ingest.ingest_dataset import ingest_dataset
from gqcore.utils.logs import get_logger

get_logger("ingest")

ingest_dataset(
    json_data=Path("/tmp/geoquery-update/data/critical_habitats/raster_ingest.json"),
    update_or_insert=True,
)
