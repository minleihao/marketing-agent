from __future__ import annotations

import json
from pathlib import Path

from models.brand_kb import BrandKB


KB_DIR = Path(__file__).resolve().parent / "kb"
KB_DIR.mkdir(parents=True, exist_ok=True)


def _kb_path(kb_id: str) -> Path:
    return KB_DIR / f"{kb_id}.json"


def create_kb(kb_data: dict) -> BrandKB:
    kb = BrandKB.model_validate(kb_data)
    path = _kb_path(kb.id)
    if path.exists():
        raise ValueError(f"KB already exists: {kb.id}")
    path.write_text(kb.model_dump_json(indent=2), encoding="utf-8")
    return kb


def update_kb(kb_id: str, kb_data: dict) -> BrandKB:
    path = _kb_path(kb_id)
    if not path.exists():
        raise FileNotFoundError(f"KB not found: {kb_id}")
    merged = json.loads(path.read_text(encoding="utf-8"))
    merged.update(kb_data)
    merged["id"] = kb_id
    merged["version"] = int(merged.get("version", 1)) + 1
    kb = BrandKB.model_validate(merged)
    path.write_text(kb.model_dump_json(indent=2), encoding="utf-8")
    return kb


def get_kb(kb_id: str) -> BrandKB | None:
    path = _kb_path(kb_id)
    if not path.exists():
        return None
    return BrandKB.model_validate_json(path.read_text(encoding="utf-8"))


def list_kb() -> list[BrandKB]:
    out: list[BrandKB] = []
    for path in sorted(KB_DIR.glob("*.json")):
        out.append(BrandKB.model_validate_json(path.read_text(encoding="utf-8")))
    return out
