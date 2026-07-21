from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    from supabase import create_client, Client
except ImportError:  # pragma: no cover
    create_client = None  # type: ignore[assignment]
    Client = Any  # type: ignore[assignment]

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH)


def get_supabase() -> Any:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured in .env")
    if create_client is None:
        raise RuntimeError("supabase-py is not installed")
    return create_client(url, key)
