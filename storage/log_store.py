from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "generation_logs.jsonl"


def save_generation_log(log: dict[str, Any]) -> None:
    line = json.dumps(log, ensure_ascii=False)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
