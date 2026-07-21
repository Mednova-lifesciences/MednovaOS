from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repository root is importable when backend/app.py is imported.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app  # noqa: E402

__all__ = ['app']

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
