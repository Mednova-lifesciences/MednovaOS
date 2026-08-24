from __future__ import annotations

import logging
import os

DEFAULT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def configure_logger(name: str = "mednova") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(DEFAULT_LOG_LEVEL)
    logger.propagate = False
    return logger


def get_logger(name: str = "mednova") -> logging.Logger:
    return configure_logger(name)
