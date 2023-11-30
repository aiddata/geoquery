
import json
from pathlib import Path

from gqcore.utils.db import features as futils


def ingest_feature_collection(json_path: str = None, json_data: dict = None, update: bool = False) -> None:
    if json_path is None and json_data is None:
        raise ValueError("Must provide either json_path or json_data")
    elif json_path is not None and json_data is not None:
        raise ValueError("Must provide either json_path or json_data, not both")
    elif json_path is not None:
        path = Path(json_path)
        data = json.loads(path.read_text())
    else:
        data = json_data

    FC = futils.FeatureCollection(**data)
    if update:
        futils.update_feature_collection(FC)
    else:
        futils.insert_feature_collection(FC)
