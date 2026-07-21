from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def get_setting(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def _use_file_logging() -> bool:
    if os.getenv("MEDNOVA_ENV", "").lower() == "production" or os.getenv("FLASK_ENV", "").lower() == "production":
        return False

    explicit = (get_setting("LOG_TO_FILE") or "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "y"}

    env = os.getenv("MEDNOVA_ENV", "").lower() or os.getenv("FLASK_ENV", "").lower()
    return env != "production"


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("mednova_sync")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    if _use_file_logging():
        log_dir = Path(get_setting("LOG_DIR") or Path(__file__).resolve().parents[2] / "logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "sync.log"
        handler = logging.FileHandler(log_file, encoding="utf-8")
    else:
        handler = logging.StreamHandler()

    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def safe_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value).strip() or None


def normalize_date(value: object) -> str | None:
    if value is None:
        return None
    text = safe_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text
