import os
import toml

import gqcore.utils

__version__ = "0.0.1"

confg_path = os.path.dirname(__file__) + "/config.toml"
config = toml.load(confg_path)


def get_config():
    return config
