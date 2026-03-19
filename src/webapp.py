import importlib.util
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Iterator

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from db_backend import (
    DATA_DIR,
    DB_BACKEND,
    DB_INTEGRITY_ERRORS,
    UPLOAD_DIR,
    _insert_and_get_id,
    _translate_qmark_to_postgres,
    db_conn,
    hash_password,
    now_utc,
    verify_password,
)
from db_schema import init_db as initialize_db
from model.load import DEFAULT_MODEL_ID
from webapp_schemas import (
    AccountPasswordInput,
    AdminCreateUserInput,
    AdminResetPasswordInput,
    AdminStatusInput,
    BrandKBInput,
    BrandKBUpdateInput,
    ConversationCreateInput,
    ConversationKBInput,
    ConversationModeInput,
    ConversationModelInput,
    ConversationThinkingDepthInput,
    ConversationTitleInput,
    ConversationVisibilityInput,
    GroupCreateInput,
    GroupInviteInput,
    GroupTransferAdminInput,
    LoginInput,
    MessageInput,
    RegisterInput,
)
from webapp_templates import ADMIN_HTML, APP_HTML, AUTH_HTML, GROUPS_HTML, KB_HTML


def _load_runtime_functions() -> tuple[Any, Any | None]:
    try:
        from main import invoke as runtime_invoke
        from main import invoke_stream as runtime_invoke_stream

        if callable(runtime_invoke):
            return runtime_invoke, runtime_invoke_stream if callable(runtime_invoke_stream) else None
    except Exception:
        pass

    main_path = Path(__file__).with_name("main.py")
    spec = importlib.util.spec_from_file_location("novared_runtime_main", main_path)
    if not spec or not spec.loader:
        raise RuntimeError("Failed to load runtime entrypoint from src/main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime_invoke = getattr(module, "invoke", None)
    if not callable(runtime_invoke):
        raise RuntimeError("`invoke` function was not found in src/main.py")
    runtime_invoke_stream = getattr(module, "invoke_stream", None)
    return runtime_invoke, runtime_invoke_stream if callable(runtime_invoke_stream) else None


invoke, invoke_stream = _load_runtime_functions()


SESSION_COOKIE = "nova_session"
SESSION_DAYS = 7
MAX_DOC_SIZE_BYTES = 3 * 1024 * 1024
MAX_DOC_PREVIEW_CHARS = 6000
MAX_MEMORY_TURNS = 8
MEMORY_SUMMARY_MAX_CHARS = 1400
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 10 * 60
LOGIN_RATE_LIMIT_MAX_FAILURES = 8
COOKIE_SECURE = os.getenv("NOVARED_COOKIE_SECURE", "0").strip() in {"1", "true", "True"}

SUPPORTED_MODELS = [
    "us.anthropic.claude-sonnet-4-6",
    "us.amazon.nova-micro-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-pro-v1:0",
]
TASK_MODES = {"chat", "marketing"}
THINKING_DEPTH_LEVELS = {"low", "medium", "high"}
DEFAULT_THINKING_DEPTH = "low"
DEFAULT_CONVERSATION_TITLES = {"新对话", "新营销任务", "New Chat", "New Marketing Task"}
VISIBILITY_LEVELS = {"private", "task", "company"}
GROUP_TYPES = {"task", "company"}
SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log", ".py", ".html", ".xml", ".yaml", ".yml"}

DEFAULT_ADMIN_USER = os.getenv("NOVARED_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("NOVARED_ADMIN_PASSWORD", "admin123456")
ENFORCE_DEFAULT_ADMIN_PASSWORD_CHANGE = os.getenv("NOVARED_ENFORCE_DEFAULT_ADMIN_PASSWORD_CHANGE", "0").strip() in {
    "1",
    "true",
    "True",
}


def init_db() -> None:
    initialize_db(
        default_model_id=DEFAULT_MODEL_ID,
        default_thinking_depth=DEFAULT_THINKING_DEPTH,
        default_admin_user=DEFAULT_ADMIN_USER,
        default_admin_password=DEFAULT_ADMIN_PASSWORD,
        enforce_default_admin_password_change=ENFORCE_DEFAULT_ADMIN_PASSWORD_CHANGE,
    )


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Marketing Copilot Web Chat", lifespan=app_lifespan)


def _is_csrf_exempt(request: Request) -> bool:
    if not request.url.path.startswith("/api/"):
        return True
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True
    path = request.url.path
    if path in {"/api/public/groups"}:
        return True
    return False


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    if _is_csrf_exempt(request):
        return await call_next(request)
    session_row = _request_session_row(request)
    if not session_row:
        return await call_next(request)
    expected = (session_row["csrf_token"] or "").strip()
    provided = (request.headers.get("X-CSRF-Token") or "").strip()
    if not expected or provided != expected:
        return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
    return await call_next(request)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def current_user(request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None

    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            return None

        session = conn.execute(
            "SELECT expires_at FROM sessions WHERE token = ?", (token,)
        ).fetchone()
        if not session:
            return None
        if parse_time(session["expires_at"]) <= now_utc() or row["is_active"] == 0:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None

        return row


def must_login(request: Request) -> sqlite3.Row:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def must_admin(request: Request) -> sqlite3.Row:
    user = must_login(request)
    if user["is_admin"] == 0:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def create_session(user_id: int) -> tuple[str, datetime, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    expires_at = now_utc() + timedelta(days=SESSION_DAYS)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, token, csrf_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, token, csrf_token, expires_at.isoformat(), now_utc().isoformat()),
        )
    return token, expires_at, csrf_token


def _request_session_row(request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, user_id, token, csrf_token, expires_at FROM sessions WHERE token = ?",
            (token,),
        ).fetchone()
        if row and not row["csrf_token"]:
            refreshed = secrets.token_urlsafe(24)
            conn.execute("UPDATE sessions SET csrf_token = ? WHERE id = ?", (refreshed, row["id"]))
            row = conn.execute(
                "SELECT id, user_id, token, csrf_token, expires_at FROM sessions WHERE id = ?",
                (row["id"],),
            ).fetchone()
        return row


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


def _record_login_attempt(username: str, ip_address: str, success: bool) -> None:
    now = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO login_attempts (username, ip_address, success, created_at) VALUES (?, ?, ?, ?)",
            (username, ip_address, 1 if success else 0, now),
        )
        cutoff = (now_utc() - timedelta(seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS * 5)).isoformat()
        conn.execute("DELETE FROM login_attempts WHERE created_at < ?", (cutoff,))


def _is_login_rate_limited(username: str, ip_address: str) -> bool:
    since = (now_utc() - timedelta(seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS)).isoformat()
    with db_conn() as conn:
        user_failures = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM login_attempts
            WHERE username = ? AND success = 0 AND created_at >= ?
            """,
            (username, since),
        ).fetchone()["cnt"]
        ip_failures = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM login_attempts
            WHERE ip_address = ? AND success = 0 AND created_at >= ?
            """,
            (ip_address, since),
        ).fetchone()["cnt"]
    return user_failures >= LOGIN_RATE_LIMIT_MAX_FAILURES or ip_failures >= LOGIN_RATE_LIMIT_MAX_FAILURES


def _validate_csrf_header(request: Request) -> None:
    session_row = _request_session_row(request)
    if not session_row:
        return
    expected = (session_row["csrf_token"] or "").strip()
    provided = (request.headers.get("X-CSRF-Token") or "").strip()
    if not expected or expected != provided:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def _normalize_visibility(raw: str | None) -> str:
    value = (raw or "private").strip().lower()
    if value not in VISIBILITY_LEVELS:
        raise HTTPException(status_code=400, detail=f"Unsupported visibility: {value}")
    return value


def _normalize_group_type(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value not in GROUP_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported group_type: {value}")
    return value


def _is_group_member(user_id: int, group_id: int, *, approved_only: bool = True) -> bool:
    query = (
        "SELECT 1 FROM group_memberships WHERE group_id = ? AND user_id = ? AND status = 'approved'"
        if approved_only
        else "SELECT 1 FROM group_memberships WHERE group_id = ? AND user_id = ?"
    )
    with db_conn() as conn:
        row = conn.execute(query, (group_id, user_id)).fetchone()
    return bool(row)


def _is_group_admin(user_id: int, group_id: int) -> bool:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM group_memberships
            WHERE group_id = ? AND user_id = ? AND status = 'approved' AND role = 'admin'
            """,
            (group_id, user_id),
        ).fetchone()
    return bool(row)


def _validate_share_group_for_user(user_id: int, visibility: str, share_group_id: int | None) -> tuple[str, int | None]:
    visibility_norm = _normalize_visibility(visibility)
    if visibility_norm == "private":
        return visibility_norm, None
    if not share_group_id:
        raise HTTPException(status_code=400, detail="share_group_id is required for non-private visibility")
    with db_conn() as conn:
        group_row = conn.execute(
            "SELECT id, group_type FROM groups WHERE id = ?",
            (share_group_id,),
        ).fetchone()
    if not group_row:
        raise HTTPException(status_code=404, detail="Group not found")
    expected_type = "company" if visibility_norm == "company" else "task"
    if group_row["group_type"] != expected_type:
        raise HTTPException(status_code=400, detail=f"visibility '{visibility_norm}' requires a {expected_type} group")
    if not _is_group_member(user_id, share_group_id, approved_only=True):
        raise HTTPException(status_code=403, detail="You are not an approved member of this group")
    return visibility_norm, share_group_id


def _can_user_view_by_visibility(user_id: int, owner_id: int, visibility: str, share_group_id: int | None) -> bool:
    if owner_id == user_id:
        return True
    if visibility == "private":
        return False
    if share_group_id is None:
        return False
    return _is_group_member(user_id, share_group_id, approved_only=True)


def conversation_owner_or_404(user_id: int, conversation_id: int) -> sqlite3.Row:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


def conversation_visible_or_404(user_id: int, conversation_id: int) -> sqlite3.Row:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not _can_user_view_by_visibility(
        user_id=user_id,
        owner_id=row["user_id"],
        visibility=(row["visibility"] or "private"),
        share_group_id=row["share_group_id"],
    ):
        raise HTTPException(status_code=403, detail="No access to this conversation")
    return row


def allowed_models() -> list[str]:
    configured = os.getenv("NOVARED_ALLOWED_MODELS")
    if configured:
        custom = [x.strip() for x in configured.split(",") if x.strip()]
        return custom or [DEFAULT_MODEL_ID]
    return SUPPORTED_MODELS


def _extract_text_from_upload(filename: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_TEXT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix or 'unknown'}. Supported: {', '.join(sorted(SUPPORTED_TEXT_EXTENSIONS))}",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return text[:MAX_DOC_PREVIEW_CHARS]


def _split_text_chunks(text: str, *, chunk_size: int = 700, overlap: int = 120) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]
    chunks: list[str] = []
    step = max(100, chunk_size - overlap)
    cursor = 0
    while cursor < len(cleaned):
        piece = cleaned[cursor : cursor + chunk_size].strip()
        if piece:
            chunks.append(piece)
        if cursor + chunk_size >= len(cleaned):
            break
        cursor += step
    return chunks


def _tokenize_for_retrieval(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [x for x in re.findall(r"[a-z0-9\u4e00-\u9fff_]+", lowered) if len(x) >= 2]


def _index_document_chunks(document_id: int, conversation_id: int, text_content: str) -> None:
    chunks = _split_text_chunks(text_content)
    now = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
        conn.executemany(
            """
            INSERT INTO document_chunks (document_id, conversation_id, chunk_index, chunk_text, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(document_id, conversation_id, idx, chunk, now) for idx, chunk in enumerate(chunks)],
        )


def _build_recent_messages_context(conversation_id: int, *, max_turns: int = MAX_MEMORY_TURNS) -> str:
    limit_rows = max(2, max_turns * 2)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (conversation_id, limit_rows),
        ).fetchall()
    if not rows:
        return ""
    ordered = list(reversed(rows))
    parts = ["Recent conversation context:"]
    for row in ordered:
        role_label = "User" if row["role"] == "user" else "Assistant"
        parts.append(f"- {role_label}: {row['content'][:500]}")
    return "\n".join(parts)


def _refresh_conversation_summary(conversation_id: int) -> None:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT 24
            """,
            (conversation_id,),
        ).fetchall()
        if not rows:
            conn.execute("DELETE FROM conversation_memories WHERE conversation_id = ?", (conversation_id,))
            return
        ordered = list(reversed(rows))
        summary_lines = []
        for row in ordered:
            prefix = "U" if row["role"] == "user" else "A"
            summary_lines.append(f"{prefix}: {row['content'][:180]}")
        summary_text = "\n".join(summary_lines)[-MEMORY_SUMMARY_MAX_CHARS:]
        source_message_id = ordered[-1]["id"]
        now = now_utc().isoformat()
        existing = conn.execute(
            "SELECT conversation_id FROM conversation_memories WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE conversation_memories
                SET summary = ?, source_message_id = ?, updated_at = ?
                WHERE conversation_id = ?
                """,
                (summary_text, source_message_id, now, conversation_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO conversation_memories (conversation_id, summary, source_message_id, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, summary_text, source_message_id, now),
            )


def _build_conversation_memory_context(conversation_id: int) -> str:
    recent_context = _build_recent_messages_context(conversation_id)
    with db_conn() as conn:
        memory_row = conn.execute(
            "SELECT summary, updated_at FROM conversation_memories WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    parts = []
    if memory_row and memory_row["summary"]:
        parts.append("Rolling summary memory:")
        parts.append(memory_row["summary"])
    if recent_context:
        parts.append(recent_context)
    return "\n\n".join(parts)


def _build_document_context(conversation_id: int, *, query_text: str = "", top_k: int = 6) -> str:
    with db_conn() as conn:
        chunks = conn.execute(
            """
            SELECT c.id, c.chunk_text, c.chunk_index, d.filename
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.conversation_id = ?
            """,
            (conversation_id,),
        ).fetchall()
    if not chunks:
        with db_conn() as conn:
            docs = conn.execute(
                "SELECT id, text_content FROM documents WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchall()
        if not docs:
            return ""
        for doc in docs:
            _index_document_chunks(doc["id"], conversation_id, doc["text_content"])
        with db_conn() as conn:
            chunks = conn.execute(
                """
                SELECT c.id, c.chunk_text, c.chunk_index, d.filename
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.conversation_id = ?
                """,
                (conversation_id,),
            ).fetchall()
        if not chunks:
            return ""
    query_tokens = _tokenize_for_retrieval(query_text)
    query_counts = Counter(query_tokens)
    scored: list[tuple[int, sqlite3.Row]] = []
    for chunk in chunks:
        if not query_counts:
            score = 1
        else:
            chunk_counts = Counter(_tokenize_for_retrieval(chunk["chunk_text"]))
            score = sum(min(query_counts[token], chunk_counts.get(token, 0)) for token in query_counts)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: (item[0], -item[1]["chunk_index"]), reverse=True)
    selected = [chunk for _, chunk in scored[:top_k]]
    if not selected:
        selected = [chunk for chunk in chunks[: min(top_k, len(chunks))]]
    parts = ["Retrieved document context (top relevant chunks):"]
    for chunk in selected:
        parts.append(f"\n[Document: {chunk['filename']} | chunk {chunk['chunk_index']}]\n{chunk['chunk_text']}")
    return "\n".join(parts)


def _normalize_kb_key(raw: str) -> str:
    key = raw.strip().lower()
    if not key:
        raise HTTPException(status_code=400, detail="kb_key is required")
    return key[:80]


def _normalize_task_mode(raw: str | None) -> str:
    mode = (raw or "chat").strip().lower()
    if mode not in TASK_MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported task_mode: {mode}")
    return mode


def _normalize_thinking_depth(raw: str | None) -> str:
    depth = (raw or DEFAULT_THINKING_DEPTH).strip().lower()
    if depth not in THINKING_DEPTH_LEVELS:
        raise HTTPException(status_code=400, detail=f"Unsupported thinking_depth: {depth}")
    return depth


def _is_default_conversation_title(title: str | None) -> bool:
    return (title or "").strip() in DEFAULT_CONVERSATION_TITLES


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _normalize_string_list(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _parse_json_value(raw: str) -> Any | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _extract_first_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    direct = _parse_json_value(text)
    if isinstance(direct, dict):
        return direct

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    if fence_match:
        fenced = _parse_json_value(fence_match.group(1))
        if isinstance(fenced, dict):
            return fenced

    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:idx + 1]
                    parsed = _parse_json_value(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = text.find("{", start + 1)
    return None


def _to_kb_prompt_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _to_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def _normalize_kb_structured_fields_with_llm(
    *,
    positioning: Any,
    glossary: Any,
    forbidden_words: Any,
    required_terms: Any,
    claims_policy: Any,
    examples: Any,
) -> dict[str, Any]:
    raw_map = {
        "positioning": positioning,
        "glossary": glossary,
        "forbidden_words": forbidden_words,
        "required_terms": required_terms,
        "claims_policy": claims_policy,
        "examples": examples,
    }

    parsed_map: dict[str, Any] = {}
    needs_llm = False
    for key, value in raw_map.items():
        if value is None:
            parsed_map[key] = None
            continue
        if isinstance(value, (dict, list)):
            parsed_map[key] = value
            continue
        if isinstance(value, str):
            direct = _parse_json_value(value)
            if direct is not None:
                parsed_map[key] = direct
            else:
                parsed_map[key] = value
                if value.strip():
                    needs_llm = True
            continue
        parsed_map[key] = value

    if needs_llm:
        prompt = f"""
Convert this Brand Knowledge Base draft into a strict JSON object.

Required keys and formats:
- positioning: object
- glossary: array
- forbidden_words: array of strings
- required_terms: array of strings
- claims_policy: object
- examples: object or null

Input draft values (some may be natural language):
- positioning: {_to_kb_prompt_text(raw_map['positioning']) or 'null'}
- glossary: {_to_kb_prompt_text(raw_map['glossary']) or 'null'}
- forbidden_words: {_to_kb_prompt_text(raw_map['forbidden_words']) or 'null'}
- required_terms: {_to_kb_prompt_text(raw_map['required_terms']) or 'null'}
- claims_policy: {_to_kb_prompt_text(raw_map['claims_policy']) or 'null'}
- examples: {_to_kb_prompt_text(raw_map['examples']) or 'null'}

Return ONLY valid JSON.
""".strip()
        llm_output = invoke(
            {
                "prompt": prompt,
                "tool_args": {
                    "model_id": DEFAULT_MODEL_ID,
                    "ui_language": "en",
                },
            }
        )
        if "error" not in llm_output:
            parsed = _extract_first_json_object(str(llm_output.get("result", "")))
            if isinstance(parsed, dict):
                for key in raw_map:
                    if key in parsed:
                        parsed_map[key] = parsed[key]

    positioning_obj = parsed_map["positioning"] if isinstance(parsed_map["positioning"], dict) else {}
    glossary_list = _to_list(parsed_map["glossary"])
    forbidden_list = _normalize_string_list(_to_list(parsed_map["forbidden_words"]))
    required_list = _normalize_string_list(_to_list(parsed_map["required_terms"]))
    claims_obj = parsed_map["claims_policy"] if isinstance(parsed_map["claims_policy"], dict) else {}
    examples_value = parsed_map["examples"]
    if examples_value is not None and not isinstance(examples_value, (dict, list, str, int, float, bool)):
        examples_value = None

    return {
        "positioning": positioning_obj,
        "glossary": glossary_list,
        "forbidden_words": forbidden_list,
        "required_terms": required_list,
        "claims_policy": claims_obj,
        "examples": examples_value,
    }


def _kb_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = {
        "kb_key": row["kb_key"],
        "kb_name": row["kb_name"],
        "version": row["version"],
        "owner_id": row["owner_id"] if "owner_id" in row.keys() else None,
        "visibility": row["visibility"] if "visibility" in row.keys() else "private",
        "share_group_id": row["share_group_id"] if "share_group_id" in row.keys() else None,
        "share_group_name": row["share_group_name"] if "share_group_name" in row.keys() else None,
        "owner_username": row["owner_username"] if "owner_username" in row.keys() else None,
        "brand_voice": row["brand_voice"],
        "positioning": _json_loads(row["positioning_json"], {}),
        "glossary": _json_loads(row["glossary_json"], []),
        "forbidden_words": _json_loads(row["forbidden_words_json"], []),
        "required_terms": _json_loads(row["required_terms_json"], []),
        "claims_policy": _json_loads(row["claims_policy_json"], {}),
        "examples": _json_loads(row["examples_json"], None),
        "notes": row["notes"],
        "created_at": row["created_at"],
    }
    return data


def _build_brand_kb_context(kb_key: str | None, kb_version: int | None) -> str:
    if not kb_key or kb_version is None:
        return ""
    with db_conn() as conn:
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


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    return _html_response(AUTH_HTML)


@app.post("/register")
def register(body: RegisterInput) -> Any:
    username = body.username.strip()
    salt, pwd_hash = hash_password(body.password)
    requested_group_ids = sorted({gid for gid in body.join_group_ids if isinstance(gid, int) and gid > 0})
    if len(requested_group_ids) > 20:
        raise HTTPException(status_code=400, detail="最多可申请加入 20 个组")
    try:
        with db_conn() as conn:
            if requested_group_ids:
                placeholders = ",".join(["?"] * len(requested_group_ids))
                existing_rows = conn.execute(
                    f"SELECT id FROM groups WHERE id IN ({placeholders})",
                    tuple(requested_group_ids),
                ).fetchall()
                existing_ids = {row["id"] for row in existing_rows}
                missing_ids = [gid for gid in requested_group_ids if gid not in existing_ids]
                if missing_ids:
                    raise HTTPException(status_code=400, detail=f"组不存在: {missing_ids}")
            conn.execute(
                """
                INSERT INTO users (username, password_salt, password_hash, is_admin, is_active, created_at)
                VALUES (?, ?, ?, 0, 1, ?)
                """,
                (username, salt, pwd_hash, now_utc().isoformat()),
            )
            user_id = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]
            if requested_group_ids:
                created_at = now_utc().isoformat()
                conn.executemany(
                    """
                    INSERT INTO group_memberships (group_id, user_id, role, status, requested_by, created_at)
                    VALUES (?, ?, 'member', 'pending', ?, ?)
                    """,
                    [(gid, user_id, user_id, created_at) for gid in requested_group_ids],
                )
    except DB_INTEGRITY_ERRORS:
        raise HTTPException(status_code=400, detail="用户名已存在")

    token, exp, csrf_token = create_session(user_id)
    response = JSONResponse({"ok": True, "group_requests_created": len(requested_group_ids)})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        expires=exp.strftime("%a, %d %b %Y %H:%M:%S GMT"),
    )
    response.headers["X-CSRF-Token"] = csrf_token
    return response


@app.post("/login")
def login(body: LoginInput, request: Request) -> Any:
    username = body.username.strip()
    ip_address = _client_ip(request)
    if _is_login_rate_limited(username, ip_address):
        raise HTTPException(status_code=429, detail="Too many failed login attempts. Please retry later.")
    with db_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user or not verify_password(body.password, user["password_salt"], user["password_hash"]):
        _record_login_attempt(username, ip_address, False)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user["is_active"] == 0:
        _record_login_attempt(username, ip_address, False)
        raise HTTPException(status_code=403, detail="账号已被禁用")
    _record_login_attempt(username, ip_address, True)

    token, exp, csrf_token = create_session(user["id"])
    response = JSONResponse({"ok": True, "must_change_password": bool(user["must_change_password"])})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        expires=exp.strftime("%a, %d %b %Y %H:%M:%S GMT"),
    )
    response.headers["X-CSRF-Token"] = csrf_token
    return response


@app.post("/logout")
def logout(request: Request) -> Any:
    _validate_csrf_header(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with db_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, samesite="lax", secure=COOKIE_SECURE)
    return response


@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request) -> Any:
    if not current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return _html_response(APP_HTML)


@app.get("/kb", response_class=HTMLResponse)
def kb_page(request: Request) -> Any:
    if not current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return _html_response(KB_HTML)


@app.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request) -> Any:
    if not current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return _html_response(GROUPS_HTML)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request) -> Any:
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    if user["is_admin"] == 0:
        return RedirectResponse(url="/app", status_code=302)
    return _html_response(ADMIN_HTML)


@app.get("/api/me")
def api_me(request: Request) -> Any:
    user = must_login(request)
    return {
        "id": user["id"],
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
        "must_change_password": bool(user["must_change_password"]),
    }


@app.get("/api/csrf")
def get_csrf_token(request: Request) -> Any:
    must_login(request)
    session_row = _request_session_row(request)
    if not session_row:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"csrf_token": session_row["csrf_token"] or ""}


@app.post("/api/account/password")
def update_my_password(body: AccountPasswordInput, request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        row = conn.execute("SELECT id, password_salt, password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        if not verify_password(body.current_password, row["password_salt"], row["password_hash"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        new_salt, new_hash = hash_password(body.new_password)
        conn.execute(
            "UPDATE users SET password_salt = ?, password_hash = ?, must_change_password = 0 WHERE id = ?",
            (new_salt, new_hash, user["id"]),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND token != ?", (user["id"], request.cookies.get(SESSION_COOKIE, "")))
    return {"ok": True}


@app.get("/api/public/groups")
def list_public_groups() -> Any:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT g.id, g.name, g.group_type, g.created_by, g.created_at,
                   (
                       SELECT COUNT(*) FROM group_memberships x
                       WHERE x.group_id = g.id AND x.status = 'approved'
                   ) AS approved_member_count
            FROM groups g
                ORDER BY
                    CASE g.group_type
                        WHEN 'company' THEN 0
                        ELSE 1
                    END,
                    LOWER(g.name) ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/groups")
def list_groups(request: Request, group_type: str | None = None) -> Any:
    user = must_login(request)
    normalized_type = None
    if group_type:
        normalized_type = _normalize_group_type(group_type)
    with db_conn() as conn:
        if normalized_type:
            rows = conn.execute(
                """
                SELECT g.id, g.name, g.group_type, g.created_by, g.created_at,
                       gm.status AS my_status, gm.role AS my_role,
                       (
                           SELECT COUNT(*) FROM group_memberships x
                           WHERE x.group_id = g.id AND x.status = 'approved'
                       ) AS approved_member_count
                FROM groups g
                LEFT JOIN group_memberships gm ON gm.group_id = g.id AND gm.user_id = ?
                WHERE g.group_type = ?
                ORDER BY LOWER(g.name) ASC
                """,
                (user["id"], normalized_type),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT g.id, g.name, g.group_type, g.created_by, g.created_at,
                       gm.status AS my_status, gm.role AS my_role,
                       (
                           SELECT COUNT(*) FROM group_memberships x
                           WHERE x.group_id = g.id AND x.status = 'approved'
                       ) AS approved_member_count
                FROM groups g
                LEFT JOIN group_memberships gm ON gm.group_id = g.id AND gm.user_id = ?
                ORDER BY g.group_type ASC, LOWER(g.name) ASC
                """,
                (user["id"],),
            ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/groups/mine")
def list_my_groups(request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT g.id, g.name, g.group_type, g.created_by, g.created_at, gm.role, gm.status
            FROM group_memberships gm
            JOIN groups g ON g.id = gm.group_id
            WHERE gm.user_id = ? AND gm.status = 'approved'
            ORDER BY g.group_type ASC, LOWER(g.name) ASC
            """,
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/groups/invitations")
def list_my_invitations(request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT g.id AS group_id, g.name, g.group_type, gm.created_at, gm.requested_by, u.username AS invited_by
            FROM group_memberships gm
            JOIN groups g ON g.id = gm.group_id
            LEFT JOIN users u ON u.id = gm.requested_by
            WHERE gm.user_id = ? AND gm.status = 'invited'
            ORDER BY gm.created_at DESC
            """,
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/groups")
def create_group(body: GroupCreateInput, request: Request) -> Any:
    user = must_login(request)
    group_type = _normalize_group_type(body.group_type)
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Group name must be at least 2 characters")
    now = now_utc().isoformat()
    with db_conn() as conn:
        try:
            group_id = _insert_and_get_id(
                conn,
                "INSERT INTO groups (name, group_type, created_by, created_at) VALUES (?, ?, ?, ?)",
                (name[:80], group_type, user["id"], now),
            )
        except DB_INTEGRITY_ERRORS:
            raise HTTPException(status_code=400, detail="Group with same name and type already exists")
        conn.execute(
            """
            INSERT INTO group_memberships (group_id, user_id, role, status, requested_by, created_at, approved_at)
            VALUES (?, ?, 'admin', 'approved', ?, ?, ?)
            """,
            (group_id, user["id"], user["id"], now, now),
        )
    return {
        "id": group_id,
        "name": name[:80],
        "group_type": group_type,
        "created_by": user["id"],
        "created_at": now,
        "my_status": "approved",
        "my_role": "admin",
    }


@app.post("/api/groups/{group_id}/join")
def request_group_join(group_id: int, request: Request) -> Any:
    user = must_login(request)
    now = now_utc().isoformat()
    with db_conn() as conn:
        group_row = conn.execute("SELECT id FROM groups WHERE id = ?", (group_id,)).fetchone()
        if not group_row:
            raise HTTPException(status_code=404, detail="Group not found")
        existing = conn.execute(
            "SELECT status FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, user["id"]),
        ).fetchone()
        if existing:
            status = existing["status"]
            if status == "approved":
                return {"ok": True, "status": "approved"}
            if status in {"pending", "invited"}:
                return {"ok": True, "status": status}
            conn.execute(
                "UPDATE group_memberships SET status = 'pending', requested_by = ?, created_at = ?, approved_at = NULL WHERE group_id = ? AND user_id = ?",
                (user["id"], now, group_id, user["id"]),
            )
            return {"ok": True, "status": "pending"}
        conn.execute(
            """
            INSERT INTO group_memberships (group_id, user_id, role, status, requested_by, created_at)
            VALUES (?, ?, 'member', 'pending', ?, ?)
            """,
            (group_id, user["id"], user["id"], now),
        )
    return {"ok": True, "status": "pending"}


@app.post("/api/groups/{group_id}/leave")
def leave_group(group_id: int, request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        group_row = conn.execute(
            "SELECT id, name, group_type FROM groups WHERE id = ?",
            (group_id,),
        ).fetchone()
        if not group_row:
            raise HTTPException(status_code=404, detail="Group not found")
        membership = conn.execute(
            "SELECT role, status FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, user["id"]),
        ).fetchone()
        if not membership:
            raise HTTPException(status_code=404, detail="You are not a member of this group")
        if membership["role"] == "admin" and membership["status"] == "approved":
            other_admin_count = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM group_memberships
                WHERE group_id = ? AND status = 'approved' AND role = 'admin' AND user_id != ?
                """,
                (group_id, user["id"]),
            ).fetchone()["cnt"]
            if other_admin_count <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot leave group as the last admin. Transfer admin or delete the group.",
                )
        conn.execute(
            "DELETE FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, user["id"]),
        )
    return {"ok": True, "group_id": group_id}


@app.delete("/api/groups/{group_id}")
def delete_group(group_id: int, request: Request) -> Any:
    user = must_login(request)
    now = now_utc().isoformat()
    with db_conn() as conn:
        group_row = conn.execute(
            "SELECT id, name, group_type FROM groups WHERE id = ?",
            (group_id,),
        ).fetchone()
        if not group_row:
            raise HTTPException(status_code=404, detail="Group not found")
        if user["is_admin"] == 0:
            admin_row = conn.execute(
                """
                SELECT 1 FROM group_memberships
                WHERE group_id = ? AND user_id = ? AND status = 'approved' AND role = 'admin'
                """,
                (group_id, user["id"]),
            ).fetchone()
            if not admin_row:
                raise HTTPException(status_code=403, detail="Only group admin or system admin can delete this group")
        detached_conversations = conn.execute(
            "SELECT COUNT(*) AS cnt FROM conversations WHERE share_group_id = ?",
            (group_id,),
        ).fetchone()["cnt"]
        conn.execute(
            "UPDATE conversations SET visibility = 'private', share_group_id = NULL, updated_at = ? WHERE share_group_id = ?",
            (now, group_id),
        )
        detached_kbs = conn.execute(
            "SELECT COUNT(*) AS cnt FROM brand_kb_versions WHERE share_group_id = ?",
            (group_id,),
        ).fetchone()["cnt"]
        conn.execute(
            "UPDATE brand_kb_versions SET visibility = 'private', share_group_id = NULL WHERE share_group_id = ?",
            (group_id,),
        )
        conn.execute("DELETE FROM group_memberships WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    return {
        "ok": True,
        "group_id": group_id,
        "group_name": group_row["name"],
        "detached_conversations": detached_conversations,
        "detached_kb_versions": detached_kbs,
    }


@app.get("/api/groups/{group_id}/members")
def list_group_members(group_id: int, request: Request) -> Any:
    user = must_login(request)
    if not _is_group_member(user["id"], group_id, approved_only=True):
        raise HTTPException(status_code=403, detail="No access to this group")
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT gm.user_id, u.username, gm.role, gm.status, gm.created_at, gm.approved_at
            FROM group_memberships gm
            JOIN users u ON u.id = gm.user_id
            WHERE gm.group_id = ? AND gm.status = 'approved'
            ORDER BY CASE gm.role WHEN 'admin' THEN 0 ELSE 1 END, LOWER(u.username) ASC
            """,
            (group_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/groups/{group_id}/requests")
def list_group_requests(group_id: int, request: Request) -> Any:
    user = must_login(request)
    if not _is_group_admin(user["id"], group_id):
        raise HTTPException(status_code=403, detail="Admin only for this group")
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT gm.user_id, u.username, gm.status, gm.created_at, gm.requested_by, ru.username AS requested_by_username
            FROM group_memberships gm
            JOIN users u ON u.id = gm.user_id
            LEFT JOIN users ru ON ru.id = gm.requested_by
            WHERE gm.group_id = ? AND gm.status = 'pending'
            ORDER BY gm.created_at ASC
            """,
            (group_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/groups/{group_id}/requests/{member_user_id}/approve")
def approve_group_request(group_id: int, member_user_id: int, request: Request) -> Any:
    user = must_login(request)
    if not _is_group_admin(user["id"], group_id):
        raise HTTPException(status_code=403, detail="Admin only for this group")
    now = now_utc().isoformat()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT status FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, member_user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Membership request not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="Only pending join requests can be approved")
        conn.execute(
            "UPDATE group_memberships SET status = 'approved', approved_at = ? WHERE group_id = ? AND user_id = ?",
            (now, group_id, member_user_id),
        )
    return {"ok": True, "status": "approved"}


@app.post("/api/groups/{group_id}/requests/{member_user_id}/reject")
def reject_group_request(group_id: int, member_user_id: int, request: Request) -> Any:
    user = must_login(request)
    if not _is_group_admin(user["id"], group_id):
        raise HTTPException(status_code=403, detail="Admin only for this group")
    with db_conn() as conn:
        row = conn.execute(
            "SELECT status FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, member_user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Membership request not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="Only pending join requests can be rejected")
        conn.execute(
            "DELETE FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, member_user_id),
        )
    return {"ok": True}


@app.post("/api/groups/{group_id}/invite")
def invite_user_to_group(group_id: int, body: GroupInviteInput, request: Request) -> Any:
    user = must_login(request)
    if not _is_group_admin(user["id"], group_id):
        raise HTTPException(status_code=403, detail="Admin only for this group")
    username = body.username.strip()
    now = now_utc().isoformat()
    with db_conn() as conn:
        target = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        target_id = target["id"]
        existing = conn.execute(
            "SELECT status FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, target_id),
        ).fetchone()
        if existing and existing["status"] == "approved":
            raise HTTPException(status_code=400, detail="User is already a member")
        if existing:
            conn.execute(
                "UPDATE group_memberships SET status = 'invited', requested_by = ?, created_at = ?, approved_at = NULL WHERE group_id = ? AND user_id = ?",
                (user["id"], now, group_id, target_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO group_memberships (group_id, user_id, role, status, requested_by, created_at)
                VALUES (?, ?, 'member', 'invited', ?, ?)
                """,
                (group_id, target_id, user["id"], now),
            )
    return {"ok": True, "status": "invited", "username": username}


@app.post("/api/groups/{group_id}/invitations/accept")
def accept_group_invite(group_id: int, request: Request) -> Any:
    user = must_login(request)
    now = now_utc().isoformat()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT status FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, user["id"]),
        ).fetchone()
        if not row or row["status"] != "invited":
            raise HTTPException(status_code=404, detail="Invitation not found")
        conn.execute(
            "UPDATE group_memberships SET status = 'approved', approved_at = ? WHERE group_id = ? AND user_id = ?",
            (now, group_id, user["id"]),
        )
    return {"ok": True, "status": "approved"}


@app.post("/api/groups/{group_id}/invitations/reject")
def reject_group_invite(group_id: int, request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        row = conn.execute(
            "SELECT status FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, user["id"]),
        ).fetchone()
        if not row or row["status"] != "invited":
            raise HTTPException(status_code=404, detail="Invitation not found")
        conn.execute(
            "DELETE FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, user["id"]),
        )
    return {"ok": True}


@app.post("/api/groups/{group_id}/transfer-admin")
def transfer_group_admin(group_id: int, body: GroupTransferAdminInput, request: Request) -> Any:
    user = must_login(request)
    if not _is_group_admin(user["id"], group_id):
        raise HTTPException(status_code=403, detail="Admin only for this group")
    new_admin_id = body.new_admin_user_id
    with db_conn() as conn:
        target = conn.execute(
            "SELECT status FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, new_admin_id),
        ).fetchone()
        if not target or target["status"] != "approved":
            raise HTTPException(status_code=400, detail="Target user must be an approved member")
        conn.execute(
            "UPDATE group_memberships SET role = 'member' WHERE group_id = ? AND role = 'admin'",
            (group_id,),
        )
        conn.execute(
            "UPDATE group_memberships SET role = 'admin' WHERE group_id = ? AND user_id = ?",
            (group_id, new_admin_id),
        )
    return {"ok": True, "new_admin_user_id": new_admin_id}


@app.get("/api/kb/list")
def list_brand_kb(request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT b.kb_key, b.kb_name, b.version, b.owner_id, u.username AS owner_username, b.visibility,
                   b.share_group_id, g.name AS share_group_name, b.brand_voice, b.created_at,
                   b.positioning_json, b.glossary_json, b.forbidden_words_json, b.required_terms_json,
                   b.claims_policy_json, b.examples_json, b.notes
            FROM brand_kb_versions b
            LEFT JOIN users u ON u.id = b.owner_id
            LEFT JOIN groups g ON g.id = b.share_group_id
            LEFT JOIN group_memberships gm
              ON gm.group_id = b.share_group_id AND gm.user_id = ? AND gm.status = 'approved'
            JOIN (
                SELECT b2.kb_key, MAX(b2.version) AS latest_version
                FROM brand_kb_versions b2
                LEFT JOIN group_memberships gm2
                  ON gm2.group_id = b2.share_group_id AND gm2.user_id = ? AND gm2.status = 'approved'
                WHERE b2.owner_id = ?
                   OR (b2.visibility IN ('task', 'company') AND gm2.user_id IS NOT NULL)
                GROUP BY b2.kb_key
            ) latest
              ON latest.kb_key = b.kb_key AND latest.latest_version = b.version
            WHERE b.owner_id = ?
               OR (b.visibility IN ('task', 'company') AND gm.user_id IS NOT NULL)
            ORDER BY LOWER(b.kb_name) ASC, b.kb_key ASC
            """
            ,
            (user["id"], user["id"], user["id"], user["id"]),
        ).fetchall()
    return [_kb_row_to_dict(r) for r in rows]


@app.get("/api/kb/{kb_key}/versions")
def list_brand_kb_versions(kb_key: str, request: Request) -> Any:
    user = must_login(request)
    key = _normalize_kb_key(kb_key)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT b.kb_key, b.kb_name, b.version, b.owner_id, u.username AS owner_username,
                   b.visibility, b.share_group_id, g.name AS share_group_name, b.created_at,
                   b.brand_voice, b.positioning_json, b.glossary_json, b.forbidden_words_json,
                   b.required_terms_json, b.claims_policy_json, b.examples_json, b.notes
            FROM brand_kb_versions b
            LEFT JOIN users u ON u.id = b.owner_id
            LEFT JOIN groups g ON g.id = b.share_group_id
            LEFT JOIN group_memberships gm
              ON gm.group_id = b.share_group_id AND gm.user_id = ? AND gm.status = 'approved'
            WHERE b.kb_key = ?
              AND (
                    b.owner_id = ?
                    OR (b.visibility IN ('task', 'company') AND gm.user_id IS NOT NULL)
              )
            ORDER BY version DESC
            """,
            (user["id"], key, user["id"]),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    return [_kb_row_to_dict(r) for r in rows]


@app.get("/api/kb/{kb_key}")
def get_brand_kb(kb_key: str, request: Request, version: int | None = None) -> Any:
    user = must_login(request)
    key = _normalize_kb_key(kb_key)
    with db_conn() as conn:
        if version is None:
            row = conn.execute(
                """
                SELECT b.kb_key, b.kb_name, b.version, b.owner_id, u.username AS owner_username,
                       b.visibility, b.share_group_id, g.name AS share_group_name,
                       b.brand_voice, b.positioning_json, b.glossary_json,
                       b.forbidden_words_json, b.required_terms_json,
                       b.claims_policy_json, b.examples_json, b.notes, b.created_at
                FROM brand_kb_versions b
                LEFT JOIN users u ON u.id = b.owner_id
                LEFT JOIN groups g ON g.id = b.share_group_id
                LEFT JOIN group_memberships gm
                  ON gm.group_id = b.share_group_id AND gm.user_id = ? AND gm.status = 'approved'
                WHERE b.kb_key = ?
                  AND (
                        b.owner_id = ?
                        OR (b.visibility IN ('task', 'company') AND gm.user_id IS NOT NULL)
                  )
                ORDER BY version DESC
                LIMIT 1
                """,
                (user["id"], key, user["id"]),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT b.kb_key, b.kb_name, b.version, b.owner_id, u.username AS owner_username,
                       b.visibility, b.share_group_id, g.name AS share_group_name,
                       b.brand_voice, b.positioning_json, b.glossary_json,
                       b.forbidden_words_json, b.required_terms_json,
                       b.claims_policy_json, b.examples_json, b.notes, b.created_at
                FROM brand_kb_versions b
                LEFT JOIN users u ON u.id = b.owner_id
                LEFT JOIN groups g ON g.id = b.share_group_id
                LEFT JOIN group_memberships gm
                  ON gm.group_id = b.share_group_id AND gm.user_id = ? AND gm.status = 'approved'
                WHERE b.kb_key = ? AND b.version = ?
                  AND (
                        b.owner_id = ?
                        OR (b.visibility IN ('task', 'company') AND gm.user_id IS NOT NULL)
                  )
                """,
                (user["id"], key, version, user["id"]),
            ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    return _kb_row_to_dict(row)


@app.post("/api/kb")
def create_brand_kb(body: BrandKBInput, request: Request) -> Any:
    user = must_login(request)

    kb_key = _normalize_kb_key(body.kb_key)
    kb_name = (body.kb_name or kb_key).strip() or kb_key
    visibility, share_group_id = _validate_share_group_for_user(user["id"], body.visibility, body.share_group_id)
    brand_voice = body.brand_voice.strip() if body.brand_voice else None
    notes = body.notes.strip() if body.notes else None
    normalized = _normalize_kb_structured_fields_with_llm(
        positioning=body.positioning,
        glossary=body.glossary,
        forbidden_words=body.forbidden_words,
        required_terms=body.required_terms,
        claims_policy=body.claims_policy,
        examples=body.examples,
    )
    now = now_utc().isoformat()

    with db_conn() as conn:
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM brand_kb_versions WHERE kb_key = ?",
            (kb_key,),
        ).fetchone()["next_version"]
        conn.execute(
            """
            INSERT INTO brand_kb_versions (
                kb_key, kb_name, version, owner_id, visibility, share_group_id, brand_voice, positioning_json, glossary_json,
                forbidden_words_json, required_terms_json, claims_policy_json, examples_json, notes, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kb_key,
                kb_name[:120],
                version,
                user["id"],
                visibility,
                share_group_id,
                brand_voice,
                _json_dumps(normalized["positioning"]),
                _json_dumps(normalized["glossary"]),
                _json_dumps(normalized["forbidden_words"]),
                _json_dumps(normalized["required_terms"]),
                _json_dumps(normalized["claims_policy"]),
                _json_dumps(normalized["examples"]) if normalized["examples"] is not None else None,
                notes,
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT b.kb_key, b.kb_name, b.version, b.owner_id, u.username AS owner_username,
                   b.visibility, b.share_group_id, g.name AS share_group_name,
                   b.brand_voice, b.positioning_json, b.glossary_json,
                   b.forbidden_words_json, b.required_terms_json, b.claims_policy_json, b.examples_json, b.notes, b.created_at
            FROM brand_kb_versions b
            LEFT JOIN users u ON u.id = b.owner_id
            LEFT JOIN groups g ON g.id = b.share_group_id
            WHERE b.kb_key = ? AND b.version = ?
            """,
            (kb_key, version),
        ).fetchone()
    return _kb_row_to_dict(row)


@app.put("/api/kb/{kb_key}/{version}")
def update_brand_kb(kb_key: str, version: int, body: BrandKBUpdateInput, request: Request) -> Any:
    user = must_login(request)
    key = _normalize_kb_key(kb_key)
    kb_name = (body.kb_name or key).strip() or key
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT owner_id, visibility, share_group_id FROM brand_kb_versions WHERE kb_key = ? AND version = ?",
            (key, version),
        ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Knowledge Base version not found")
    if existing["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only owner can update this Knowledge Base version")

    visibility, share_group_id = _validate_share_group_for_user(
        user["id"],
        body.visibility or existing["visibility"] or "private",
        body.share_group_id if body.visibility is not None else existing["share_group_id"],
    )
    brand_voice = body.brand_voice.strip() if body.brand_voice else None
    notes = body.notes.strip() if body.notes else None
    normalized = _normalize_kb_structured_fields_with_llm(
        positioning=body.positioning,
        glossary=body.glossary,
        forbidden_words=body.forbidden_words,
        required_terms=body.required_terms,
        claims_policy=body.claims_policy,
        examples=body.examples,
    )

    with db_conn() as conn:
        conn.execute(
            """
            UPDATE brand_kb_versions
            SET kb_name = ?, visibility = ?, share_group_id = ?, brand_voice = ?, positioning_json = ?, glossary_json = ?,
                forbidden_words_json = ?, required_terms_json = ?, claims_policy_json = ?,
                examples_json = ?, notes = ?
            WHERE kb_key = ? AND version = ?
            """,
            (
                kb_name[:120],
                visibility,
                share_group_id,
                brand_voice,
                _json_dumps(normalized["positioning"]),
                _json_dumps(normalized["glossary"]),
                _json_dumps(normalized["forbidden_words"]),
                _json_dumps(normalized["required_terms"]),
                _json_dumps(normalized["claims_policy"]),
                _json_dumps(normalized["examples"]) if normalized["examples"] is not None else None,
                notes,
                key,
                version,
            ),
        )
        row = conn.execute(
            """
            SELECT b.kb_key, b.kb_name, b.version, b.owner_id, u.username AS owner_username,
                   b.visibility, b.share_group_id, g.name AS share_group_name,
                   b.brand_voice, b.positioning_json, b.glossary_json,
                   b.forbidden_words_json, b.required_terms_json, b.claims_policy_json, b.examples_json, b.notes, b.created_at
            FROM brand_kb_versions b
            LEFT JOIN users u ON u.id = b.owner_id
            LEFT JOIN groups g ON g.id = b.share_group_id
            WHERE b.kb_key = ? AND b.version = ?
            """,
            (key, version),
        ).fetchone()
    return _kb_row_to_dict(row)


@app.delete("/api/kb/{kb_key}/{version}")
def delete_brand_kb(kb_key: str, version: int, request: Request) -> Any:
    user = must_login(request)
    key = _normalize_kb_key(kb_key)
    with db_conn() as conn:
        exists = conn.execute(
            "SELECT id, owner_id FROM brand_kb_versions WHERE kb_key = ? AND version = ?",
            (key, version),
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Knowledge Base version not found")
        if exists["owner_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Only owner can delete this Knowledge Base version")
        in_use = conn.execute(
            "SELECT id FROM conversations WHERE kb_key = ? AND kb_version = ? LIMIT 1",
            (key, version),
        ).fetchone()
        if in_use:
            raise HTTPException(status_code=400, detail="Knowledge Base version is currently used by a conversation")
        conn.execute(
            "DELETE FROM brand_kb_versions WHERE kb_key = ? AND version = ?",
            (key, version),
        )
    return {"ok": True}


@app.get("/api/conversations")
def list_conversations(request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.user_id, c.title, c.model_id, c.task_mode, c.thinking_depth, c.visibility, c.share_group_id,
                   g.name AS share_group_name, u.username AS owner_username,
                   c.kb_key, c.kb_version, c.created_at, c.updated_at
            FROM conversations c
            LEFT JOIN users u ON u.id = c.user_id
            LEFT JOIN groups g ON g.id = c.share_group_id
            LEFT JOIN group_memberships gm
              ON gm.group_id = c.share_group_id AND gm.user_id = ? AND gm.status = 'approved'
            WHERE c.user_id = ?
               OR (c.visibility IN ('task', 'company') AND gm.user_id IS NOT NULL)
            ORDER BY c.updated_at DESC
            """,
            (user["id"], user["id"]),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/conversations")
def create_conversation(body: ConversationCreateInput, request: Request) -> Any:
    user = must_login(request)
    task_mode = _normalize_task_mode(body.task_mode)
    thinking_depth = _normalize_thinking_depth(body.thinking_depth)
    visibility, share_group_id = _validate_share_group_for_user(user["id"], body.visibility, body.share_group_id)
    lang = (body.ui_language or "").strip().lower()
    is_english = lang.startswith("en")
    if task_mode == "marketing":
        default_title = "New Marketing Task" if is_english else "新营销任务"
    else:
        default_title = "New Chat" if is_english else "新对话"
    title = (body.title or default_title).strip() or default_title
    now = now_utc().isoformat()
    model_id = DEFAULT_MODEL_ID
    with db_conn() as conn:
        conv_id = _insert_and_get_id(
            conn,
            """
            INSERT INTO conversations (
                user_id, title, model_id, task_mode, thinking_depth, visibility, share_group_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user["id"], title[:120], model_id, task_mode, thinking_depth, visibility, share_group_id, now, now),
        )
    return {
        "id": conv_id,
        "user_id": user["id"],
        "owner_username": user["username"],
        "title": title[:120],
        "model_id": model_id,
        "task_mode": task_mode,
        "thinking_depth": thinking_depth,
        "visibility": visibility,
        "share_group_id": share_group_id,
        "share_group_name": None,
        "kb_key": None,
        "kb_version": None,
        "created_at": now,
        "updated_at": now,
    }


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, request: Request) -> Any:
    user = must_login(request)
    conversation_owner_or_404(user["id"], conversation_id)
    with db_conn() as conn:
        doc_rows = conn.execute(
            "SELECT file_path FROM documents WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
        for doc in doc_rows:
            path = Path(doc["file_path"])
            if path.exists():
                path.unlink()
        conn.execute("DELETE FROM document_chunks WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversation_memories WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM orchestrator_runs WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM documents WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return {"ok": True}


@app.get("/api/models")
def list_models(request: Request) -> Any:
    must_login(request)
    models = allowed_models()
    return {
        "models": models,
        "default_model_id": DEFAULT_MODEL_ID if DEFAULT_MODEL_ID in models else models[0],
    }


@app.patch("/api/conversations/{conversation_id}/model")
def update_conversation_model(conversation_id: int, body: ConversationModelInput, request: Request) -> Any:
    user = must_login(request)
    conversation_owner_or_404(user["id"], conversation_id)
    model_id = body.model_id.strip()
    if model_id not in allowed_models():
        raise HTTPException(status_code=400, detail=f"Unsupported model_id: {model_id}")
    now = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute(
            "UPDATE conversations SET model_id = ?, updated_at = ? WHERE id = ?",
            (model_id, now, conversation_id),
        )
    return {"ok": True, "model_id": model_id, "updated_at": now}


@app.patch("/api/conversations/{conversation_id}/thinking-depth")
def update_conversation_thinking_depth(
    conversation_id: int, body: ConversationThinkingDepthInput, request: Request
) -> Any:
    user = must_login(request)
    conversation_owner_or_404(user["id"], conversation_id)
    thinking_depth = _normalize_thinking_depth(body.thinking_depth)
    now = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute(
            "UPDATE conversations SET thinking_depth = ?, updated_at = ? WHERE id = ?",
            (thinking_depth, now, conversation_id),
        )
    return {"ok": True, "thinking_depth": thinking_depth, "updated_at": now}


@app.patch("/api/conversations/{conversation_id}/title")
def update_conversation_title(conversation_id: int, body: ConversationTitleInput, request: Request) -> Any:
    user = must_login(request)
    conversation_owner_or_404(user["id"], conversation_id)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title cannot be empty")
    now = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title[:120], now, conversation_id),
        )
    return {"ok": True, "title": title[:120], "updated_at": now}


@app.patch("/api/conversations/{conversation_id}/mode")
def update_conversation_mode(conversation_id: int, body: ConversationModeInput, request: Request) -> Any:
    user = must_login(request)
    conversation_owner_or_404(user["id"], conversation_id)
    task_mode = _normalize_task_mode(body.task_mode)
    now = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute(
            "UPDATE conversations SET task_mode = ?, updated_at = ? WHERE id = ?",
            (task_mode, now, conversation_id),
        )
    return {"ok": True, "task_mode": task_mode, "updated_at": now}


@app.patch("/api/conversations/{conversation_id}/visibility")
def update_conversation_visibility(conversation_id: int, body: ConversationVisibilityInput, request: Request) -> Any:
    user = must_login(request)
    conversation_owner_or_404(user["id"], conversation_id)
    visibility, share_group_id = _validate_share_group_for_user(user["id"], body.visibility, body.share_group_id)
    now = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute(
            "UPDATE conversations SET visibility = ?, share_group_id = ?, updated_at = ? WHERE id = ?",
            (visibility, share_group_id, now, conversation_id),
        )
        group_name = None
        if share_group_id:
            row = conn.execute("SELECT name FROM groups WHERE id = ?", (share_group_id,)).fetchone()
            group_name = row["name"] if row else None
    return {
        "ok": True,
        "visibility": visibility,
        "share_group_id": share_group_id,
        "share_group_name": group_name,
        "updated_at": now,
    }


@app.patch("/api/conversations/{conversation_id}/kb")
def update_conversation_kb(conversation_id: int, body: ConversationKBInput, request: Request) -> Any:
    user = must_login(request)
    conversation_owner_or_404(user["id"], conversation_id)

    kb_key: str | None = None
    kb_version: int | None = None
    kb_name: str | None = None

    has_key = body.kb_key is not None and body.kb_key.strip() != ""
    has_version = body.kb_version is not None
    if has_key or has_version:
        if not has_key or not has_version:
            raise HTTPException(status_code=400, detail="Both Knowledge Base key and version are required")
        kb_key = _normalize_kb_key(body.kb_key or "")
        kb_version = body.kb_version
        with db_conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM brand_kb_versions WHERE kb_key = ? AND version = ?",
                (kb_key, kb_version),
            ).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Knowledge Base version not found")
            kb_row = conn.execute(
                """
                SELECT b.kb_name
                FROM brand_kb_versions b
                LEFT JOIN group_memberships gm
                  ON gm.group_id = b.share_group_id AND gm.user_id = ? AND gm.status = 'approved'
                WHERE b.kb_key = ? AND b.version = ?
                  AND (
                        b.owner_id = ?
                        OR (b.visibility IN ('task', 'company') AND gm.user_id IS NOT NULL)
                  )
                """,
                (user["id"], kb_key, kb_version, user["id"]),
            ).fetchone()
        if not kb_row:
            raise HTTPException(status_code=403, detail="No access to this Knowledge Base version")
        kb_name = kb_row["kb_name"]

    now = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute(
            "UPDATE conversations SET kb_key = ?, kb_version = ?, updated_at = ? WHERE id = ?",
            (kb_key, kb_version, now, conversation_id),
        )
    return {
        "ok": True,
        "kb_key": kb_key,
        "kb_name": kb_name,
        "kb_version": kb_version,
        "updated_at": now,
    }


@app.get("/api/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, request: Request) -> Any:
    user = must_login(request)
    conversation_visible_or_404(user["id"], conversation_id)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/conversations/{conversation_id}/orchestrator-runs")
def list_orchestrator_runs(conversation_id: int, request: Request) -> Any:
    user = must_login(request)
    conversation_visible_or_404(user["id"], conversation_id)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, request_message_id, response_message_id, model_id,
                   brief_json, plan_json, evaluation_json, created_at
            FROM orchestrator_runs
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT 30
            """,
            (conversation_id,),
        ).fetchall()
    data = []
    for row in rows:
        item = dict(row)
        item["brief"] = _json_loads(item.pop("brief_json"), {})
        item["plan"] = _json_loads(item.pop("plan_json"), {})
        item["evaluation"] = _json_loads(item.pop("evaluation_json"), {})
        data.append(item)
    return data


@app.get("/api/conversations/{conversation_id}/export")
def export_conversation(conversation_id: int, request: Request) -> Any:
    user = must_login(request)
    conversation = conversation_visible_or_404(user["id"], conversation_id)
    with db_conn() as conn:
        messages = conn.execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()

    mode = conversation["task_mode"] if "task_mode" in conversation.keys() else "chat"
    lines = [
        f"# {conversation['title']}",
        "",
        f"- Owner user id: {conversation['user_id']}",
        f"- Task mode: {mode}",
        f"- Model: {conversation['model_id']}",
        f"- Thinking depth: {conversation['thinking_depth'] if 'thinking_depth' in conversation.keys() else DEFAULT_THINKING_DEPTH}",
        f"- Visibility: {conversation['visibility'] or 'private'}",
        f"- Share group id: {conversation['share_group_id'] if conversation['share_group_id'] is not None else 'none'}",
        f"- Exported at: {now_utc().isoformat()}",
        "",
    ]
    for item in messages:
        role = "User" if item["role"] == "user" else "Assistant"
        lines.extend(
            [
                f"## {role}",
                item["content"],
                "",
            ]
        )

    return {
        "filename": f"conversation-{conversation_id}.md",
        "content": "\n".join(lines).strip() + "\n",
    }


@app.get("/api/conversations/{conversation_id}/documents")
def list_documents(conversation_id: int, request: Request) -> Any:
    user = must_login(request)
    conversation_visible_or_404(user["id"], conversation_id)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, content_type, created_at
            FROM documents
            WHERE conversation_id = ?
            ORDER BY id DESC
            """,
            (conversation_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/conversations/{conversation_id}/documents")
async def upload_document(conversation_id: int, request: Request, file: UploadFile = File(...)) -> Any:
    user = must_login(request)
    conversation_owner_or_404(user["id"], conversation_id)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(raw) > MAX_DOC_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_DOC_SIZE_BYTES} bytes)")

    text_content = _extract_text_from_upload(file.filename, raw)
    stored_name = f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    conversation_dir = UPLOAD_DIR / str(conversation_id)
    conversation_dir.mkdir(parents=True, exist_ok=True)
    file_path = conversation_dir / stored_name
    with file_path.open("wb") as f:
        f.write(raw)

    now = now_utc().isoformat()
    with db_conn() as conn:
        doc_id = _insert_and_get_id(
            conn,
            """
            INSERT INTO documents (conversation_id, filename, content_type, file_path, text_content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                Path(file.filename).name,
                file.content_type,
                str(file_path),
                text_content,
                now,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
    _index_document_chunks(doc_id, conversation_id, text_content)
    return {
        "id": doc_id,
        "filename": Path(file.filename).name,
        "content_type": file.content_type,
        "created_at": now,
    }


@app.delete("/api/conversations/{conversation_id}/documents/{document_id}")
def delete_document(conversation_id: int, document_id: int, request: Request) -> Any:
    user = must_login(request)
    conversation_owner_or_404(user["id"], conversation_id)
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, file_path FROM documents WHERE id = ? AND conversation_id = ?",
            (document_id, conversation_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found")
        conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        path = Path(row["file_path"])
        if path.exists():
            path.unlink()
    return {"ok": True}


def _ui_is_english(ui_language: str | None) -> bool:
    return str(ui_language or "").lower().startswith("en")


def _selected_channels_from_body(body: MessageInput) -> list[str]:
    selected: list[str] = []
    if isinstance(body.channels, list):
        for item in body.channels:
            value = str(item or "").strip().lower()
            if value and value not in selected:
                selected.append(value)
    single = str(body.channel or "").strip().lower()
    if single and single not in selected:
        selected.insert(0, single)
    return selected


def _build_message_context(conversation_id: int, conversation: sqlite3.Row, body: MessageInput, content: str) -> dict[str, Any]:
    channels = _selected_channels_from_body(body)
    primary_channel = channels[0] if channels else (str(body.channel or "").strip() or None)
    context: dict[str, Any] = {
        "channel": primary_channel,
        "channels": channels,
        "product": body.product,
        "audience": body.audience,
        "objective": body.objective,
        "brand_voice": body.brand_voice,
        "ui_language": body.ui_language,
        "output_sections": body.output_sections,
        "model_id": conversation["model_id"],
        "thinking_depth": conversation["thinking_depth"] if "thinking_depth" in conversation.keys() else DEFAULT_THINKING_DEPTH,
        "include_trace": True,
    }

    extra_parts = []
    if body.extra_requirements:
        extra_parts.append(body.extra_requirements)
    memory_context = _build_conversation_memory_context(conversation_id)
    if memory_context:
        extra_parts.append(memory_context)
    kb_context = _build_brand_kb_context(conversation["kb_key"], conversation["kb_version"])
    if kb_context:
        extra_parts.append(kb_context)
    doc_context = _build_document_context(conversation_id, query_text=content)
    if doc_context:
        extra_parts.append(doc_context)
    context["extra_requirements"] = "\n\n".join(extra_parts) if extra_parts else None
    return context


def _run_agent_with_model_fallback(
    *,
    content: str,
    context: dict[str, Any],
    original_model_id: str,
    ui_language: str | None,
    on_delta: Any = None,
) -> dict[str, Any]:
    is_en = _ui_is_english(ui_language)
    model_fallback_used = False
    use_stream = on_delta is not None and callable(invoke_stream)
    if use_stream:
        agent_output = invoke_stream({"prompt": content, "tool_args": context}, on_delta=on_delta)
    else:
        agent_output = invoke({"prompt": content, "tool_args": context})
    assistant_text = ""

    if "error" in agent_output and original_model_id != DEFAULT_MODEL_ID:
        fallback_context = dict(context)
        fallback_context["model_id"] = DEFAULT_MODEL_ID
        fallback_output = invoke({"prompt": content, "tool_args": fallback_context})
        if "error" not in fallback_output:
            model_fallback_used = True
            agent_output = fallback_output
            if is_en:
                assistant_text = (
                    f"[System] Model `{original_model_id}` failed, automatically fell back to `{DEFAULT_MODEL_ID}`.\n\n"
                    f"{fallback_output.get('result', '')}"
                )
            else:
                assistant_text = (
                    f"[系统提示] 模型 `{original_model_id}` 调用失败，已自动回退到 `{DEFAULT_MODEL_ID}`。\n\n"
                    f"{fallback_output.get('result', '')}"
                )
        else:
            agent_output = fallback_output

    if "error" in agent_output and not model_fallback_used:
        error_block = agent_output.get("error", {}) or {}
        message = error_block.get("message", "unknown")
        details = error_block.get("details")
        assistant_text = f"[Error] {message}" if is_en else f"[错误] {message}"
        if details:
            assistant_text += f"\n{details}"
    elif not model_fallback_used:
        assistant_text = agent_output.get("result", "")

    return {
        "assistant_text": assistant_text,
        "agent_output": agent_output,
        "model_fallback_used": model_fallback_used,
        "resolved_model_id": DEFAULT_MODEL_ID if model_fallback_used else original_model_id,
    }


def _persist_assistant_message(
    *,
    conversation: sqlite3.Row,
    conversation_id: int,
    user_message_id: int,
    user_content: str,
    assistant_text: str,
    agent_output: dict[str, Any],
    resolved_model_id: str,
) -> dict[str, Any]:
    now2 = now_utc().isoformat()
    with db_conn() as conn:
        assistant_message_id = _insert_and_get_id(
            conn,
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
            (conversation_id, assistant_text, now2),
        )

        orchestrator = agent_output.get("orchestrator") if isinstance(agent_output, dict) else None
        if isinstance(orchestrator, dict):
            conn.execute(
                """
                INSERT INTO orchestrator_runs (
                    conversation_id, request_message_id, response_message_id, model_id,
                    brief_json, plan_json, evaluation_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    user_message_id,
                    assistant_message_id,
                    resolved_model_id,
                    _json_dumps(orchestrator.get("brief")),
                    _json_dumps(orchestrator.get("plan")),
                    _json_dumps(orchestrator.get("evaluation")),
                    now2,
                ),
            )

        if _is_default_conversation_title(conversation["title"]):
            conn.execute(
                "UPDATE conversations SET title = ?, model_id = ?, updated_at = ? WHERE id = ?",
                (
                    user_content[:30],
                    resolved_model_id,
                    now2,
                    conversation_id,
                ),
            )
        else:
            conn.execute(
                "UPDATE conversations SET model_id = ?, updated_at = ? WHERE id = ?",
                (
                    resolved_model_id,
                    now2,
                    conversation_id,
                ),
            )

    _refresh_conversation_summary(conversation_id)
    return {"assistant_created_at": now2}


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _chunk_text(text: str, *, size: int = 96) -> list[str]:
    clean = str(text or "")
    if not clean:
        return []
    return [clean[i : i + size] for i in range(0, len(clean), size)]


def _html_response(content: str) -> HTMLResponse:
    response = HTMLResponse(content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.post("/api/conversations/{conversation_id}/messages")
def send_message(conversation_id: int, body: MessageInput, request: Request) -> Any:
    user = must_login(request)
    conversation = conversation_visible_or_404(user["id"], conversation_id)

    content = body.content.strip()
    if not content:
        detail = "Message cannot be empty" if _ui_is_english(body.ui_language) else "消息不能为空"
        raise HTTPException(status_code=400, detail=detail)

    now = now_utc().isoformat()
    with db_conn() as conn:
        user_message_id = _insert_and_get_id(
            conn,
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (conversation_id, content, now),
        )

    context = _build_message_context(conversation_id, conversation, body, content)
    runtime_result = _run_agent_with_model_fallback(
        content=content,
        context=context,
        original_model_id=conversation["model_id"],
        ui_language=body.ui_language,
    )
    persist_result = _persist_assistant_message(
        conversation=conversation,
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        user_content=content,
        assistant_text=runtime_result["assistant_text"],
        agent_output=runtime_result["agent_output"],
        resolved_model_id=runtime_result["resolved_model_id"],
    )

    return {
        "assistant_message": {
            "role": "assistant",
            "content": runtime_result["assistant_text"],
            "created_at": persist_result["assistant_created_at"],
        }
    }


@app.post("/api/conversations/{conversation_id}/messages/stream")
def send_message_stream(conversation_id: int, body: MessageInput, request: Request) -> Any:
    user = must_login(request)
    conversation = conversation_visible_or_404(user["id"], conversation_id)

    content = body.content.strip()
    if not content:
        detail = "Message cannot be empty" if _ui_is_english(body.ui_language) else "消息不能为空"
        raise HTTPException(status_code=400, detail=detail)

    now = now_utc().isoformat()
    with db_conn() as conn:
        user_message_id = _insert_and_get_id(
            conn,
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (conversation_id, content, now),
        )

    context = _build_message_context(conversation_id, conversation, body, content)
    result_queue: Queue[tuple[str, Any]] = Queue()

    def emit_delta(text: str) -> None:
        if text:
            result_queue.put(("delta", text))

    def worker() -> None:
        try:
            runtime_result = _run_agent_with_model_fallback(
                content=content,
                context=context,
                original_model_id=conversation["model_id"],
                ui_language=body.ui_language,
                on_delta=emit_delta,
            )
            result_queue.put(("ok", runtime_result))
        except Exception as exc:  # pragma: no cover - fallback protection for stream path
            result_queue.put(("err", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def stream() -> Iterator[str]:
        yield _sse_event("status", {"state": "processing"})

        runtime_result: dict[str, Any]
        while True:
            try:
                status, payload = result_queue.get(timeout=0.35)
                if status == "delta":
                    yield _sse_event("delta", {"text": str(payload)})
                    continue
                if status == "ok":
                    runtime_result = payload
                else:
                    error_prefix = "[Error]" if _ui_is_english(body.ui_language) else "[错误]"
                    runtime_result = {
                        "assistant_text": f"{error_prefix} {type(payload).__name__}: {payload}",
                        "agent_output": {},
                        "resolved_model_id": conversation["model_id"],
                    }
                break
            except Empty:
                yield ": keep-alive\n\n"

        persist_result = _persist_assistant_message(
            conversation=conversation,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            user_content=content,
            assistant_text=runtime_result["assistant_text"],
            agent_output=runtime_result["agent_output"],
            resolved_model_id=runtime_result["resolved_model_id"],
        )

        yield _sse_event(
            "done",
            {
                "assistant_message": {
                    "role": "assistant",
                    "content": runtime_result["assistant_text"],
                    "created_at": persist_result["assistant_created_at"],
                }
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/admin/users")
def admin_list_users(request: Request) -> Any:
    must_admin(request)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, username, is_admin, is_active, created_at
            FROM users
            ORDER BY id ASC
            """
        ).fetchall()
    return [
        {
            "id": r["id"],
            "username": r["username"],
            "is_admin": bool(r["is_admin"]),
            "is_active": bool(r["is_active"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.post("/api/admin/users")
def admin_create_user(body: AdminCreateUserInput, request: Request) -> Any:
    must_admin(request)
    salt, pwd_hash = hash_password(body.password)

    try:
        with db_conn() as conn:
            user_id = _insert_and_get_id(
                conn,
                """
                INSERT INTO users (username, password_salt, password_hash, is_admin, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    body.username.strip(),
                    salt,
                    pwd_hash,
                    1 if body.is_admin else 0,
                    now_utc().isoformat(),
                ),
            )
    except DB_INTEGRITY_ERRORS:
        raise HTTPException(status_code=400, detail="用户名已存在")

    return {"id": user_id, "ok": True}


@app.post("/api/admin/users/{user_id}/status")
def admin_set_status(user_id: int, body: AdminStatusInput, request: Request) -> Any:
    admin_user = must_admin(request)
    if user_id == admin_user["id"] and not body.is_active:
        raise HTTPException(status_code=400, detail="不能禁用当前管理员")

    with db_conn() as conn:
        exists = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if body.is_active else 0, user_id))
        if not body.is_active:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    return {"ok": True}


@app.post("/api/admin/users/{user_id}/password")
def admin_reset_password(user_id: int, body: AdminResetPasswordInput, request: Request) -> Any:
    must_admin(request)
    salt, pwd_hash = hash_password(body.new_password)
    with db_conn() as conn:
        exists = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="用户不存在")

        conn.execute(
            "UPDATE users SET password_salt = ?, password_hash = ? WHERE id = ?",
            (salt, pwd_hash, user_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    return {"ok": True}
