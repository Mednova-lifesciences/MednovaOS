from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .utils import get_setting


def configure_logging(name: str = "mednova_sync") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    log_level_name = (get_setting("LOG_LEVEL") or "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logger.setLevel(log_level)

    log_dir = Path(get_setting("LOG_DIR") or Path(__file__).resolve().parents[2] / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "sync.log"

    handler = RotatingFileHandler(
        log_file,
        maxBytes=int(get_setting("LOG_MAX_BYTES") or "10485760"),
        backupCount=int(get_setting("LOG_BACKUP_COUNT") or "5"),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
