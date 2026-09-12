"""
RAAH backend package.

Loads .env here rather than in main.py because store.py and
routers/whatsapp.py read os.getenv at import time -- by the time main.py's
body runs, those values have already been captured. Package __init__ is the
only hook guaranteed to run before any `app.*` import.
"""

from __future__ import annotations

from pathlib import Path

try:
    from dotenv import load_dotenv

    _env = Path(__file__).resolve().parent / ".env"
    if _env.exists():
        load_dotenv(_env, override=False)
except ImportError:
    # python-dotenv is optional; real environment variables still work.
    pass