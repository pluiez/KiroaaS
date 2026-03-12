# -*- coding: utf-8 -*-

"""
Patched Kiro Gateway entry point.

This entry point monkey patches Enterprise device registration loading so
`ENTERPRISE_DEVICE_REG_PATH` can override the default hash-based file path.
"""

import copy
import json
import os
from pathlib import Path

import main
from loguru import logger

from kiro.auth import KiroAuthManager
from kiro.config import _get_raw_env_value, _warn_timeout_configuration


ENTERPRISE_DEVICE_REG_PATH_ENV = "ENTERPRISE_DEVICE_REG_PATH"

# Re-export for uvicorn log config compatibility when this file is __main__.
InterceptHandler = main.InterceptHandler
app = main.app


def _resolve_enterprise_device_reg_path(client_id_hash: str) -> Path:
    raw_env_path = _get_raw_env_value(ENTERPRISE_DEVICE_REG_PATH_ENV)
    if raw_env_path is None:
        raw_env_path = os.getenv(ENTERPRISE_DEVICE_REG_PATH_ENV)

    if raw_env_path is not None and raw_env_path.strip():
        return Path(raw_env_path).expanduser()

    return Path.home() / ".aws" / "sso" / "cache" / f"{client_id_hash}.json"


def _patched_load_enterprise_device_registration(
    self: KiroAuthManager,
    client_id_hash: str,
) -> None:
    device_reg_path = _resolve_enterprise_device_reg_path(client_id_hash)

    if not device_reg_path.exists():
        logger.error(f"Enterprise device registration file not found: {device_reg_path}")
        raise SystemExit(1)

    try:
        with open(device_reg_path, "r", encoding="utf-8") as file_handle:
            device_data = json.load(file_handle)
    except Exception as exc:
        logger.error(f"Error loading enterprise device registration from {device_reg_path}: {exc}")
        raise SystemExit(1) from exc

    missing_fields = [
        field_name
        for field_name in ("clientId", "clientSecret")
        if not device_data.get(field_name)
    ]
    if missing_fields:
        fields = ", ".join(missing_fields)
        logger.error(
            f"Enterprise device registration missing required fields ({fields}): {device_reg_path}"
        )
        raise SystemExit(1)

    self._client_id = device_data["clientId"]
    self._client_secret = device_data["clientSecret"]

    logger.info(f"Enterprise device registration loaded from {device_reg_path}")


def _build_uvicorn_log_config() -> dict:
    log_config = copy.deepcopy(main.UVICORN_LOG_CONFIG)
    log_config["handlers"]["default"]["class"] = "__main__.InterceptHandler"
    return log_config


KiroAuthManager._load_enterprise_device_registration = _patched_load_enterprise_device_registration
UVICORN_LOG_CONFIG = _build_uvicorn_log_config()


if __name__ == "__main__":
    import uvicorn

    main.validate_configuration()
    _warn_timeout_configuration()

    args = main.parse_cli_args()
    final_host, final_port = main.resolve_server_config(args)

    main.print_startup_banner(final_host, final_port)
    logger.info(f"Starting Uvicorn server on {final_host}:{final_port}...")

    uvicorn.run(
        app,
        host=final_host,
        port=final_port,
        log_config=UVICORN_LOG_CONFIG,
    )
