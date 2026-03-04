from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import uvicorn


load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def run() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload_enabled = os.getenv("NOVARED_RELOAD", "1") == "1"
    uvicorn.run("webapp:app", host=host, port=port, reload=reload_enabled, app_dir=str(SRC_DIR))


if __name__ == "__main__":
    run()
