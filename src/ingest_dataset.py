
import json
from pathlib import Path

from utils.db import dataset as dutils


def ingest_dataset(json_path: str = None, json_data: dict = None, update: bool = False) -> None:
    if json_path is None and json_data is None:
        raise ValueError("Must provide either json_path or json_data")
    elif json_path is not None and json_data is not None:
        raise ValueError("Must provide either json_path or json_data, not both")
    elif json_path is not None:
        path = Path(json_path)
        data = json.loads(path.read_text())
    else:
        data = json_data

    DS = dutils.Dataset(**data)
    if update:
        dutils.update_dataset(DS)
    else:
        dutils.insert_dataset(DS)


if __name__ == "__main__":
    # test dataset
    ingest_dataset(json_path="../data/esa_lc/raster_ingest.json", update=True)
    # ingest_dataset(json_data=json.loads(Path("../data/esa_lc/raster_ingest.json").read_text()), update=True)
