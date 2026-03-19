#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from main import invoke  # noqa: E402


SAMPLE_CHAT_CONFIGS: dict[str, dict[str, Any]] = {
    "Sample Marketing Chat": {
        "channel": "email",
        "channels": ["email", "linkedin"],
        "product": "B2B analytics platform",
        "audience": "operations leaders",
        "objective": "launch the product with channel-ready messaging that feels credible and practical",
        "brand_voice": "credible, practical, professional",
        "thinking_depth": "medium",
        "ui_language": "en",
        "output_sections": ["generator"],
        "extra_requirements": (
            "Include both email and LinkedIn guidance. "
            "Keep the answer concise but concrete, and avoid hype or inflated claims."
        ),
    },
    "Sample General Chat": {
        "thinking_depth": "low",
        "ui_language": "en",
        "extra_requirements": "Answer as a practical marketing collaborator. Keep the structure crisp and useful.",
    },
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh sample chats with live model outputs.")
    parser.add_argument(
        "--sqlite-path",
        default="data/webapp.db",
        help="Path to the local SQLite database (default: data/webapp.db).",
    )
    return parser.parse_args()


def _json_loads(raw: str | None, fallback: Any) -> Any:
    if raw is None or raw == "":
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _build_brand_kb_context(conn: sqlite3.Connection, kb_key: str | None, kb_version: int | None) -> str:
    if not kb_key or kb_version is None:
        return ""
    row = conn.execute(
        """
        SELECT kb_key, kb_name, version, brand_voice, positioning_json, glossary_json,
               forbidden_words_json, required_terms_json, claims_policy_json, examples_json, notes
        FROM brand_kb_versions
        WHERE kb_key = ? AND version = ?
        """,
        (kb_key, kb_version),
    ).fetchone()
    if not row:
        return ""

    parts = [
        "Shared brand knowledge context (apply when relevant):",
        f"- Knowledge Base: {row['kb_name']} (key={row['kb_key']}, version={row['version']})",
    ]
    if row["brand_voice"]:
        parts.append(f"- Brand voice: {row['brand_voice']}")

    positioning = _json_loads(row["positioning_json"], {})
    if positioning:
        parts.append(f"- Positioning: {json.dumps(positioning, ensure_ascii=False)}")
    glossary = _json_loads(row["glossary_json"], [])
    if glossary:
        parts.append(f"- Glossary: {json.dumps(glossary, ensure_ascii=False)}")
    forbidden_words = _json_loads(row["forbidden_words_json"], [])
    if forbidden_words:
        parts.append(f"- Forbidden words: {json.dumps(forbidden_words, ensure_ascii=False)}")
    required_terms = _json_loads(row["required_terms_json"], [])
    if required_terms:
        parts.append(f"- Required terms: {json.dumps(required_terms, ensure_ascii=False)}")
    claims_policy = _json_loads(row["claims_policy_json"], {})
    if claims_policy:
        parts.append(f"- Claims policy: {json.dumps(claims_policy, ensure_ascii=False)}")
    examples = _json_loads(row["examples_json"], None)
    if examples:
        parts.append(f"- Examples: {json.dumps(examples, ensure_ascii=False)}")
    if row["notes"]:
        parts.append(f"- Notes: {row['notes']}")
    return "\n".join(parts)


def _load_sample_row(conn: sqlite3.Connection, title: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT c.id, c.title, c.model_id, c.kb_key, c.kb_version, u.id AS user_message_id, u.content AS user_content
        FROM conversations c
        JOIN messages u ON u.conversation_id = c.id AND u.role = 'user'
        WHERE c.title = ?
        ORDER BY u.id ASC
        LIMIT 1
        """,
        (title,),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Sample conversation not found: {title}")
    return row


def _generate_output(conn: sqlite3.Connection, row: sqlite3.Row, config: dict[str, Any]) -> str:
    extra_parts: list[str] = []
    extra_text = str(config.get("extra_requirements") or "").strip()
    if extra_text:
        extra_parts.append(extra_text)
    kb_context = _build_brand_kb_context(conn, row["kb_key"], row["kb_version"])
    if kb_context:
        extra_parts.append(kb_context)

    tool_args = {
        "channel": config.get("channel"),
        "channels": config.get("channels"),
        "product": config.get("product"),
        "audience": config.get("audience"),
        "objective": config.get("objective"),
        "brand_voice": config.get("brand_voice"),
        "ui_language": config.get("ui_language", "en"),
        "output_sections": config.get("output_sections"),
        "model_id": row["model_id"],
        "thinking_depth": config.get("thinking_depth", "low"),
        "include_trace": False,
        "extra_requirements": "\n\n".join(extra_parts) if extra_parts else None,
    }
    payload = {
        "prompt": row["user_content"],
        "tool_args": tool_args,
    }
    response = invoke(payload)
    if not isinstance(response, dict):
        raise RuntimeError(f"Unexpected response type for {row['title']}: {type(response)}")
    if "error" in response:
        raise RuntimeError(f"Model call failed for {row['title']}: {response['error']}")
    result = str(response.get("result") or "").strip()
    if not result:
        raise RuntimeError(f"Empty model output for {row['title']}")
    if "Local Fallback Mode" in result:
        raise RuntimeError(f"Credential fallback detected for {row['title']}; refusing to save fallback text")
    return result


def _rewrite_conversation(conn: sqlite3.Connection, conversation_id: int, assistant_text: str, model_id: str) -> None:
    now = now_utc_iso()
    user_rows = conn.execute(
        "SELECT id FROM messages WHERE conversation_id = ? AND role = 'user' ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    if not user_rows:
        raise RuntimeError(f"No user message found for conversation {conversation_id}")
    primary_user_id = int(user_rows[0]["id"])
    extra_user_ids = [int(row["id"]) for row in user_rows[1:]]

    assistant_rows = conn.execute(
        "SELECT id FROM messages WHERE conversation_id = ? AND role = 'assistant' ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    primary_assistant_id = int(assistant_rows[0]["id"]) if assistant_rows else None
    extra_assistant_ids = [int(row["id"]) for row in assistant_rows[1:]] if assistant_rows else []

    conn.execute("DELETE FROM orchestrator_runs WHERE conversation_id = ?", (conversation_id,))
    conn.execute("DELETE FROM conversation_memories WHERE conversation_id = ?", (conversation_id,))

    if extra_user_ids:
        placeholders = ",".join(["?"] * len(extra_user_ids))
        conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", tuple(extra_user_ids))
    if extra_assistant_ids:
        placeholders = ",".join(["?"] * len(extra_assistant_ids))
        conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", tuple(extra_assistant_ids))

    if primary_assistant_id is not None:
        conn.execute(
            "UPDATE messages SET content = ?, created_at = ? WHERE id = ?",
            (assistant_text, now, primary_assistant_id),
        )
    else:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
            (conversation_id, assistant_text, now),
        )

    conn.execute(
        "UPDATE conversations SET model_id = ?, updated_at = ? WHERE id = ?",
        (model_id, now, conversation_id),
    )


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        for title, config in SAMPLE_CHAT_CONFIGS.items():
            row = _load_sample_row(conn, title)
            assistant_text = _generate_output(conn, row, config)
            _rewrite_conversation(conn, int(row["id"]), assistant_text, str(row["model_id"]))
            print(f"[updated] {title}")
            print(assistant_text[:400].strip())
            print("---")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
