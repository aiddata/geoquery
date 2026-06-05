import os
from pathlib import Path

import toml
from loguru import logger

import gqcore.utils

__version__ = "0.0.1"


def get_config():
    local_config_path = Path(__file__).parent / "config.toml"
    if local_config_path.exists():
        local_config = toml.load(local_config_path)
        if local_config["main"]["use_local_config"]:
            logger.trace("Local config found and being used...")
            return local_config["main"]

    k8s_config = {}

    # try fetching secrets from k8s
    secrets_dir = Path("/secrets/db")
    if secrets_dir.is_dir():
        logger.trace("DB secrets directory found, loading secrets...")
        for s in secrets_dir.iterdir():
            if not s.is_file():
                continue
            try:
                with open(s) as src:
                    k8s_config[f"postgis_{s.name}"] = src.read()
                    logger.trace(f"Loaded secret {s.name}")
            except Exception as e:
                logger.warning(f"Error loading secret {s.name}: {e}")

    # try fetching secrets from k8s
    secrets_dir = Path("/secrets/email")
    if secrets_dir.is_dir():
        logger.trace("Email secrets directory found, loading secrets...")
        for s in secrets_dir.iterdir():
            if not s.is_file():
                continue
            try:
                with open(s) as src:
                    k8s_config[f"email_{s.name}"] = src.read()
                    logger.trace(f"Loaded secret {s.name}")
            except Exception as e:
                logger.warning(f"Error loading secret {s.name}: {e}")

    # try fetching config from k8s
    config_dir = Path("/config")
    if config_dir.is_dir():
        logger.trace("Config directory found, loading config...")
        for s in config_dir.iterdir():
            if not s.is_file():
                continue
            try:
                with open(s) as src:
                    k8s_config[s.name] = src.read()
                    logger.trace(f"Loaded config item {s.name}")
            except Exception as e:
                logger.warning(f"Error loading config item {s.name}: {e}")

    if k8s_config != {}:
        logger.trace("Kubernetes config found and being used...")
        return k8s_config

    local_str = (
        "not found" if not local_config_path.exists() else "found but not being used"
    )
    logger.exception(f"No secrets directory found, and local config {local_str}.")
