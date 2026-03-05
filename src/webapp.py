import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from model.load import DEFAULT_MODEL_ID


def _load_invoke() -> Any:
    try:
        from main import invoke as runtime_invoke

        if callable(runtime_invoke):
            return runtime_invoke
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
    return runtime_invoke


invoke = _load_invoke()


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
if os.getenv("AWS_LAMBDA_FUNCTION_NAME") and not os.getenv("NOVARED_DATA_DIR"):
    DATA_DIR = Path("/tmp/novaRed")
else:
    DATA_DIR = Path(os.getenv("NOVARED_DATA_DIR", str(DEFAULT_DATA_DIR)))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "webapp.db"
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
    "us.amazon.nova-micro-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.anthropic.claude-sonnet-4-6",
]
TASK_MODES = {"chat", "marketing"}
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


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, password_hash: str) -> bool:
    _salt, candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, password_hash)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with db_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                csrf_token TEXT,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                model_id TEXT NOT NULL DEFAULT 'us.amazon.nova-micro-v1:0',
                task_mode TEXT NOT NULL DEFAULT 'chat',
                visibility TEXT NOT NULL DEFAULT 'private',
                share_group_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                content_type TEXT,
                file_path TEXT NOT NULL,
                text_content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                conversation_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS brand_kb_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_key TEXT NOT NULL,
                kb_name TEXT NOT NULL,
                version INTEGER NOT NULL,
                owner_id INTEGER,
                visibility TEXT NOT NULL DEFAULT 'private',
                share_group_id INTEGER,
                brand_voice TEXT,
                positioning_json TEXT NOT NULL DEFAULT '{}',
                glossary_json TEXT NOT NULL DEFAULT '[]',
                forbidden_words_json TEXT NOT NULL DEFAULT '[]',
                required_terms_json TEXT NOT NULL DEFAULT '[]',
                claims_policy_json TEXT NOT NULL DEFAULT '{}',
                examples_json TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(kb_key, version)
            );

            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                group_type TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(name, group_type),
                FOREIGN KEY(created_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS group_memberships (
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                status TEXT NOT NULL DEFAULT 'pending',
                requested_by INTEGER,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                PRIMARY KEY(group_id, user_id),
                FOREIGN KEY(group_id) REFERENCES groups(id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(requested_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS conversation_memories (
                conversation_id INTEGER PRIMARY KEY,
                summary TEXT NOT NULL,
                source_message_id INTEGER,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS orchestrator_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                request_message_id INTEGER,
                response_message_id INTEGER,
                model_id TEXT NOT NULL,
                brief_json TEXT,
                plan_json TEXT,
                evaluation_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                ip_address TEXT,
                success INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                conversation_id INTEGER,
                title TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                traffic_allocation_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(owner_user_id) REFERENCES users(id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS experiment_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL,
                variant_key TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(experiment_id) REFERENCES experiments(id),
                UNIQUE(experiment_id, variant_key)
            );
            """
        )

        conversation_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "model_id" not in conversation_cols:
            conn.execute(
                f"ALTER TABLE conversations ADD COLUMN model_id TEXT NOT NULL DEFAULT '{DEFAULT_MODEL_ID}'"
            )
        if "kb_key" not in conversation_cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN kb_key TEXT")
        if "kb_version" not in conversation_cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN kb_version INTEGER")
        if "task_mode" not in conversation_cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN task_mode TEXT NOT NULL DEFAULT 'chat'")
        if "visibility" not in conversation_cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'")
        if "share_group_id" not in conversation_cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN share_group_id INTEGER")

        user_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "must_change_password" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")

        session_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "csrf_token" not in session_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN csrf_token TEXT")

        kb_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(brand_kb_versions)").fetchall()
        }
        if "owner_id" not in kb_cols:
            conn.execute("ALTER TABLE brand_kb_versions ADD COLUMN owner_id INTEGER")
            conn.execute("UPDATE brand_kb_versions SET owner_id = 1 WHERE owner_id IS NULL")
        if "visibility" not in kb_cols:
            conn.execute("ALTER TABLE brand_kb_versions ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'")
        if "share_group_id" not in kb_cols:
            conn.execute("ALTER TABLE brand_kb_versions ADD COLUMN share_group_id INTEGER")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_conversation_id ON documents(conversation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks_conversation_id ON document_chunks(conversation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_username_time ON login_attempts(username, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_time ON login_attempts(ip_address, created_at)")

        admin_exists = conn.execute(
            "SELECT id, password_salt, password_hash FROM users WHERE username = ?", (DEFAULT_ADMIN_USER,)
        ).fetchone()
        if not admin_exists:
            salt, pwd_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
            conn.execute(
                """
                INSERT INTO users (username, password_salt, password_hash, is_admin, is_active, must_change_password, created_at)
                VALUES (?, ?, ?, 1, 1, ?, ?)
                """,
                (
                    DEFAULT_ADMIN_USER,
                    salt,
                    pwd_hash,
                    1 if (ENFORCE_DEFAULT_ADMIN_PASSWORD_CHANGE and DEFAULT_ADMIN_PASSWORD == "admin123456") else 0,
                    now_utc().isoformat(),
                ),
            )
        elif verify_password(DEFAULT_ADMIN_PASSWORD, admin_exists["password_salt"], admin_exists["password_hash"]):
            conn.execute(
                "UPDATE users SET must_change_password = ? WHERE id = ?",
                (1 if ENFORCE_DEFAULT_ADMIN_PASSWORD_CHANGE else 0, admin_exists["id"]),
            )
        elif not ENFORCE_DEFAULT_ADMIN_PASSWORD_CHANGE:
            conn.execute(
                "UPDATE users SET must_change_password = 0 WHERE id = ?",
                (admin_exists["id"],),
            )


app = FastAPI(title="Marketing Copilot Web Chat")


@app.on_event("startup")
def startup() -> None:
    init_db()


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
        conn.execute(
            """
            INSERT INTO conversation_memories (conversation_id, summary, source_message_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                summary = excluded.summary,
                source_message_id = excluded.source_message_id,
                updated_at = excluded.updated_at
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
Convert this Brand KB draft into a strict JSON object.

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
        f"- KB: {row['kb_name']} (key={row['kb_key']}, version={row['version']})",
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


class RegisterInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    join_group_ids: list[int] = Field(default_factory=list)


class LoginInput(BaseModel):
    username: str
    password: str


class ConversationCreateInput(BaseModel):
    title: str | None = None
    task_mode: str | None = None
    visibility: str | None = "private"
    share_group_id: int | None = None


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    ui_language: str | None = None
    channel: str | None = None
    product: str | None = None
    audience: str | None = None
    objective: str | None = None
    brand_voice: str | None = None
    extra_requirements: str | None = None


class AdminCreateUserInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False


class AdminResetPasswordInput(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class AccountPasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class BrandKBInput(BaseModel):
    kb_key: str = Field(min_length=1, max_length=80)
    kb_name: str | None = Field(default=None, max_length=120)
    brand_voice: str | None = Field(default=None, max_length=500)
    visibility: str | None = "private"
    share_group_id: int | None = None
    positioning: Any = Field(default_factory=dict)
    glossary: Any = Field(default_factory=list)
    forbidden_words: Any = Field(default_factory=list)
    required_terms: Any = Field(default_factory=list)
    claims_policy: Any = Field(default_factory=dict)
    examples: Any | None = None
    notes: str | None = Field(default=None, max_length=4000)


class ConversationKBInput(BaseModel):
    kb_key: str | None = Field(default=None, max_length=80)
    kb_version: int | None = Field(default=None, ge=1)


class ConversationModeInput(BaseModel):
    task_mode: str


class ConversationModelInput(BaseModel):
    model_id: str = Field(min_length=3, max_length=128)


class ConversationVisibilityInput(BaseModel):
    visibility: str
    share_group_id: int | None = None


class ConversationTitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class GroupCreateInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    group_type: str


class GroupInviteInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)


class GroupTransferAdminInput(BaseModel):
    new_admin_user_id: int


class ExperimentCreateInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    hypothesis: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None
    traffic_allocation: Any = Field(default_factory=dict)


class ExperimentVariantInput(BaseModel):
    variant_key: str = Field(min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=10000)


class ExperimentStatusInput(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    result: Any = Field(default_factory=dict)


class BrandKBUpdateInput(BaseModel):
    kb_name: str | None = Field(default=None, max_length=120)
    brand_voice: str | None = Field(default=None, max_length=500)
    visibility: str | None = None
    share_group_id: int | None = None
    positioning: Any = Field(default_factory=dict)
    glossary: Any = Field(default_factory=list)
    forbidden_words: Any = Field(default_factory=list)
    required_terms: Any = Field(default_factory=list)
    claims_policy: Any = Field(default_factory=dict)
    examples: Any | None = None
    notes: str | None = Field(default=None, max_length=4000)


AUTH_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Marketing Copilot</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;700;800&family=IBM+Plex+Mono:wght@500&display=swap');
    :root { --bg:#ecf3ff; --card:#ffffff; --line:#d9deea; --txt:#101828; --muted:#5a6472; --accent:#1565d8; --accent-2:#11a089; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Manrope","Segoe UI",sans-serif; background:radial-gradient(1200px 540px at 10% -10%,#d7e8ff 0%,transparent 56%),radial-gradient(980px 520px at 92% 0%,#d6f3e9 0%,transparent 58%),linear-gradient(160deg,#eef4ff,#f8fbff 45%,#edf8f3); color:var(--txt); min-height:100vh; display:grid; place-items:center; }
    .lang { position:fixed; top:14px; right:14px; display:flex; gap:6px; }
    .lang button { width:auto; padding:7px 10px; border:1px solid var(--line); background:#fff; color:var(--txt); border-radius:999px; transition:.2s ease; }
    .lang button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
    .wrap { width:min(940px,94vw); display:grid; grid-template-columns:1fr 1fr; gap:16px; }
    .card { background:linear-gradient(180deg,#ffffff,#fdfefe); border:1px solid var(--line); border-radius:16px; padding:22px; box-shadow:0 20px 45px rgba(18,30,58,.10); backdrop-filter: blur(2px); }
    h2 { margin:0 0 10px; font-weight:800; letter-spacing:.1px; }
    p { color:var(--muted); margin:0 0 16px; font-size:14px; }
    input, select { width:100%; padding:11px; border:1px solid var(--line); border-radius:12px; margin-bottom:10px; transition:.2s ease; background:#fff; font-family:inherit; }
    input:focus, select:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(21,101,216,.15); }
    select[multiple] { min-height:92px; padding:8px; }
    button { width:100%; border:0; border-radius:12px; padding:11px; background:linear-gradient(120deg,var(--accent),#0f8ad7); color:#fff; font-weight:700; cursor:pointer; transition:.2s ease; }
    button:hover { transform:translateY(-1px); box-shadow:0 10px 22px rgba(21,101,216,.28); }
    .group-block { border:1px solid var(--line); background:#f7fbff; border-radius:12px; padding:10px; margin-bottom:10px; }
    .group-head { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px; }
    .group-label { font-size:12px; color:var(--muted); margin:0 0 5px; }
    .group-help { font-size:12px; color:var(--muted); margin:0; }
    .inline-btn {
      width:auto;
      border:1px solid var(--line);
      border-radius:10px;
      padding:7px 10px;
      background:#fff;
      color:var(--txt);
      font-weight:700;
      box-shadow:none;
    }
    .inline-btn:hover { transform:none; box-shadow:none; border-color:#bfc9db; }
    .err { color:#d1242f; font-size:13px; min-height:20px; }
    .note { margin-top:8px; font-size:12px; color:var(--muted); font-family:"IBM Plex Mono",ui-monospace,monospace; }
    @media (max-width: 760px) { .wrap { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="lang">
    <button id="lang-zh" onclick="setLang('zh')">中文</button>
    <button id="lang-en" onclick="setLang('en')">EN</button>
  </div>
  <div class="wrap">
    <div class="card">
      <h2 data-i18n="login_title">登录</h2>
      <p data-i18n="login_subtitle">进入你的营销 Agent 工作台。</p>
      <input id="login-username" data-i18n-placeholder="username" placeholder="用户名" />
      <input id="login-password" data-i18n-placeholder="password" placeholder="密码" type="password" />
      <button onclick="login()" data-i18n="login_btn">登录</button>
      <div id="login-err" class="err"></div>
      <div class="note" data-i18n="default_admin">首次可用默认管理员账号：admin / admin123456</div>
    </div>
    <div class="card">
      <h2 data-i18n="register_title">注册</h2>
      <p data-i18n="register_subtitle">创建个人账号后可保存自己的对话记录，并可申请加入组。</p>
      <input id="reg-username" data-i18n-placeholder="reg_username" placeholder="用户名（3-32 位）" />
      <input id="reg-password" data-i18n-placeholder="reg_password" placeholder="密码（至少 8 位）" type="password" />
      <div class="group-block">
        <div class="group-head">
          <div class="group-label" data-i18n="register_group_optional">可选：注册时申请加入组</div>
          <button type="button" class="inline-btn" onclick="loadPublicGroups()" data-i18n="refresh_groups">刷新组列表</button>
        </div>
        <div class="group-label" data-i18n="task_groups_label">任务小组（可多选）</div>
        <select id="reg-task-groups" multiple></select>
        <div class="group-label" data-i18n="company_groups_label">公司组（可多选）</div>
        <select id="reg-company-groups" multiple></select>
        <div class="group-help" data-i18n="register_group_hint">提交后会创建入组申请，需组管理员批准。</div>
      </div>
      <button onclick="registerUser()" data-i18n="register_btn">创建账号</button>
      <div id="reg-err" class="err"></div>
    </div>
  </div>

<script>
const I18N = {
  zh: {
    page_title: 'Marketing Copilot 登录',
    login_title: '登录',
    login_subtitle: '进入你的 Marketing Copilot 工作台。',
    login_btn: '登录',
    register_title: '注册',
    register_subtitle: '创建个人账号后可保存自己的对话记录，并可申请加入组。',
    register_btn: '创建账号',
    register_group_optional: '可选：注册时申请加入组',
    task_groups_label: '任务小组（可多选）',
    company_groups_label: '公司组（可多选）',
    refresh_groups: '刷新组列表',
    register_group_hint: '提交后会创建入组申请，需组管理员批准。',
    no_task_groups: '暂无可选任务组',
    no_company_groups: '暂无可选公司组',
    group_load_failed: '组列表加载失败',
    username: '用户名',
    password: '密码',
    reg_username: '用户名（3-32 位）',
    reg_password: '密码（至少 8 位）',
    default_admin: '首次可用默认管理员账号：admin / admin123456',
    login_failed: '登录失败',
    register_failed: '注册失败'
  },
  en: {
    page_title: 'Marketing Copilot Sign In',
    login_title: 'Sign In',
    login_subtitle: 'Access your marketing agent workspace.',
    login_btn: 'Sign In',
    register_title: 'Register',
    register_subtitle: 'Create your account, keep your own chat history, and request group access.',
    register_btn: 'Create Account',
    register_group_optional: 'Optional: Request group access during registration',
    task_groups_label: 'Task Groups (multi-select)',
    company_groups_label: 'Company Groups (multi-select)',
    refresh_groups: 'Refresh Groups',
    register_group_hint: 'Registration will create join requests that require group admin approval.',
    no_task_groups: 'No task groups available',
    no_company_groups: 'No company groups available',
    group_load_failed: 'Failed to load groups',
    username: 'Username',
    password: 'Password',
    reg_username: 'Username (3-32 chars)',
    reg_password: 'Password (at least 8 chars)',
    default_admin: 'Default admin account: admin / admin123456',
    login_failed: 'Login failed',
    register_failed: 'Registration failed'
  }
};

let currentLang = localStorage.getItem('nova_lang') || 'zh';
let csrfToken = '';
let publicGroups = [];

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || key;
}

function setGroupSelectOptions(select, groups, emptyKey) {
  const selectedValues = new Set([...select.selectedOptions].map((opt) => opt.value));
  select.innerHTML = '';
  if (!groups.length) {
    const empty = document.createElement('option');
    empty.value = '';
    empty.disabled = true;
    empty.textContent = t(emptyKey);
    select.appendChild(empty);
    return;
  }
  for (const group of groups) {
    const option = document.createElement('option');
    option.value = String(group.id);
    option.textContent = `${group.name} (#${group.id})`;
    if (selectedValues.has(option.value)) option.selected = true;
    select.appendChild(option);
  }
}

function renderPublicGroups() {
  const taskSelect = document.getElementById('reg-task-groups');
  const companySelect = document.getElementById('reg-company-groups');
  if (!taskSelect || !companySelect) return;
  const taskGroups = publicGroups.filter((g) => g.group_type === 'task');
  const companyGroups = publicGroups.filter((g) => g.group_type === 'company');
  setGroupSelectOptions(taskSelect, taskGroups, 'no_task_groups');
  setGroupSelectOptions(companySelect, companyGroups, 'no_company_groups');
}

function applyI18n() {
  document.title = t('page_title');
  document.documentElement.lang = currentLang === 'en' ? 'en' : 'zh-CN';
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.getElementById('lang-zh').classList.toggle('active', currentLang === 'zh');
  document.getElementById('lang-en').classList.toggle('active', currentLang === 'en');
  renderPublicGroups();
}

function setLang(lang) {
  currentLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('nova_lang', currentLang);
  applyI18n();
}

async function login() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const err = document.getElementById('login-err');
  err.textContent = '';
  const res = await fetch('/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username,password})});
  const data = await res.json();
  if (!res.ok) { err.textContent = data.detail || t('login_failed'); return; }
  location.href = '/app';
}

function selectedGroupIds(selectId) {
  const select = document.getElementById(selectId);
  if (!select) return [];
  return [...select.selectedOptions]
    .map((opt) => Number(opt.value))
    .filter((id) => Number.isInteger(id) && id > 0);
}

async function loadPublicGroups() {
  const err = document.getElementById('reg-err');
  try {
    const res = await fetch('/api/public/groups');
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || t('group_load_failed'));
    publicGroups = Array.isArray(data) ? data : [];
    renderPublicGroups();
  } catch (_) {
    publicGroups = [];
    renderPublicGroups();
    if (err) err.textContent = t('group_load_failed');
  }
}

async function registerUser() {
  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value;
  const join_group_ids = Array.from(new Set([
    ...selectedGroupIds('reg-task-groups'),
    ...selectedGroupIds('reg-company-groups'),
  ]));
  const err = document.getElementById('reg-err');
  err.textContent = '';
  const res = await fetch('/register', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username, password, join_group_ids}),
  });
  const data = await res.json();
  if (!res.ok) { err.textContent = data.detail || t('register_failed'); return; }
  location.href = '/app';
}
applyI18n();
loadPublicGroups();
</script>
</body>
</html>
"""


APP_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Marketing Copilot</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap');
    :root {
      --bg:#edf4ff;
      --bg-soft:#f4fbf7;
      --pane:rgba(255,255,255,.86);
      --pane-solid:#ffffff;
      --line:#d6dfec;
      --line-strong:#bfcee3;
      --txt:#0f1b2d;
      --muted:#53647c;
      --accent:#0a67d3;
      --accent-2:#0ea979;
      --danger:#cf3f3f;
      --bot:#f4f8ff;
      --user:#e9f8ef;
      --shadow:0 18px 36px rgba(16,32,62,.12);
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      font-family:"IBM Plex Sans","Segoe UI",sans-serif;
      background:
        radial-gradient(920px 520px at 0% -10%,#d8e7ff 0%,transparent 58%),
        radial-gradient(980px 560px at 106% -16%,#d7f3e8 0%,transparent 62%),
        linear-gradient(160deg,var(--bg),var(--bg-soft));
      color:var(--txt);
      height:100vh;
      overflow:hidden;
    }
    .app-shell {
      height:100vh;
      display:grid;
      grid-template-rows:auto 1fr;
      gap:8px;
      padding:8px;
      min-height:0;
    }
    .global-bar {
      border:1px solid var(--line);
      border-radius:16px;
      background:rgba(255,255,255,.86);
      box-shadow:var(--shadow);
      backdrop-filter: blur(10px);
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:10px;
      padding:6px 10px;
    }
    .global-title {
      font-family:"Sora","IBM Plex Sans",sans-serif;
      font-size:15px;
      font-weight:700;
      letter-spacing:.2px;
    }
    .global-actions { display:flex; align-items:center; gap:6px; flex-wrap:wrap; justify-content:flex-end; }
    .root {
      min-height:0;
      height:100%;
      display:grid;
      grid-template-columns:minmax(300px,340px) 1fr;
      gap:10px;
      min-width:0;
    }
    .sidebar {
      border:1px solid var(--line);
      background:var(--pane);
      border-radius:24px;
      padding:12px;
      display:flex;
      flex-direction:column;
      box-shadow:var(--shadow);
      backdrop-filter: blur(10px);
      overflow:hidden;
      min-height:0;
    }
    .topline { display:block; margin-bottom:8px; }
    .topline strong { font-family:"Sora","IBM Plex Sans",sans-serif; font-size:17px; letter-spacing:.1px; display:block; margin-bottom:6px; }
    .quick-actions { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
    .badge {
      font-size:12px;
      color:var(--muted);
      padding:7px 10px;
      border:1px dashed var(--line-strong);
      border-radius:12px;
      margin-top:10px;
      background:#f7fbff;
    }
    .btn {
      border:1px solid var(--line);
      background:#fff;
      color:var(--txt);
      padding:7px 9px;
      border-radius:10px;
      cursor:pointer;
      font-weight:600;
      transition:.16s ease;
    }
    .btn:hover { border-color:var(--line-strong); transform:translateY(-1px); box-shadow:0 8px 16px rgba(14,30,60,.08); }
    .btn:focus-visible { outline:none; box-shadow:0 0 0 3px rgba(10,103,211,.17); border-color:var(--accent); }
    .btn.accent {
      background:linear-gradient(120deg,var(--accent),#0987cf);
      color:#fff;
      border-color:transparent;
    }
    .chat-list {
      overflow:auto;
      display:flex;
      flex-direction:column;
      gap:8px;
      margin-top:8px;
      padding-right:2px;
      min-height:0;
      flex:1 1 auto;
    }
    .chat-item {
      border:1px solid var(--line);
      border-radius:12px;
      padding:8px;
      background:linear-gradient(180deg,#fff,#fdfefe);
      cursor:pointer;
      transition:.16s ease;
    }
    .chat-item:hover { border-color:var(--line-strong); transform:translateY(-1px); }
    .chat-item.active { border-color:var(--accent); box-shadow:0 0 0 3px rgba(10,103,211,.14); background:#fbfdff; }
    .chat-row { display:flex; justify-content:space-between; align-items:center; gap:8px; }
    .chat-title { font-size:14px; font-weight:700; line-height:1.35; }
    .chat-title-input {
      width:100%;
      font-size:14px;
      font-weight:700;
      border:1px solid var(--accent);
      border-radius:8px;
      padding:5px 8px;
      background:#fff;
    }
    .mode-pill {
      font-size:11px;
      border:1px solid #b8d8ce;
      color:#0a7f5e;
      background:#ebfaf4;
      border-radius:999px;
      padding:2px 8px;
      white-space:nowrap;
      font-family:"IBM Plex Mono",ui-monospace,monospace;
      text-transform:uppercase;
      letter-spacing:.2px;
    }
    .chat-time { font-size:12px; color:var(--muted); margin-top:4px; }
    .lang { display:flex; gap:6px; padding:4px; border:1px solid var(--line); border-radius:999px; width:max-content; background:#fff; }
    .lang .btn { padding:6px 10px; border-radius:999px; border:0; box-shadow:none; }
    .lang .btn:hover { transform:none; box-shadow:none; background:#f2f6fb; }
    .lang .btn.active { background:var(--accent); color:#fff; }

    .main {
      display:grid;
      grid-template-rows:auto 1fr auto;
      border:1px solid var(--line);
      border-radius:24px;
      background:var(--pane);
      box-shadow:var(--shadow);
      backdrop-filter: blur(10px);
      overflow:hidden;
      min-height:0;
      min-width:0;
    }
    .head {
      border-bottom:1px solid var(--line);
      background:rgba(255,255,255,.86);
      padding:8px 12px;
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:10px;
    }
    .head strong {
      font-family:"Sora","IBM Plex Sans",sans-serif;
      font-size:17px;
      max-width:44%;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .head-controls {
      display:grid;
      grid-template-columns:repeat(2, minmax(170px, 1fr));
      gap:6px 8px;
      align-items:end;
      width:min(760px, 100%);
    }
    .control {
      display:flex;
      flex-direction:column;
      gap:3px;
      min-width:0;
    }
    .control label { font-size:11px; color:var(--muted); line-height:1.15; }
    .control select {
      border:1px solid var(--line);
      border-radius:10px;
      padding:5px 8px;
      background:#fff;
      min-width:0;
      color:var(--txt);
      height:34px;
    }
    .head-actions {
      grid-column:1 / -1;
      display:flex;
      align-items:center;
      gap:6px;
      flex-wrap:wrap;
      margin-top:1px;
    }
    .head-actions .btn {
      padding:6px 8px;
      font-size:12px;
    }
    .messages {
      padding:12px;
      overflow:auto;
      display:flex;
      flex-direction:column;
      gap:10px;
      min-height:0;
      background:
        radial-gradient(420px 180px at 2% 4%,rgba(10,103,211,.06),transparent 80%),
        radial-gradient(320px 160px at 98% 95%,rgba(14,169,121,.08),transparent 78%);
    }
    .msg {
      max-width:min(860px,84%);
      border:1px solid var(--line);
      border-radius:16px;
      padding:10px 12px;
      line-height:1.58;
      white-space:pre-wrap;
      box-shadow:0 10px 20px rgba(12,26,48,.06);
      animation:riseIn .2s ease;
    }
    .msg.user { background:var(--user); align-self:flex-end; border-color:#bfe6cf; }
    .msg.assistant { background:var(--bot); align-self:flex-start; border-color:#c9daf3; }
    .composer {
      border-top:1px solid var(--line);
      background:rgba(255,255,255,.92);
      padding:8px 10px;
      max-height:34vh;
      overflow:auto;
    }
    textarea, input, select {
      width:100%;
      border:1px solid var(--line);
      border-radius:10px;
      padding:8px 10px;
      background:#fff;
      color:var(--txt);
      font-family:inherit;
      transition:.16s ease;
    }
    textarea:focus, input:focus, select:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(10,103,211,.14); }
    textarea { min-height:70px; resize:vertical; }
    .brief-card {
      border:1px solid var(--line);
      background:linear-gradient(180deg,#fafdff,#f8fdfb);
      border-radius:12px;
      padding:8px;
      margin-bottom:6px;
    }
    .brief-card.hidden { display:none; }
    .brief-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .brief-grid .full { grid-column:1 / -1; }
    .brief-grid label { font-size:12px; color:var(--muted); display:block; margin-bottom:4px; }
    .brief-grid textarea { min-height:58px; }
    .action { margin-top:6px; display:flex; justify-content:space-between; align-items:center; gap:8px; }
    .upload { margin-top:6px; display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
    .upload label { font-size:12px; color:var(--muted); }
    input[type="file"] {
      width:auto;
      max-width:340px;
      font-size:12px;
      padding:7px;
      border-radius:10px;
      background:#fff;
    }
    .doc-list { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; }
    .doc-pill {
      display:inline-flex;
      align-items:center;
      gap:8px;
      font-size:12px;
      border:1px solid var(--line);
      border-radius:999px;
      padding:4px 9px;
      background:#fff;
      box-shadow:0 6px 14px rgba(13,27,48,.05);
    }
    .doc-pill button {
      border:0;
      background:transparent;
      cursor:pointer;
      color:var(--danger);
      font-size:12px;
      padding:0;
      font-weight:700;
    }
    .hint { font-size:12px; color:var(--muted); }
    .empty-state {
      border:1px dashed var(--line-strong);
      border-radius:14px;
      padding:14px;
      color:var(--muted);
      background:rgba(255,255,255,.66);
      text-align:center;
      font-size:13px;
    }
    .kbd-hint { font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:10px; color:var(--muted); margin-top:4px; }
    @keyframes riseIn {
      from { opacity:.2; transform:translateY(3px); }
      to { opacity:1; transform:none; }
    }
    *::-webkit-scrollbar { width:10px; height:10px; }
    *::-webkit-scrollbar-thumb { background:#c7d5e8; border-radius:999px; border:2px solid rgba(255,255,255,.9); }
    *::-webkit-scrollbar-track { background:transparent; }

    @media (max-width: 1200px) {
      .root { grid-template-columns:300px 1fr; }
      .head strong { max-width:100%; font-size:18px; }
      .head { flex-direction:column; align-items:flex-start; }
      .head-controls { width:100%; }
    }
    @media (max-width: 900px) {
      body { background:linear-gradient(160deg,var(--bg),var(--bg-soft)); }
      .app-shell { padding:6px; gap:6px; }
      .global-bar { border-radius:12px; padding:7px; }
      .global-title { font-size:14px; }
      .root { grid-template-columns:1fr; gap:8px; }
      .sidebar, .main { border-radius:16px; }
      .sidebar { height:36vh; border-right:1px solid var(--line); }
      .global-actions { width:100%; justify-content:flex-start; }
      .quick-actions { grid-template-columns:1fr; }
      .head-controls { grid-template-columns:1fr; }
      .msg { max-width:96%; }
      .brief-grid { grid-template-columns:1fr; }
      .action { flex-direction:column; align-items:stretch; }
      .action .btn { width:100%; }
      input[type="file"] { width:100%; max-width:none; }
      .composer { max-height:40vh; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <div class="global-bar">
      <div class="global-title" data-i18n="app_brand">Marketing Copilot</div>
      <div class="global-actions">
        <div class="lang">
          <button class="btn" id="lang-zh" onclick="setLang('zh')">中文</button>
          <button class="btn" id="lang-en" onclick="setLang('en')">EN</button>
        </div>
        <button class="btn" onclick="gotoKB()" data-i18n="kb_mgmt">KB 管理</button>
        <button class="btn" onclick="gotoGroups()" data-i18n="group_mgmt">组管理</button>
        <button class="btn" onclick="changePassword()" data-i18n="change_password">修改密码</button>
        <button class="btn" onclick="gotoAdmin()" id="admin-btn" style="display:none" data-i18n="user_mgmt">用户管理</button>
        <button class="btn" onclick="logout()" data-i18n="logout">退出</button>
      </div>
    </div>

    <div class="root">
      <aside class="sidebar">
        <div class="topline">
          <strong data-i18n="conversation_list">会话记录</strong>
          <div class="quick-actions">
            <button class="btn accent" onclick="createConversation('chat')" data-i18n="new_chat_conversation">+ 新对话</button>
            <button class="btn" onclick="createConversation('marketing')" data-i18n="new_marketing_conversation">+ 营销任务</button>
          </div>
        </div>
        <div class="badge" id="user-badge"></div>
        <div class="chat-list" id="chat-list"></div>
      </aside>

      <section class="main">
        <div class="head">
          <strong id="chat-title" data-i18n="no_conversation">未选择会话</strong>
          <div class="head-controls">
            <div class="control">
              <label for="model-select" data-i18n="model_label">模型</label>
              <select id="model-select" onchange="changeModel()"></select>
            </div>
            <div class="control">
              <label for="task-mode-select" data-i18n="mode_label">任务模式</label>
              <select id="task-mode-select" onchange="changeTaskMode()">
                <option value="chat" data-i18n="mode_chat">普通聊天</option>
                <option value="marketing" data-i18n="mode_marketing">营销任务</option>
              </select>
            </div>
            <div class="control">
              <label for="visibility-select" data-i18n="visibility_label">可见范围</label>
              <select id="visibility-select" onchange="handleVisibilityModeChange()">
                <option value="private" data-i18n="visibility_private">仅自己</option>
                <option value="task" data-i18n="visibility_task">任务小组</option>
                <option value="company" data-i18n="visibility_company">公司组</option>
              </select>
            </div>
            <div class="control">
              <label for="visibility-group-select" data-i18n="group_label">共享组</label>
              <select id="visibility-group-select"></select>
            </div>
            <div class="head-actions">
              <button class="btn" onclick="saveConversationVisibility()" data-i18n="save_visibility">保存权限</button>
              <button class="btn" onclick="exportConversation()" data-i18n="export_chat">导出聊天</button>
              <button class="btn" onclick="renameConversation()" data-i18n="rename_chat">重命名</button>
              <button class="btn" onclick="deleteConversation()" data-i18n="delete_chat">删除聊天</button>
            </div>
          </div>
        </div>

        <div class="messages" id="messages"></div>

        <div class="composer">
        <div class="brief-card hidden" id="marketing-brief">
          <div class="brief-grid">
            <div>
              <label for="brief-channel" data-i18n="brief_channel">Channel</label>
              <select id="brief-channel">
                <option value=""></option>
                <option value="email">email</option>
                <option value="linkedin">linkedin</option>
                <option value="x">x</option>
                <option value="wechat">wechat</option>
                <option value="landing_page">landing_page</option>
                <option value="other">other</option>
              </select>
            </div>
            <div>
              <label for="kb-select" data-i18n="kb_label">Brand KB</label>
              <select id="kb-select" onchange="changeKBKey()"></select>
            </div>
            <div>
              <label for="brief-product" data-i18n="brief_product">Product</label>
              <input id="brief-product" />
            </div>
            <div>
              <label for="brief-audience" data-i18n="brief_audience">Audience</label>
              <input id="brief-audience" />
            </div>
            <div>
              <label for="brief-objective" data-i18n="brief_objective">Objective</label>
              <input id="brief-objective" />
            </div>
            <div>
              <label for="kb-version-select" data-i18n="kb_version_label">Version</label>
              <select id="kb-version-select" onchange="changeKBVersion()"></select>
            </div>
            <div class="full">
              <label for="brief-extra" data-i18n="brief_extra_requirements">Extra Requirements</label>
              <textarea id="brief-extra"></textarea>
            </div>
          </div>
        </div>
        <label for="input" data-i18n="brief_prompt" style="font-size:12px; color:var(--muted); display:block; margin-bottom:4px;">Prompt</label>
        <textarea id="input" data-i18n-placeholder="input_placeholder" placeholder="输入你的营销任务，例如：给 B2B SaaS 产品写 3 个 LinkedIn 开场文案"></textarea>
        <div class="kbd-hint">Ctrl/Cmd + Enter</div>
        <div class="upload">
          <label for="doc-file" data-i18n="upload_label">上传文档</label>
          <input id="doc-file" type="file" />
          <button class="btn" onclick="uploadDocument()" data-i18n="upload_btn">上传</button>
        </div>
        <div class="doc-list" id="doc-list"></div>
          <div class="action">
            <span class="hint" data-i18n="hint">每个用户仅能访问自己的会话和消息。</span>
            <button class="btn accent" onclick="sendMessage()" data-i18n="send">发送</button>
          </div>
        </div>
      </section>
    </div>
  </div>

<script>
const I18N = {
  zh: {
    page_title: 'Marketing Copilot',
    app_brand: 'Marketing Copilot',
    conversation_list: '会话记录',
    new_conversation: '+ 新对话',
    new_chat_conversation: '+ 新对话',
    new_marketing_conversation: '+ 营销任务',
    no_conversation: '未选择会话',
    model_label: '模型',
    mode_label: '任务模式',
    kb_label: '品牌知识库',
    kb_version_label: '版本',
    kb_create: '新建KB版本',
    kb_mgmt: 'KB 管理',
    group_mgmt: '组管理',
    change_password: '修改密码',
    force_change_password: '为了安全，请先修改默认密码。',
    old_password_prompt: '请输入当前密码',
    new_password_prompt: '请输入新密码（至少8位）',
    password_changed: '密码已更新，请重新登录',
    export_chat: '导出聊天',
    rename_chat: '重命名',
    brief_channel: '渠道',
    brief_prompt: '任务指令',
    brief_product: '产品',
    brief_audience: '受众',
    brief_objective: '目标',
    brief_extra_requirements: '额外要求',
    mode_chat: '普通聊天',
    mode_marketing: '营销任务',
    visibility_label: '可见范围',
    visibility_private: '仅自己',
    visibility_task: '任务小组',
    visibility_company: '公司组',
    group_label: '共享组',
    save_visibility: '保存权限',
    visibility_saved: '权限已更新',
    delete_chat: '删除聊天',
    user_mgmt: '用户管理',
    logout: '退出',
    upload_label: '上传文档',
    upload_btn: '上传',
    input_placeholder: '输入你的营销任务，例如：给 B2B SaaS 产品写 3 个 LinkedIn 开场文案',
    chat_input_placeholder: '输入任意消息进行普通聊天',
    hint: '默认仅自己可见；设置为任务组/公司组后，组内成员可共享访问。',
    send: '发送',
    current_user: '当前用户',
    thinking: '思考中...',
    request_failed: '请求失败',
    request_error: '请求失败',
    default_chat_title: '新对话',
    default_marketing_title: '新营销任务',
    upload_failed: '上传失败',
    upload_success: '上传成功',
    delete_confirm: '确定删除该聊天及其所有消息与文档吗？',
    rename_prompt: '输入新的聊天名称',
    no_chat_selected: '请先选择一个聊天',
    documents_title: '文档',
    kb_none: '不使用KB',
    kb_no_version: '无可用版本',
    kb_key_prompt: '输入 KB Key（建议英文）',
    kb_key_required: 'KB Key 不能为空',
    kb_name_prompt: '输入 KB 名称',
    kb_brand_voice_prompt: '输入品牌语调（可选）',
    kb_notes_prompt: '输入备注（可选）',
    kb_create_success: 'KB 版本已创建:',
    kb_create_failed: '创建 KB 失败',
    export_failed: '导出失败',
    rename_failed: '重命名失败',
    conversations_empty: '还没有会话，点击上方按钮开始。',
    messages_empty: '从这里开始和 Agent 对话。',
    documents_empty: '暂无上传文档。',
    shared_from: '共享自',
    no_group_needed: '无需组',
    choose_group: '请选择组'
  },
  en: {
    page_title: 'Marketing Copilot',
    app_brand: 'Marketing Copilot',
    conversation_list: 'Conversations',
    new_conversation: '+ New Chat',
    new_chat_conversation: '+ Chat',
    new_marketing_conversation: '+ Marketing',
    no_conversation: 'No conversation selected',
    model_label: 'Model',
    mode_label: 'Task Mode',
    kb_label: 'Brand KB',
    kb_version_label: 'Version',
    kb_create: 'New KB Version',
    kb_mgmt: 'KB Management',
    group_mgmt: 'Group Management',
    change_password: 'Change Password',
    force_change_password: 'For security, please change your default password first.',
    old_password_prompt: 'Enter current password',
    new_password_prompt: 'Enter new password (at least 8 characters)',
    password_changed: 'Password updated. Please sign in again.',
    export_chat: 'Export Chat',
    rename_chat: 'Rename',
    brief_channel: 'Channel',
    brief_prompt: 'Prompt',
    brief_product: 'Product',
    brief_audience: 'Audience',
    brief_objective: 'Objective',
    brief_extra_requirements: 'Extra Requirements',
    mode_chat: 'Chat',
    mode_marketing: 'Marketing',
    visibility_label: 'Visibility',
    visibility_private: 'Private',
    visibility_task: 'Task Group',
    visibility_company: 'Company Group',
    group_label: 'Share Group',
    save_visibility: 'Save Visibility',
    visibility_saved: 'Visibility updated',
    delete_chat: 'Delete Chat',
    user_mgmt: 'User Management',
    logout: 'Log Out',
    upload_label: 'Upload document',
    upload_btn: 'Upload',
    input_placeholder: 'Type your marketing task, e.g., write 3 LinkedIn hooks for a B2B SaaS launch',
    chat_input_placeholder: 'Type a free-form message to chat with the agent',
    hint: 'Private by default. Task-group/company visibility shares chats with approved members.',
    send: 'Send',
    current_user: 'Current user',
    thinking: 'Thinking...',
    request_failed: 'Request failed',
    request_error: 'Request failed',
    default_chat_title: 'New Chat',
    default_marketing_title: 'New Marketing Task',
    upload_failed: 'Upload failed',
    upload_success: 'Upload succeeded',
    delete_confirm: 'Delete this chat with all messages and documents?',
    rename_prompt: 'Enter a new conversation title',
    no_chat_selected: 'Please select a conversation first',
    documents_title: 'Documents',
    kb_none: 'No KB',
    kb_no_version: 'No versions',
    kb_key_prompt: 'Enter KB key (recommended: lowercase id)',
    kb_key_required: 'KB key is required',
    kb_name_prompt: 'Enter KB display name',
    kb_brand_voice_prompt: 'Enter brand voice (optional)',
    kb_notes_prompt: 'Enter notes (optional)',
    kb_create_success: 'KB version created:',
    kb_create_failed: 'Failed to create KB',
    export_failed: 'Export failed',
    rename_failed: 'Rename failed',
    conversations_empty: 'No conversations yet. Start one from above.',
    messages_empty: 'Start chatting with your agent here.',
    documents_empty: 'No uploaded documents yet.',
    shared_from: 'Shared from',
    no_group_needed: 'No group needed',
    choose_group: 'Choose group'
  }
};

let me = null;
let conversations = [];
let models = [];
let kbList = [];
let kbVersions = [];
let myGroups = [];
let activeConversationId = null;
let activeDocuments = [];
let suppressKBChange = false;
let editingConversationId = null;
let currentLang = localStorage.getItem('nova_lang') || 'zh';
let csrfToken = '';

function currentConversation() {
  return conversations.find((x) => x.id === activeConversationId) || null;
}

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || key;
}

function setLang(lang) {
  currentLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('nova_lang', currentLang);
  applyI18n();
}

function applyI18n() {
  document.title = t('page_title');
  document.documentElement.lang = currentLang === 'en' ? 'en' : 'zh-CN';
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.getElementById('lang-zh').classList.toggle('active', currentLang === 'zh');
  document.getElementById('lang-en').classList.toggle('active', currentLang === 'en');
  if (!activeConversationId) {
    document.getElementById('chat-title').textContent = t('no_conversation');
  }
  if (me) {
    document.getElementById('user-badge').textContent = `${t('current_user')}: ${me.username}`;
  }
  renderKBKeySelect();
  renderKBVersionSelect();
  renderVisibilityGroupSelect();
  renderConversations();
  renderDocuments();
  const emptyMsg = document.querySelector('#messages .empty-state');
  if (emptyMsg && !document.querySelector('#messages .msg')) {
    emptyMsg.textContent = t('messages_empty');
  }
  syncTaskModeSelect();
  syncTaskModeUI();
  syncConversationVisibilityUI();
}

function syncTaskModeUI() {
  const brief = document.getElementById('marketing-brief');
  const active = currentConversation();
  const mode = active && active.task_mode ? active.task_mode : 'chat';
  const marketingMode = mode === 'marketing';
  brief.classList.toggle('hidden', !marketingMode);
  document.getElementById('input').placeholder = marketingMode
    ? t('input_placeholder')
    : t('chat_input_placeholder');
}

async function api(url, options={}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = options.body instanceof FormData ? {} : {'Content-Type':'application/json'};
  if (csrfToken && ['POST','PUT','PATCH','DELETE'].includes(method)) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  const res = await fetch(url, {headers, ...options});
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error(data.detail || t('request_failed'));
  return data;
}

async function loadCsrfToken() {
  const res = await fetch('/api/csrf');
  if (!res.ok) throw new Error('csrf');
  const data = await res.json();
  csrfToken = data.csrf_token || '';
}

function fmt(ts) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

function renderDocuments() {
  const box = document.getElementById('doc-list');
  box.innerHTML = '';
  if (!activeDocuments.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = t('documents_empty');
    box.appendChild(empty);
    return;
  }
  for (const d of activeDocuments) {
    const item = document.createElement('div');
    item.className = 'doc-pill';
    item.innerHTML = `<span>${d.filename}</span><button title="delete" onclick="deleteDocument(${d.id})">x</button>`;
    box.appendChild(item);
  }
}

function syncModelSelect() {
  const select = document.getElementById('model-select');
  select.innerHTML = '';
  for (const m of models) {
    const option = document.createElement('option');
    option.value = m;
    option.textContent = m;
    select.appendChild(option);
  }
  const active = conversations.find(x => x.id === activeConversationId);
  if (active && active.model_id) {
    select.value = active.model_id;
  }
}

function syncTaskModeSelect() {
  const select = document.getElementById('task-mode-select');
  const active = currentConversation();
  if (!activeConversationId || !active) {
    select.value = 'chat';
    select.disabled = true;
    return;
  }
  select.disabled = false;
  select.value = active.task_mode || 'chat';
}

function renderVisibilityGroupSelect(visibilityMode = null) {
  const select = document.getElementById('visibility-group-select');
  if (!select) return;
  const targetVisibility = visibilityMode || document.getElementById('visibility-select')?.value || 'private';
  const requiredType = targetVisibility === 'company' ? 'company' : (targetVisibility === 'task' ? 'task' : null);
  const previous = select.value;
  select.innerHTML = '';
  const none = document.createElement('option');
  none.value = '';
  none.textContent = t('no_group_needed');
  select.appendChild(none);
  const eligibleGroups = requiredType ? myGroups.filter((g) => g.group_type === requiredType) : myGroups;
  for (const g of eligibleGroups) {
    const option = document.createElement('option');
    option.value = String(g.id);
    const typeLabel = g.group_type === 'company' ? t('visibility_company') : t('visibility_task');
    option.textContent = `${g.name} (${typeLabel})`;
    option.dataset.groupType = g.group_type;
    select.appendChild(option);
  }
  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  }
}

function syncConversationVisibilityUI() {
  const visibilitySelect = document.getElementById('visibility-select');
  const groupSelect = document.getElementById('visibility-group-select');
  const active = currentConversation();
  if (!activeConversationId || !active) {
    visibilitySelect.value = 'private';
    visibilitySelect.disabled = true;
    groupSelect.value = '';
    groupSelect.disabled = true;
    return;
  }
  visibilitySelect.disabled = false;
  visibilitySelect.value = active.visibility || 'private';
  renderVisibilityGroupSelect(visibilitySelect.value);
  const ownerId = active.user_id ?? null;
  const isOwner = me && ownerId === me.id;
  visibilitySelect.disabled = !isOwner;
  groupSelect.disabled = !isOwner;
  if (active.share_group_id) {
    groupSelect.value = String(active.share_group_id);
  } else {
    groupSelect.value = '';
  }
  handleVisibilityModeChange();
}

function handleVisibilityModeChange() {
  const visibilitySelect = document.getElementById('visibility-select');
  const groupSelect = document.getElementById('visibility-group-select');
  if (!visibilitySelect || !groupSelect) return;
  renderVisibilityGroupSelect(visibilitySelect.value);
  const active = currentConversation();
  const ownerId = active ? (active.user_id ?? null) : null;
  const isOwner = !!(me && active && ownerId === me.id);
  if (!isOwner) return;
  const vis = visibilitySelect.value;
  if (vis === 'private') {
    groupSelect.disabled = true;
    groupSelect.value = '';
  } else {
    groupSelect.disabled = false;
  }
}

async function loadModels() {
  const data = await api('/api/models');
  models = data.models || [];
  syncModelSelect();
  syncTaskModeSelect();
}

async function loadMyGroups() {
  myGroups = await api('/api/groups/mine');
  renderVisibilityGroupSelect();
}

async function saveConversationVisibility() {
  if (!activeConversationId) {
    alert(t('no_chat_selected'));
    return;
  }
  const active = currentConversation();
  if (!active || !me || active.user_id !== me.id) {
    return;
  }
  const visibility = document.getElementById('visibility-select').value;
  const rawGroup = document.getElementById('visibility-group-select').value;
  const payload = {
    visibility,
    share_group_id: rawGroup ? Number(rawGroup) : null,
  };
  const data = await api(`/api/conversations/${activeConversationId}/visibility`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  conversations = conversations.map((c) => (
    c.id === activeConversationId
      ? {...c, visibility: data.visibility, share_group_id: data.share_group_id, share_group_name: data.share_group_name}
      : c
  ));
  renderConversations();
  syncConversationVisibilityUI();
}

function renderKBKeySelect() {
  const select = document.getElementById('kb-select');
  const previous = select.value;
  select.innerHTML = '';
  const none = document.createElement('option');
  none.value = '';
  none.textContent = t('kb_none');
  select.appendChild(none);
  for (const kb of kbList) {
    const option = document.createElement('option');
    option.value = kb.kb_key;
    option.textContent = `${kb.kb_name} (v${kb.version})`;
    select.appendChild(option);
  }
  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  }
}

function renderKBVersionSelect() {
  const select = document.getElementById('kb-version-select');
  const previous = select.value;
  select.innerHTML = '';
  if (!kbVersions.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = t('kb_no_version');
    select.appendChild(option);
    return;
  }
  for (const versionItem of kbVersions) {
    const option = document.createElement('option');
    option.value = String(versionItem.version);
    option.textContent = `v${versionItem.version}`;
    select.appendChild(option);
  }
  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  }
}

async function loadKBList() {
  kbList = await api('/api/kb/list');
  renderKBKeySelect();
}

async function loadKBVersions(kbKey) {
  if (!kbKey) {
    kbVersions = [];
    renderKBVersionSelect();
    return;
  }
  try {
    kbVersions = await api(`/api/kb/${encodeURIComponent(kbKey)}/versions`);
  } catch (_) {
    kbVersions = [];
  }
  renderKBVersionSelect();
}

async function syncKBSelects() {
  const keySelect = document.getElementById('kb-select');
  const versionSelect = document.getElementById('kb-version-select');
  if (!activeConversationId) {
    suppressKBChange = true;
    renderKBKeySelect();
    kbVersions = [];
    renderKBVersionSelect();
    keySelect.value = '';
    keySelect.disabled = true;
    versionSelect.disabled = true;
    suppressKBChange = false;
    return;
  }

  keySelect.disabled = false;
  versionSelect.disabled = false;
  if (!kbList.length) {
    await loadKBList();
  } else {
    renderKBKeySelect();
  }
  const active = conversations.find((x) => x.id === activeConversationId);
  const selectedKey = active && active.kb_key ? active.kb_key : '';
  suppressKBChange = true;
  keySelect.value = selectedKey;
  suppressKBChange = false;

  if (!selectedKey) {
    kbVersions = [];
    renderKBVersionSelect();
    return;
  }

  await loadKBVersions(selectedKey);
  suppressKBChange = true;
  if (active && active.kb_version) {
    versionSelect.value = String(active.kb_version);
  }
  if (!versionSelect.value && kbVersions.length) {
    versionSelect.value = String(kbVersions[0].version);
  }
  suppressKBChange = false;
}

async function updateConversationKB(kbKey, kbVersion) {
  if (!activeConversationId) return null;
  const payload = kbKey && kbVersion
    ? {kb_key: kbKey, kb_version: Number(kbVersion)}
    : {kb_key: null, kb_version: null};
  const data = await api(`/api/conversations/${activeConversationId}/kb`, {
    method:'PATCH',
    body: JSON.stringify(payload)
  });
  conversations = conversations.map((c) => (
    c.id === activeConversationId
      ? {...c, kb_key: data.kb_key, kb_version: data.kb_version}
      : c
  ));
  return data;
}

async function changeKBKey() {
  if (suppressKBChange || !activeConversationId) return;
  const kbKey = document.getElementById('kb-select').value;
  if (!kbKey) {
    kbVersions = [];
    renderKBVersionSelect();
    await updateConversationKB(null, null);
    return;
  }
  await loadKBVersions(kbKey);
  if (!kbVersions.length) {
    await updateConversationKB(null, null);
    return;
  }
  const versionSelect = document.getElementById('kb-version-select');
  suppressKBChange = true;
  versionSelect.value = String(kbVersions[0].version);
  suppressKBChange = false;
  await updateConversationKB(kbKey, Number(versionSelect.value));
}

async function changeKBVersion() {
  if (suppressKBChange || !activeConversationId) return;
  const kbKey = document.getElementById('kb-select').value;
  const versionRaw = document.getElementById('kb-version-select').value;
  if (!kbKey || !versionRaw) {
    await updateConversationKB(null, null);
    return;
  }
  await updateConversationKB(kbKey, Number(versionRaw));
}

async function createKbVersion() {
  const rawKey = prompt(t('kb_key_prompt'));
  if (rawKey === null) return;
  const kbKey = rawKey.trim();
  if (!kbKey) {
    alert(t('kb_key_required'));
    return;
  }
  const kbNameRaw = prompt(t('kb_name_prompt'), kbKey);
  if (kbNameRaw === null) return;
  const brandVoiceRaw = prompt(t('kb_brand_voice_prompt'), '');
  if (brandVoiceRaw === null) return;
  const notesRaw = prompt(t('kb_notes_prompt'), '');
  if (notesRaw === null) return;
  try {
    const created = await api('/api/kb', {
      method:'POST',
      body: JSON.stringify({
        kb_key: kbKey,
        kb_name: kbNameRaw.trim() || kbKey,
        brand_voice: brandVoiceRaw.trim() || null,
        positioning: {},
        glossary: [],
        forbidden_words: [],
        required_terms: [],
        claims_policy: {},
        examples: null,
        notes: notesRaw.trim() || null
      })
    });
    await loadKBList();
    if (activeConversationId) {
      suppressKBChange = true;
      document.getElementById('kb-select').value = created.kb_key;
      suppressKBChange = false;
      await loadKBVersions(created.kb_key);
      suppressKBChange = true;
      document.getElementById('kb-version-select').value = String(created.version);
      suppressKBChange = false;
      await updateConversationKB(created.kb_key, created.version);
    }
    alert(`${t('kb_create_success')} ${created.kb_key} v${created.version}`);
  } catch (e) {
    alert(`${t('kb_create_failed')}: ${e.message}`);
  }
}

async function loadDocuments(conversationId) {
  activeDocuments = await api(`/api/conversations/${conversationId}/documents`);
  renderDocuments();
}

function renderConversations() {
  const list = document.getElementById('chat-list');
  list.innerHTML = '';
  if (!conversations.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = t('conversations_empty');
    list.appendChild(empty);
    return;
  }
  for (const c of conversations) {
    const div = document.createElement('div');
    div.className = 'chat-item' + (c.id === activeConversationId ? ' active' : '');
    div.onclick = () => openConversation(c.id);
    const row = document.createElement('div');
    row.className = 'chat-row';
    const modeLabel = c.task_mode === 'marketing' ? t('mode_marketing') : t('mode_chat');

    if (editingConversationId === c.id) {
      const input = document.createElement('input');
      input.className = 'chat-title-input';
      input.value = c.title || '';
      input.onkeydown = async (event) => {
        event.stopPropagation();
        if (event.key === 'Enter') {
          await submitInlineRename(c.id, input.value);
        } else if (event.key === 'Escape') {
          cancelInlineRename();
        }
      };
      input.onblur = async () => {
        await submitInlineRename(c.id, input.value);
      };
      input.onclick = (event) => event.stopPropagation();
      input.ondblclick = (event) => event.stopPropagation();
      row.appendChild(input);
      setTimeout(() => {
        const el = document.querySelector(`[data-rename-input="${c.id}"]`);
        if (el) { el.focus(); el.select(); }
      }, 0);
      input.setAttribute('data-rename-input', String(c.id));
    } else {
      const title = document.createElement('div');
      title.className = 'chat-title';
      title.textContent = c.title;
      title.ondblclick = (event) => {
        event.stopPropagation();
        startInlineRename(c.id);
      };
      row.appendChild(title);
    }

    const mode = document.createElement('span');
    mode.className = 'mode-pill';
    mode.textContent = modeLabel;
    row.appendChild(mode);

    const time = document.createElement('div');
    time.className = 'chat-time';
    const owner = c.owner_username || '';
    const shared = me && owner && owner !== me.username;
    const sharedPrefix = shared ? `${t('shared_from')}: ${owner} · ` : '';
    time.textContent = `${sharedPrefix}${fmt(c.updated_at)}`;

    div.appendChild(row);
    div.appendChild(time);
    list.appendChild(div);
  }
}

function startInlineRename(conversationId) {
  if (!conversationId) return;
  editingConversationId = conversationId;
  renderConversations();
}

function cancelInlineRename() {
  editingConversationId = null;
  renderConversations();
}

async function submitInlineRename(conversationId, rawTitle) {
  const title = (rawTitle || '').trim();
  const target = conversations.find((x) => x.id === conversationId);
  if (!title) {
    cancelInlineRename();
    return;
  }
  if (target && target.title === title) {
    cancelInlineRename();
    return;
  }
  try {
    const data = await api(`/api/conversations/${conversationId}/title`, {
      method:'PATCH',
      body: JSON.stringify({ title })
    });
    conversations = conversations.map((c) => (
      c.id === conversationId ? {...c, title: data.title, updated_at: data.updated_at} : c
    ));
    if (activeConversationId === conversationId) {
      document.getElementById('chat-title').textContent = data.title;
    }
  } catch (e) {
    alert(`${t('rename_failed')}: ${e.message}`);
  } finally {
    editingConversationId = null;
    renderConversations();
  }
}

function renderMessages(items) {
  const box = document.getElementById('messages');
  box.innerHTML = '';
  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = t('messages_empty');
    box.appendChild(empty);
    return;
  }
  for (const m of items) {
    const div = document.createElement('div');
    div.className = 'msg ' + (m.role === 'user' ? 'user' : 'assistant');
    div.textContent = m.content;
    box.appendChild(div);
  }
  box.scrollTop = box.scrollHeight;
}

async function loadMe() {
  me = await api('/api/me');
  document.getElementById('user-badge').textContent = `${t('current_user')}: ${me.username}`;
  if (me.is_admin) document.getElementById('admin-btn').style.display = 'inline-block';
  if (me.must_change_password) {
    alert(t('force_change_password'));
    await changePassword(true);
  }
}

async function loadConversations() {
  conversations = await api('/api/conversations');
  if (activeConversationId && !conversations.some((x) => x.id === activeConversationId)) {
    activeConversationId = null;
  }
  renderConversations();
  if (!activeConversationId && conversations.length) {
    await openConversation(conversations[0].id);
    return;
  }
  syncModelSelect();
  syncTaskModeSelect();
  await syncKBSelects();
  syncTaskModeUI();
  syncConversationVisibilityUI();
}

async function createConversation(taskMode='chat') {
  const created = await api('/api/conversations', {
    method:'POST',
    body:JSON.stringify({task_mode: taskMode, visibility: 'private', share_group_id: null})
  });
  if (created.title === '新对话') {
    created.title = t('default_chat_title');
  }
  if (created.title === '新营销任务') {
    created.title = t('default_marketing_title');
  }
  conversations.unshift(created);
  activeConversationId = created.id;
  renderConversations();
  document.getElementById('chat-title').textContent = created.title;
  renderMessages([]);
  activeDocuments = [];
  renderDocuments();
  syncModelSelect();
  syncTaskModeSelect();
  await syncKBSelects();
  syncTaskModeUI();
  syncConversationVisibilityUI();
}

async function openConversation(id) {
  activeConversationId = id;
  const conv = conversations.find(x => x.id === id);
  if (conv) document.getElementById('chat-title').textContent = conv.title;
  renderConversations();
  const items = await api(`/api/conversations/${id}/messages`);
  renderMessages(items);
  await loadDocuments(id);
  syncModelSelect();
  syncTaskModeSelect();
  await syncKBSelects();
  syncTaskModeUI();
  syncConversationVisibilityUI();
}

async function changeModel() {
  if (!activeConversationId) return;
  const modelId = document.getElementById('model-select').value;
  const data = await api(`/api/conversations/${activeConversationId}/model`, {
    method:'PATCH',
    body: JSON.stringify({ model_id: modelId })
  });
  conversations = conversations.map(c => c.id === activeConversationId ? {...c, model_id: data.model_id} : c);
}

async function changeTaskMode() {
  if (!activeConversationId) return;
  const taskMode = document.getElementById('task-mode-select').value;
  const data = await api(`/api/conversations/${activeConversationId}/mode`, {
    method:'PATCH',
    body: JSON.stringify({ task_mode: taskMode })
  });
  conversations = conversations.map((c) => (
    c.id === activeConversationId ? {...c, task_mode: data.task_mode} : c
  ));
  renderConversations();
  syncTaskModeUI();
}

async function deleteConversation() {
  if (!activeConversationId) {
    alert(t('no_chat_selected'));
    return;
  }
  if (!confirm(t('delete_confirm'))) return;
  await api(`/api/conversations/${activeConversationId}`, {method:'DELETE'});
  activeConversationId = null;
  await loadConversations();
  if (!conversations.length) {
    document.getElementById('chat-title').textContent = t('no_conversation');
    renderMessages([]);
    activeDocuments = [];
    renderDocuments();
    syncModelSelect();
    syncTaskModeSelect();
    await syncKBSelects();
    syncTaskModeUI();
  }
}

async function uploadDocument() {
  if (!activeConversationId) {
    alert(t('no_chat_selected'));
    return;
  }
  const fileInput = document.getElementById('doc-file');
  if (!fileInput.files || !fileInput.files.length) return;
  const form = new FormData();
  form.append('file', fileInput.files[0]);
  try {
    await api(`/api/conversations/${activeConversationId}/documents`, {
      method:'POST',
      body: form
    });
    fileInput.value = '';
    await loadDocuments(activeConversationId);
  } catch (e) {
    alert(`${t('upload_failed')}: ${e.message}`);
  }
}

async function deleteDocument(documentId) {
  if (!activeConversationId) return;
  await api(`/api/conversations/${activeConversationId}/documents/${documentId}`, {method:'DELETE'});
  await loadDocuments(activeConversationId);
}

async function sendMessage() {
  if (!activeConversationId) await createConversation('chat');
  const input = document.getElementById('input');
  const content = input.value.trim();
  if (!content) return;
  input.value = '';

  const box = document.getElementById('messages');
  const empty = box.querySelector('.empty-state');
  if (empty) empty.remove();
  const pendingUser = document.createElement('div');
  pendingUser.className = 'msg user';
  pendingUser.textContent = content;
  box.appendChild(pendingUser);

  const pendingBot = document.createElement('div');
  pendingBot.className = 'msg assistant';
  pendingBot.textContent = t('thinking');
  box.appendChild(pendingBot);
  box.scrollTop = box.scrollHeight;

  try {
    const active = currentConversation();
    const payload = { content, ui_language: currentLang };
    if (active && active.task_mode === 'marketing') {
      payload.channel = document.getElementById('brief-channel').value || null;
      payload.product = document.getElementById('brief-product').value.trim() || null;
      payload.audience = document.getElementById('brief-audience').value.trim() || null;
      payload.objective = document.getElementById('brief-objective').value.trim() || null;
      payload.extra_requirements = document.getElementById('brief-extra').value.trim() || null;
    }
    const data = await api(`/api/conversations/${activeConversationId}/messages`, {
      method:'POST',
      body: JSON.stringify(payload)
    });
    pendingBot.textContent = data.assistant_message.content;
    await loadConversations();
    renderConversations();
  } catch (e) {
    pendingBot.textContent = `${t('request_error')}: ${e.message}`;
  }
}

async function logout() {
  await api('/logout', {method:'POST'});
  location.href = '/';
}

async function changePassword(force=false) {
  const currentPassword = prompt(t('old_password_prompt'));
  if (!currentPassword) {
    if (force) {
      await logout();
      return;
    }
    return;
  }
  const newPassword = prompt(t('new_password_prompt'));
  if (!newPassword) return;
  try {
    await api('/api/account/password', {
      method:'POST',
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    alert(t('password_changed'));
    await logout();
  } catch (e) {
    alert(`${t('request_failed')}: ${e.message}`);
    if (force) {
      await changePassword(true);
    }
  }
}

async function exportConversation() {
  if (!activeConversationId) {
    alert(t('no_chat_selected'));
    return;
  }
  try {
    const data = await api(`/api/conversations/${activeConversationId}/export`);
    const blob = new Blob([data.content], {type: 'text/markdown;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = data.filename || `conversation-${activeConversationId}.md`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert(`${t('export_failed')}: ${e.message}`);
  }
}

async function renameConversation() {
  if (!activeConversationId) {
    alert(t('no_chat_selected'));
    return;
  }
  startInlineRename(activeConversationId);
}

function gotoAdmin() { location.href = '/admin'; }
function gotoKB() { location.href = '/kb'; }
function gotoGroups() { location.href = '/groups'; }

(async function init(){
  try {
    applyI18n();
    await loadCsrfToken();
    await loadMe();
    await loadModels();
    await loadMyGroups();
    await loadKBList();
    await loadConversations();
    document.getElementById('input').addEventListener('keydown', (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        sendMessage();
      }
    });
  } catch {
    location.href = '/';
  }
})();
</script>
</body>
</html>
"""


KB_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Marketing Copilot - KB</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap');
    :root {
      --bg:#eef4ff;
      --line:#d6dfec;
      --line-strong:#bfcee3;
      --txt:#0f1b2d;
      --muted:#55657d;
      --accent:#0a67d3;
      --danger:#c63939;
      --ok:#0f766e;
      --shadow:0 18px 36px rgba(16,32,62,.12);
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      font-family:"IBM Plex Sans","Segoe UI",sans-serif;
      background:
        radial-gradient(920px 520px at 0% -10%,#d8e7ff 0%,transparent 58%),
        radial-gradient(980px 560px at 106% -16%,#d7f3e8 0%,transparent 62%),
        linear-gradient(160deg,#edf4ff,#f5fbf6);
      color:var(--txt);
    }
    .wrap { max-width:1220px; margin:16px auto; padding:0 14px; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:12px; }
    .top h2 { font-family:"Sora","IBM Plex Sans",sans-serif; margin:0; }
    .toolbar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    .toolbar button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
    .layout { display:grid; grid-template-columns: 330px 1fr; gap:12px; }
    .card {
      background:rgba(255,255,255,.88);
      border:1px solid var(--line);
      border-radius:18px;
      padding:14px;
      box-shadow:var(--shadow);
      backdrop-filter: blur(8px);
    }
    .card h3 { margin:0 0 10px; font-family:"Sora","IBM Plex Sans",sans-serif; font-size:17px; }
    .list { display:flex; flex-direction:column; gap:8px; max-height:620px; overflow:auto; padding-right:2px; }
    .item {
      border:1px solid var(--line);
      border-radius:12px;
      padding:9px;
      cursor:pointer;
      background:#fff;
      transition:.16s ease;
    }
    .item:hover { transform:translateY(-1px); border-color:var(--line-strong); }
    .item.active { border-color:var(--accent); box-shadow:0 0 0 3px rgba(10,103,211,.14); background:#fbfdff; }
    .item .name { font-weight:700; font-size:14px; }
    .item .meta { color:var(--muted); font-size:12px; margin-top:4px; font-family:"IBM Plex Mono",ui-monospace,monospace; }
    .grid { display:grid; gap:10px; grid-template-columns:1fr 1fr; }
    .full { grid-column:1 / -1; }
    label { font-size:12px; color:var(--muted); display:block; margin-bottom:4px; font-weight:600; }
    input, select, textarea, button {
      width:100%;
      box-sizing:border-box;
      padding:9px 10px;
      border-radius:11px;
      border:1px solid var(--line);
      font-family:inherit;
      transition:.16s ease;
      color:var(--txt);
      background:#fff;
    }
    input:focus, select:focus, textarea:focus {
      outline:none;
      border-color:var(--accent);
      box-shadow:0 0 0 3px rgba(10,103,211,.14);
    }
    textarea { min-height:96px; font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:12px; }
    button { cursor:pointer; font-weight:600; }
    button:hover { border-color:var(--line-strong); transform:translateY(-1px); box-shadow:0 8px 14px rgba(15,30,60,.07); }
    button.primary { background:linear-gradient(120deg,var(--accent),#0987cf); border-color:transparent; color:#fff; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; }
    .actions button { width:auto; }
    .msg {
      font-size:12px;
      margin-top:10px;
      color:var(--ok);
      min-height:20px;
      border-radius:10px;
      background:#f3fdf9;
      border:1px solid #bde9d9;
      padding:7px 10px;
    }
    .warn { color:var(--danger); background:#fff6f6; border-color:#f0c9c9; }
    .empty {
      border:1px dashed var(--line-strong);
      border-radius:12px;
      padding:13px;
      text-align:center;
      color:var(--muted);
      background:rgba(255,255,255,.62);
      font-size:13px;
    }
    *::-webkit-scrollbar { width:10px; height:10px; }
    *::-webkit-scrollbar-thumb { background:#c7d5e8; border-radius:999px; border:2px solid rgba(255,255,255,.9); }
    *::-webkit-scrollbar-track { background:transparent; }
    @media (max-width: 960px) {
      .layout { grid-template-columns:1fr; }
      .toolbar { justify-content:flex-start; }
      .actions button { width:100%; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <h2 data-i18n="title">Brand KB 管理</h2>
      <div class="toolbar">
        <button id="lang-zh" onclick="setLang('zh')">中文</button>
        <button id="lang-en" onclick="setLang('en')">EN</button>
        <button onclick="backToApp()" data-i18n="back">返回聊天</button>
        <button onclick="logout()" data-i18n="logout">退出</button>
      </div>
    </div>
    <div class="layout">
      <div class="card">
        <h3 data-i18n="kb_list">KB 列表</h3>
        <div id="kb-list" class="list"></div>
      </div>
      <div class="card">
        <div class="grid">
          <div>
            <label for="kb-key-select" data-i18n="select_key">选择 KB Key</label>
            <select id="kb-key-select" onchange="changeKBKey()"></select>
          </div>
          <div>
            <label for="kb-version-select-page" data-i18n="select_version">选择版本</label>
            <select id="kb-version-select-page" onchange="loadSelectedVersion()"></select>
          </div>
          <div>
            <label for="kb-visibility" data-i18n="visibility_label">可见范围</label>
            <select id="kb-visibility" onchange="onKBVisibilityChange()">
              <option value="private" data-i18n="visibility_private">仅自己</option>
              <option value="task" data-i18n="visibility_task">任务小组</option>
              <option value="company" data-i18n="visibility_company">公司组</option>
            </select>
          </div>
          <div>
            <label for="kb-share-group" data-i18n="group_label">共享组</label>
            <select id="kb-share-group"></select>
          </div>
          <div class="full">
            <label for="kb-key-input" data-i18n="new_key">新版本目标 Key（可新建）</label>
            <input id="kb-key-input" placeholder="brand_main" />
          </div>
          <div>
            <label for="kb-name" data-i18n="kb_name">KB 名称</label>
            <input id="kb-name" />
          </div>
          <div>
            <label for="kb-brand-voice" data-i18n="brand_voice">Brand Voice</label>
            <input id="kb-brand-voice" />
          </div>
          <div class="full">
            <label for="kb-positioning" data-i18n="positioning">Positioning (JSON or natural language)</label>
            <textarea id="kb-positioning">{}</textarea>
          </div>
          <div class="full">
            <label for="kb-glossary" data-i18n="glossary">Glossary (JSON array or natural language)</label>
            <textarea id="kb-glossary">[]</textarea>
          </div>
          <div class="full">
            <label for="kb-forbidden" data-i18n="forbidden">Forbidden Words (JSON array or natural language)</label>
            <textarea id="kb-forbidden">[]</textarea>
          </div>
          <div class="full">
            <label for="kb-required" data-i18n="required">Required Terms (JSON array or natural language)</label>
            <textarea id="kb-required">[]</textarea>
          </div>
          <div class="full">
            <label for="kb-claims" data-i18n="claims">Claims Policy (JSON or natural language)</label>
            <textarea id="kb-claims">{}</textarea>
          </div>
          <div class="full">
            <label for="kb-examples" data-i18n="examples">Examples (JSON / natural language / null)</label>
            <textarea id="kb-examples">null</textarea>
          </div>
          <div class="full">
            <label for="kb-notes" data-i18n="notes">Notes</label>
            <textarea id="kb-notes"></textarea>
          </div>
          <div class="full actions">
            <button class="primary" onclick="createVersion()" data-i18n="create_version">创建新版本</button>
            <button onclick="updateVersion()" data-i18n="update_version">更新当前版本</button>
            <button onclick="deleteVersion()" data-i18n="delete_version">删除当前版本</button>
          </div>
        </div>
        <div id="msg" class="msg"></div>
      </div>
    </div>
  </div>
<script>
const I18N = {
  zh: {
    title: 'Brand KB 管理',
    back: '返回聊天',
    logout: '退出',
    kb_list: 'KB 列表',
    select_key: '选择 KB Key',
    select_version: '选择版本',
    visibility_label: '可见范围',
    visibility_private: '仅自己',
    visibility_task: '任务小组',
    visibility_company: '公司组',
    group_label: '共享组',
    no_group_needed: '无需组',
    new_key: '新版本目标 Key（可新建）',
    kb_name: 'KB 名称',
    brand_voice: '品牌语调',
    positioning: '定位（JSON 或自然语言）',
    glossary: '术语表（JSON 数组或自然语言）',
    forbidden: '禁用词（JSON 数组或自然语言）',
    required: '必需词（JSON 数组或自然语言）',
    claims: '声明策略（JSON 或自然语言）',
    examples: '示例（JSON / 自然语言 / null）',
    notes: '备注',
    create_version: '创建新版本',
    update_version: '更新当前版本',
    delete_version: '删除当前版本',
    none: '无',
    load_failed: '加载失败',
    create_ok: '新版本创建成功',
    update_ok: '版本更新成功',
    delete_ok: '版本删除成功',
    delete_confirm: '确定删除该 KB 版本吗？',
    required_key: '请输入 KB Key',
    invalid_json: 'JSON 格式错误',
    kb_empty: '还没有 KB 版本，请先在右侧创建。',
    shared_from: '共享自'
  },
  en: {
    title: 'Brand KB Management',
    back: 'Back to Chat',
    logout: 'Log Out',
    kb_list: 'KB List',
    select_key: 'Select KB Key',
    select_version: 'Select Version',
    visibility_label: 'Visibility',
    visibility_private: 'Private',
    visibility_task: 'Task Group',
    visibility_company: 'Company Group',
    group_label: 'Share Group',
    no_group_needed: 'No group needed',
    new_key: 'Target key for new version',
    kb_name: 'KB Name',
    brand_voice: 'Brand Voice',
    positioning: 'Positioning (JSON or natural language)',
    glossary: 'Glossary (JSON array or natural language)',
    forbidden: 'Forbidden Words (JSON array or natural language)',
    required: 'Required Terms (JSON array or natural language)',
    claims: 'Claims Policy (JSON or natural language)',
    examples: 'Examples (JSON / natural language / null)',
    notes: 'Notes',
    create_version: 'Create New Version',
    update_version: 'Update Current Version',
    delete_version: 'Delete Current Version',
    none: 'None',
    load_failed: 'Failed to load',
    create_ok: 'Version created',
    update_ok: 'Version updated',
    delete_ok: 'Version deleted',
    delete_confirm: 'Delete this KB version?',
    required_key: 'KB key is required',
    invalid_json: 'Invalid JSON',
    kb_empty: 'No KB versions yet. Create one from the form.',
    shared_from: 'Shared from'
  }
};

let currentLang = localStorage.getItem('nova_lang') || 'zh';
let kbList = [];
let kbVersions = [];
let myGroups = [];
let me = null;
let csrfToken = '';

function t(key) { return (I18N[currentLang] && I18N[currentLang][key]) || key; }
function setMsg(text, isWarn=false) {
  const el = document.getElementById('msg');
  el.textContent = text || '';
  el.classList.toggle('warn', !!isWarn);
}
function applyI18n() {
  document.title = t('title');
  document.documentElement.lang = currentLang === 'en' ? 'en' : 'zh-CN';
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.getElementById('lang-zh').classList.toggle('active', currentLang === 'zh');
  document.getElementById('lang-en').classList.toggle('active', currentLang === 'en');
  renderGroupSelect();
  renderKBList();
  renderKBKeySelect();
  renderVersionSelect();
}
function setLang(lang) {
  currentLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('nova_lang', currentLang);
  applyI18n();
}
async function api(url, options={}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = {'Content-Type':'application/json'};
  if (csrfToken && ['POST','PUT','PATCH','DELETE'].includes(method)) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  const res = await fetch(url, {headers, ...options});
  let data = {};
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}
async function loadCsrfToken() {
  const res = await fetch('/api/csrf');
  if (!res.ok) throw new Error('csrf');
  const data = await res.json();
  csrfToken = data.csrf_token || '';
}
function parseJSON(raw, fallback) {
  const text = (raw || '').trim();
  if (!text) return fallback;
  try {
    return JSON.parse(text);
  } catch (_) {
    return text;
  }
}
function stringify(value) {
  if (value === null || value === undefined) return 'null';
  return JSON.stringify(value, null, 2);
}
function renderKBList() {
  const box = document.getElementById('kb-list');
  box.innerHTML = '';
  if (!kbList.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = t('kb_empty');
    box.appendChild(empty);
    return;
  }
  const activeKey = document.getElementById('kb-key-select').value;
  for (const kb of kbList) {
    const div = document.createElement('div');
    div.className = 'item' + (activeKey === kb.kb_key ? ' active' : '');
    div.onclick = async () => {
      document.getElementById('kb-key-select').value = kb.kb_key;
      await changeKBKey();
    };
    const shared = me && kb.owner_username && kb.owner_username !== me.username;
    const sharedText = shared ? ` · ${t('shared_from')}: ${kb.owner_username}` : '';
    div.innerHTML = `<div class="name">${kb.kb_name}</div><div class="meta">${kb.kb_key} · v${kb.version}${sharedText}</div>`;
    box.appendChild(div);
  }
}
function renderGroupSelect() {
  const select = document.getElementById('kb-share-group');
  if (!select) return;
  const visibility = document.getElementById('kb-visibility')?.value || 'private';
  const requiredType = visibility === 'company' ? 'company' : (visibility === 'task' ? 'task' : null);
  const previous = select.value;
  select.innerHTML = '';
  const empty = document.createElement('option');
  empty.value = '';
  empty.textContent = t('no_group_needed');
  select.appendChild(empty);
  const eligibleGroups = requiredType ? myGroups.filter((g) => g.group_type === requiredType) : myGroups;
  for (const g of eligibleGroups) {
    const option = document.createElement('option');
    option.value = String(g.id);
    const typeLabel = g.group_type === 'company' ? t('visibility_company') : t('visibility_task');
    option.textContent = `${g.name} (${typeLabel})`;
    option.dataset.groupType = g.group_type;
    select.appendChild(option);
  }
  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  }
}
function onKBVisibilityChange() {
  renderGroupSelect();
  const visibility = document.getElementById('kb-visibility').value;
  const groupSelect = document.getElementById('kb-share-group');
  if (visibility === 'private') {
    groupSelect.disabled = true;
    groupSelect.value = '';
  } else {
    groupSelect.disabled = false;
  }
}
function renderKBKeySelect() {
  const select = document.getElementById('kb-key-select');
  const previous = select.value;
  select.innerHTML = '';
  const empty = document.createElement('option');
  empty.value = '';
  empty.textContent = t('none');
  select.appendChild(empty);
  for (const kb of kbList) {
    const option = document.createElement('option');
    option.value = kb.kb_key;
    option.textContent = `${kb.kb_name} (${kb.kb_key})`;
    select.appendChild(option);
  }
  if ([...select.options].some((opt) => opt.value === previous)) select.value = previous;
}
function renderVersionSelect() {
  const select = document.getElementById('kb-version-select-page');
  const previous = select.value;
  select.innerHTML = '';
  if (!kbVersions.length) {
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = t('none');
    select.appendChild(empty);
    return;
  }
  for (const item of kbVersions) {
    const option = document.createElement('option');
    option.value = String(item.version);
    option.textContent = `v${item.version}`;
    select.appendChild(option);
  }
  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  }
}
function fillForm(data) {
  document.getElementById('kb-key-input').value = data.kb_key || '';
  document.getElementById('kb-name').value = data.kb_name || '';
  document.getElementById('kb-brand-voice').value = data.brand_voice || '';
  document.getElementById('kb-positioning').value = stringify(data.positioning || {});
  document.getElementById('kb-glossary').value = stringify(data.glossary || []);
  document.getElementById('kb-forbidden').value = stringify(data.forbidden_words || []);
  document.getElementById('kb-required').value = stringify(data.required_terms || []);
  document.getElementById('kb-claims').value = stringify(data.claims_policy || {});
  document.getElementById('kb-examples').value = stringify(data.examples ?? null);
  document.getElementById('kb-notes').value = data.notes || '';
  document.getElementById('kb-visibility').value = data.visibility || 'private';
  document.getElementById('kb-share-group').value = data.share_group_id ? String(data.share_group_id) : '';
  onKBVisibilityChange();
}
function collectPayload() {
  return {
    kb_name: document.getElementById('kb-name').value.trim() || null,
    brand_voice: document.getElementById('kb-brand-voice').value.trim() || null,
    visibility: document.getElementById('kb-visibility').value,
    share_group_id: document.getElementById('kb-share-group').value ? Number(document.getElementById('kb-share-group').value) : null,
    positioning: parseJSON(document.getElementById('kb-positioning').value, {}),
    glossary: parseJSON(document.getElementById('kb-glossary').value, []),
    forbidden_words: parseJSON(document.getElementById('kb-forbidden').value, []),
    required_terms: parseJSON(document.getElementById('kb-required').value, []),
    claims_policy: parseJSON(document.getElementById('kb-claims').value, {}),
    examples: parseJSON(document.getElementById('kb-examples').value, null),
    notes: document.getElementById('kb-notes').value.trim() || null
  };
}
async function refreshKBList() {
  kbList = await api('/api/kb/list');
  renderKBList();
  renderKBKeySelect();
}
async function loadMyGroups() {
  myGroups = await api('/api/groups/mine');
  renderGroupSelect();
}
async function changeKBKey() {
  const key = document.getElementById('kb-key-select').value;
  renderKBList();
  if (!key) {
    kbVersions = [];
    renderVersionSelect();
    return;
  }
  kbVersions = await api(`/api/kb/${encodeURIComponent(key)}/versions`);
  renderVersionSelect();
  document.getElementById('kb-version-select-page').value = String(kbVersions[0].version);
  await loadSelectedVersion();
}
async function loadSelectedVersion() {
  const key = document.getElementById('kb-key-select').value;
  const version = document.getElementById('kb-version-select-page').value;
  if (!key || !version) return;
  const data = await api(`/api/kb/${encodeURIComponent(key)}?version=${version}`);
  fillForm(data);
}
async function createVersion() {
  try {
    const rawKey = document.getElementById('kb-key-input').value.trim() || document.getElementById('kb-key-select').value;
    if (!rawKey) throw new Error(t('required_key'));
    const payload = collectPayload();
    payload.kb_key = rawKey;
    const data = await api('/api/kb', {method:'POST', body:JSON.stringify(payload)});
    await refreshKBList();
    document.getElementById('kb-key-select').value = data.kb_key;
    await changeKBKey();
    document.getElementById('kb-version-select-page').value = String(data.version);
    await loadSelectedVersion();
    setMsg(t('create_ok'));
  } catch (e) {
    setMsg(`${t('load_failed')}: ${e.message}`, true);
  }
}
async function updateVersion() {
  try {
    const key = document.getElementById('kb-key-select').value;
    const version = document.getElementById('kb-version-select-page').value;
    if (!key || !version) throw new Error(t('required_key'));
    const payload = collectPayload();
    await api(`/api/kb/${encodeURIComponent(key)}/${version}`, {method:'PUT', body:JSON.stringify(payload)});
    await refreshKBList();
    setMsg(t('update_ok'));
  } catch (e) {
    const msg = e instanceof SyntaxError ? t('invalid_json') : e.message;
    setMsg(`${t('load_failed')}: ${msg}`, true);
  }
}
async function deleteVersion() {
  try {
    const key = document.getElementById('kb-key-select').value;
    const version = document.getElementById('kb-version-select-page').value;
    if (!key || !version) throw new Error(t('required_key'));
    if (!confirm(t('delete_confirm'))) return;
    await api(`/api/kb/${encodeURIComponent(key)}/${version}`, {method:'DELETE'});
    await refreshKBList();
    kbVersions = [];
    renderVersionSelect();
    setMsg(t('delete_ok'));
  } catch (e) {
    setMsg(`${t('load_failed')}: ${e.message}`, true);
  }
}
async function logout() { await api('/logout', {method:'POST'}); location.href = '/'; }
function backToApp() { location.href = '/app'; }

(async function init() {
  applyI18n();
  try {
    await loadCsrfToken();
    me = await api('/api/me');
    await loadMyGroups();
    await refreshKBList();
  } catch {
    location.href = '/';
  }
})();
</script>
</body>
</html>
"""


GROUPS_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Marketing Copilot - Groups</title>
  <style>
    body { margin:0; font-family:"IBM Plex Sans","Segoe UI",sans-serif; background:#f2f6ff; color:#142136; }
    .wrap { max-width:1180px; margin:16px auto; padding:0 12px; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:12px; }
    .toolbar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    .toolbar button.active { background:#0a67d3; color:#fff; border-color:#0a67d3; }
    .layout { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .card { background:#fff; border:1px solid #d6dfec; border-radius:14px; padding:12px; box-shadow:0 8px 20px rgba(16,32,62,.08); }
    h2, h3 { margin:0 0 10px; }
    .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px; }
    input, select, button { padding:8px 10px; border:1px solid #d6dfec; border-radius:10px; background:#fff; }
    button { cursor:pointer; font-weight:600; }
    .list { display:flex; flex-direction:column; gap:8px; max-height:260px; overflow:auto; }
    .item { border:1px solid #d6dfec; border-radius:10px; padding:8px; }
    .meta { font-size:12px; color:#5b6b80; margin-top:4px; }
    .small { font-size:12px; color:#5b6b80; }
    .ok { color:#0f766e; }
    .warn { color:#b91c1c; }
    @media (max-width: 980px) { .layout { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <h2 data-i18n="title">组管理</h2>
      <div class="toolbar">
        <button id="lang-zh" onclick="setLang('zh')">中文</button>
        <button id="lang-en" onclick="setLang('en')">EN</button>
        <button onclick="backToApp()" data-i18n="back">返回聊天</button>
        <button onclick="logout()" data-i18n="logout">退出</button>
      </div>
    </div>

    <div class="layout">
      <div class="card">
        <h3 data-i18n="create_group">创建组</h3>
        <div class="row">
          <input id="new-group-name" data-i18n-placeholder="group_name" placeholder="组名称" />
          <select id="new-group-type">
            <option value="company" data-i18n="company_group">公司组</option>
            <option value="task" data-i18n="task_group">任务小组</option>
          </select>
          <button onclick="createGroup()" data-i18n="create">创建</button>
        </div>
        <div id="create-msg" class="small"></div>

        <h3 style="margin-top:14px" data-i18n="my_groups">我的组</h3>
        <div class="row">
          <select id="manage-group-select" onchange="loadManageGroup()"></select>
        </div>
        <div id="my-groups" class="list"></div>
      </div>

      <div class="card">
        <h3 data-i18n="all_groups">可加入的组</h3>
        <div id="all-groups" class="list"></div>
        <h3 style="margin-top:14px" data-i18n="invites">我的邀请</h3>
        <div id="invites" class="list"></div>
      </div>

      <div class="card">
        <h3 data-i18n="members">组成员</h3>
        <div id="members" class="list"></div>
      </div>

      <div class="card">
        <h3 data-i18n="requests">待审批请求</h3>
        <div id="requests" class="list"></div>
        <div class="row" style="margin-top:10px">
          <input id="invite-username" data-i18n-placeholder="invite_user" placeholder="邀请用户名" />
          <button onclick="inviteUser()" data-i18n="invite">邀请</button>
        </div>
        <div class="row">
          <input id="transfer-user-id" data-i18n-placeholder="transfer_user_id" placeholder="新管理员 user_id" />
          <button onclick="transferAdmin()" data-i18n="transfer_admin">转移管理员</button>
        </div>
        <div id="manage-msg" class="small"></div>
      </div>
    </div>
  </div>

<script>
const I18N = {
  zh: {
    title: '组管理',
    back: '返回聊天',
    logout: '退出',
    create_group: '创建组',
    group_name: '组名称',
    company_group: '公司组',
    task_group: '任务小组',
    create: '创建',
    my_groups: '我的组',
    all_groups: '可加入的组',
    invites: '我的邀请',
    members: '组成员',
    requests: '待审批请求',
    invite_user: '邀请用户名',
    invite: '邀请',
    transfer_user_id: '新管理员 user_id',
    transfer_admin: '转移管理员',
    join: '申请加入',
    approve: '批准',
    reject: '拒绝',
    accept: '接受',
    no_data: '暂无数据',
    admin: '管理员',
    member: '成员',
    approved: '已批准',
    pending: '待审批',
    invited: '已邀请',
    save_ok: '操作成功',
    save_fail: '操作失败'
  },
  en: {
    title: 'Group Management',
    back: 'Back to Chat',
    logout: 'Log Out',
    create_group: 'Create Group',
    group_name: 'Group name',
    company_group: 'Company Group',
    task_group: 'Task Group',
    create: 'Create',
    my_groups: 'My Groups',
    all_groups: 'Discover Groups',
    invites: 'My Invitations',
    members: 'Members',
    requests: 'Pending Requests',
    invite_user: 'Username to invite',
    invite: 'Invite',
    transfer_user_id: 'New admin user_id',
    transfer_admin: 'Transfer Admin',
    join: 'Request Join',
    approve: 'Approve',
    reject: 'Reject',
    accept: 'Accept',
    no_data: 'No data',
    admin: 'Admin',
    member: 'Member',
    approved: 'Approved',
    pending: 'Pending',
    invited: 'Invited',
    save_ok: 'Operation succeeded',
    save_fail: 'Operation failed'
  }
};

let currentLang = localStorage.getItem('nova_lang') || 'zh';
let me = null;
let myGroups = [];
let allGroups = [];
let csrfToken = '';

function t(key) { return (I18N[currentLang] && I18N[currentLang][key]) || key; }
function setLang(lang) {
  currentLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('nova_lang', currentLang);
  applyI18n();
  renderAll();
}
function applyI18n() {
  document.title = t('title');
  document.documentElement.lang = currentLang === 'en' ? 'en' : 'zh-CN';
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.getElementById('lang-zh').classList.toggle('active', currentLang === 'zh');
  document.getElementById('lang-en').classList.toggle('active', currentLang === 'en');
}
async function api(url, options={}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = {'Content-Type':'application/json'};
  if (csrfToken && ['POST','PUT','PATCH','DELETE'].includes(method)) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  const res = await fetch(url, {headers, ...options});
  let data = {};
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}
async function loadCsrfToken() {
  const res = await fetch('/api/csrf');
  if (!res.ok) throw new Error('csrf');
  const data = await res.json();
  csrfToken = data.csrf_token || '';
}
function roleLabel(role) { return role === 'admin' ? t('admin') : t('member'); }
function statusLabel(status) {
  if (status === 'approved') return t('approved');
  if (status === 'pending') return t('pending');
  if (status === 'invited') return t('invited');
  return status || '';
}
function renderAll() {
  renderMyGroups();
  renderDiscoverGroups();
}
function renderMyGroups() {
  const box = document.getElementById('my-groups');
  const select = document.getElementById('manage-group-select');
  box.innerHTML = '';
  select.innerHTML = '';
  if (!myGroups.length) {
    box.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    return;
  }
  for (const g of myGroups) {
    const item = document.createElement('div');
    item.className = 'item';
    item.innerHTML = `<div><strong>${g.name}</strong> (${g.group_type})</div><div class="meta">${roleLabel(g.role)} · ${statusLabel(g.status)}</div>`;
    box.appendChild(item);
    const opt = document.createElement('option');
    opt.value = String(g.id);
    opt.textContent = `${g.name} (${g.group_type})`;
    select.appendChild(opt);
  }
}
function renderDiscoverGroups() {
  const box = document.getElementById('all-groups');
  box.innerHTML = '';
  if (!allGroups.length) {
    box.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    return;
  }
  for (const g of allGroups) {
    const item = document.createElement('div');
    item.className = 'item';
    const status = g.my_status ? statusLabel(g.my_status) : '';
    item.innerHTML = `
      <div><strong>${g.name}</strong> (${g.group_type})</div>
      <div class="meta">members: ${g.approved_member_count}${status ? ` · ${status}` : ''}</div>
      <div class="row" style="margin-top:6px">
        <button onclick="joinGroup(${g.id})">${t('join')}</button>
      </div>`;
    box.appendChild(item);
  }
}
async function refreshData() {
  [me, myGroups, allGroups] = await Promise.all([
    api('/api/me'),
    api('/api/groups/mine'),
    api('/api/groups'),
  ]);
  await loadInvites();
  renderAll();
  await loadManageGroup();
}
async function loadInvites() {
  const invites = await api('/api/groups/invitations');
  const box = document.getElementById('invites');
  box.innerHTML = '';
  if (!invites.length) {
    box.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    return;
  }
  for (const inv of invites) {
    const item = document.createElement('div');
    item.className = 'item';
    item.innerHTML = `
      <div><strong>${inv.name}</strong> (${inv.group_type})</div>
      <div class="meta">${inv.invited_by || ''}</div>
      <div class="row" style="margin-top:6px">
        <button onclick="acceptInvite(${inv.group_id})">${t('accept')}</button>
        <button onclick="rejectInvite(${inv.group_id})">${t('reject')}</button>
      </div>`;
    box.appendChild(item);
  }
}
async function createGroup() {
  const name = document.getElementById('new-group-name').value.trim();
  const group_type = document.getElementById('new-group-type').value;
  const msg = document.getElementById('create-msg');
  try {
    await api('/api/groups', {method:'POST', body: JSON.stringify({name, group_type})});
    msg.textContent = t('save_ok');
    msg.className = 'small ok';
    await refreshData();
  } catch (e) {
    msg.textContent = `${t('save_fail')}: ${e.message}`;
    msg.className = 'small warn';
  }
}
async function joinGroup(groupId) {
  try {
    await api(`/api/groups/${groupId}/join`, {method:'POST'});
    await refreshData();
  } catch (e) {
    alert(e.message);
  }
}
async function acceptInvite(groupId) {
  await api(`/api/groups/${groupId}/invitations/accept`, {method:'POST'});
  await refreshData();
}
async function rejectInvite(groupId) {
  await api(`/api/groups/${groupId}/invitations/reject`, {method:'POST'});
  await refreshData();
}
async function loadManageGroup() {
  const groupIdRaw = document.getElementById('manage-group-select').value;
  const membersBox = document.getElementById('members');
  const reqBox = document.getElementById('requests');
  membersBox.innerHTML = '';
  reqBox.innerHTML = '';
  if (!groupIdRaw) {
    membersBox.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    reqBox.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    return;
  }
  const groupId = Number(groupIdRaw);
  const [members, requests] = await Promise.all([
    api(`/api/groups/${groupId}/members`),
    api(`/api/groups/${groupId}/requests`)
  ]);
  if (!members.length) {
    membersBox.innerHTML = `<div class="item small">${t('no_data')}</div>`;
  } else {
    for (const m of members) {
      const item = document.createElement('div');
      item.className = 'item';
      item.innerHTML = `<div><strong>${m.username}</strong> (#${m.user_id})</div><div class="meta">${roleLabel(m.role)} · ${statusLabel(m.status)}</div>`;
      membersBox.appendChild(item);
    }
  }
  if (!requests.length) {
    reqBox.innerHTML = `<div class="item small">${t('no_data')}</div>`;
  } else {
    for (const r of requests) {
      const item = document.createElement('div');
      item.className = 'item';
      item.innerHTML = `
        <div><strong>${r.username}</strong> (#${r.user_id})</div>
        <div class="meta">${statusLabel(r.status)}</div>
        <div class="row" style="margin-top:6px">
          <button onclick="approveRequest(${groupId}, ${r.user_id})">${t('approve')}</button>
          <button onclick="rejectRequest(${groupId}, ${r.user_id})">${t('reject')}</button>
        </div>`;
      reqBox.appendChild(item);
    }
  }
}
async function approveRequest(groupId, userId) {
  await api(`/api/groups/${groupId}/requests/${userId}/approve`, {method:'POST'});
  await loadManageGroup();
}
async function rejectRequest(groupId, userId) {
  await api(`/api/groups/${groupId}/requests/${userId}/reject`, {method:'POST'});
  await loadManageGroup();
}
async function inviteUser() {
  const groupIdRaw = document.getElementById('manage-group-select').value;
  if (!groupIdRaw) return;
  const username = document.getElementById('invite-username').value.trim();
  await api(`/api/groups/${groupIdRaw}/invite`, {method:'POST', body: JSON.stringify({username})});
  await loadManageGroup();
}
async function transferAdmin() {
  const groupIdRaw = document.getElementById('manage-group-select').value;
  if (!groupIdRaw) return;
  const new_admin_user_id = Number(document.getElementById('transfer-user-id').value);
  if (!new_admin_user_id) return;
  const msg = document.getElementById('manage-msg');
  try {
    await api(`/api/groups/${groupIdRaw}/transfer-admin`, {
      method:'POST',
      body: JSON.stringify({new_admin_user_id})
    });
    msg.textContent = t('save_ok');
    msg.className = 'small ok';
    await refreshData();
  } catch (e) {
    msg.textContent = `${t('save_fail')}: ${e.message}`;
    msg.className = 'small warn';
  }
}
async function logout() { await api('/logout', {method:'POST'}); location.href = '/'; }
function backToApp() { location.href = '/app'; }

(async function init() {
  applyI18n();
  try {
    await loadCsrfToken();
    await refreshData();
  } catch {
    location.href = '/';
  }
})();
</script>
</body>
</html>
"""


ADMIN_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Marketing Copilot - Admin</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
    :root {
      --bg:#eef4ff;
      --line:#d6dfec;
      --line-strong:#bfcee3;
      --txt:#0f1b2d;
      --muted:#55657d;
      --accent:#0a67d3;
      --ok:#0f766e;
      --shadow:0 18px 36px rgba(16,32,62,.12);
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      font-family:"IBM Plex Sans","Segoe UI",sans-serif;
      background:
        radial-gradient(920px 520px at 0% -10%,#d8e7ff 0%,transparent 58%),
        radial-gradient(980px 560px at 106% -16%,#d7f3e8 0%,transparent 62%),
        linear-gradient(160deg,#edf4ff,#f5fbf6);
      color:var(--txt);
    }
    .wrap { max-width:1180px; margin:18px auto; padding:0 14px; }
    .top { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; gap:8px; }
    .top h2 { margin:0; font-family:"Sora","IBM Plex Sans",sans-serif; }
    .toolbar { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
    .toolbar button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
    .card {
      background:rgba(255,255,255,.88);
      border:1px solid var(--line);
      border-radius:18px;
      padding:14px;
      margin-bottom:14px;
      box-shadow:var(--shadow);
      backdrop-filter: blur(8px);
    }
    .card h3 { margin:0 0 10px; font-family:"Sora","IBM Plex Sans",sans-serif; font-size:17px; }
    .create-form {
      display:grid;
      grid-template-columns:minmax(180px,1fr) minmax(220px,1fr) minmax(150px,170px) auto;
      gap:8px;
      align-items:center;
    }
    input, select, button {
      padding:9px 10px;
      border:1px solid var(--line);
      border-radius:11px;
      background:#fff;
      color:var(--txt);
      font-family:inherit;
      transition:.16s ease;
    }
    input:focus, select:focus {
      outline:none;
      border-color:var(--accent);
      box-shadow:0 0 0 3px rgba(10,103,211,.14);
    }
    button {
      cursor:pointer;
      font-weight:600;
      white-space:nowrap;
    }
    button:hover { border-color:var(--line-strong); transform:translateY(-1px); box-shadow:0 8px 14px rgba(15,30,60,.07); }
    .table-wrap { overflow:auto; border-radius:12px; }
    table { width:100%; min-width:760px; border-collapse:separate; border-spacing:0; overflow:hidden; border-radius:12px; border:1px solid var(--line); }
    thead th {
      background:#f7fbff;
      color:#38465a;
      font-size:12px;
      text-transform:uppercase;
      letter-spacing:.2px;
    }
    th, td { padding:10px; border-bottom:1px solid #edf1f7; text-align:left; font-size:13px; }
    tbody tr:last-child td { border-bottom:0; }
    tbody tr:hover td { background:#fcfeff; }
    td button { margin-right:6px; font-size:12px; padding:7px 9px; }
    .small {
      font-size:12px;
      color:var(--ok);
      margin-top:8px;
      min-height:18px;
      background:#f3fdf9;
      border:1px solid #bde9d9;
      border-radius:10px;
      padding:6px 10px;
      width:max-content;
      max-width:100%;
    }
    *::-webkit-scrollbar { width:10px; height:10px; }
    *::-webkit-scrollbar-thumb { background:#c7d5e8; border-radius:999px; border:2px solid rgba(255,255,255,.9); }
    *::-webkit-scrollbar-track { background:transparent; }
    @media (max-width: 980px) {
      .create-form { grid-template-columns:1fr; }
      .small { width:100%; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <h2 data-i18n="title">用户管理</h2>
      <div class="toolbar">
        <button id="lang-zh" onclick="setLang('zh')">中文</button>
        <button id="lang-en" onclick="setLang('en')">EN</button>
        <button onclick="back()" data-i18n="back">返回聊天</button>
        <button onclick="logout()" data-i18n="logout">退出</button>
      </div>
    </div>

    <div class="card">
      <h3 data-i18n="create_user">创建用户</h3>
      <div class="create-form">
        <input id="new-name" data-i18n-placeholder="username" placeholder="用户名" />
        <input id="new-pass" data-i18n-placeholder="password" placeholder="密码" type="password" />
        <select id="new-admin">
          <option value="false" data-i18n="normal_user">普通用户</option>
          <option value="true" data-i18n="admin_user">管理员</option>
        </select>
        <button onclick="createUser()" data-i18n="create">创建</button>
      </div>
      <div class="small" id="create-msg"></div>
    </div>

    <div class="card">
      <h3 data-i18n="user_list">用户列表</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th data-i18n="th_username">用户名</th>
              <th data-i18n="th_role">角色</th>
              <th data-i18n="th_status">状态</th>
              <th data-i18n="th_created_at">创建时间</th>
              <th data-i18n="th_action">操作</th>
            </tr>
          </thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
    </div>
  </div>

<script>
const I18N = {
  zh: {
    page_title: '用户管理',
    title: '用户管理',
    back: '返回聊天',
    logout: '退出',
    create_user: '创建用户',
    username: '用户名',
    password: '密码',
    normal_user: '普通用户',
    admin_user: '管理员',
    create: '创建',
    user_list: '用户列表',
    th_username: '用户名',
    th_role: '角色',
    th_status: '状态',
    th_created_at: '创建时间',
    th_action: '操作',
    role_admin: '管理员',
    role_user: '普通用户',
    status_active: '启用',
    status_disabled: '禁用',
    action_disable: '禁用',
    action_enable: '启用',
    action_reset: '重置密码',
    created_success: '创建成功',
    created_failed: '创建失败',
    request_failed: '请求失败',
    prompt_new_password: '输入新密码（至少8位）',
    reset_ok: '密码已重置'
  },
  en: {
    page_title: 'User Management',
    title: 'User Management',
    back: 'Back to Chat',
    logout: 'Log Out',
    create_user: 'Create User',
    username: 'Username',
    password: 'Password',
    normal_user: 'Standard User',
    admin_user: 'Admin',
    create: 'Create',
    user_list: 'Users',
    th_username: 'Username',
    th_role: 'Role',
    th_status: 'Status',
    th_created_at: 'Created At',
    th_action: 'Actions',
    role_admin: 'Admin',
    role_user: 'Standard',
    status_active: 'Active',
    status_disabled: 'Disabled',
    action_disable: 'Disable',
    action_enable: 'Enable',
    action_reset: 'Reset Password',
    created_success: 'Created successfully',
    created_failed: 'Create failed',
    request_failed: 'Request failed',
    prompt_new_password: 'Enter new password (at least 8 characters)',
    reset_ok: 'Password reset successfully'
  }
};

let currentLang = localStorage.getItem('nova_lang') || 'zh';

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || key;
}

function applyI18n() {
  document.title = t('page_title');
  document.documentElement.lang = currentLang === 'en' ? 'en' : 'zh-CN';
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.getElementById('lang-zh').classList.toggle('active', currentLang === 'zh');
  document.getElementById('lang-en').classList.toggle('active', currentLang === 'en');
}

function setLang(lang) {
  currentLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('nova_lang', currentLang);
  applyI18n();
  loadUsers();
}

async function api(url, options={}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = {'Content-Type':'application/json'};
  if (csrfToken && ['POST','PUT','PATCH','DELETE'].includes(method)) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  const res = await fetch(url, {headers, ...options});
  let data = {};
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error(data.detail || t('request_failed'));
  return data;
}
async function loadCsrfToken() {
  const res = await fetch('/api/csrf');
  if (!res.ok) throw new Error('csrf');
  const data = await res.json();
  csrfToken = data.csrf_token || '';
}

function fmt(ts) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

async function loadUsers() {
  const users = await api('/api/admin/users');
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  for (const u of users) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${u.id}</td>
      <td>${u.username}</td>
      <td>${u.is_admin ? t('role_admin') : t('role_user')}</td>
      <td>${u.is_active ? t('status_active') : t('status_disabled')}</td>
      <td>${fmt(u.created_at)}</td>
      <td>
        <button onclick="toggleUser(${u.id}, ${u.is_active})">${u.is_active ? t('action_disable') : t('action_enable')}</button>
        <button onclick="resetPwd(${u.id})">${t('action_reset')}</button>
      </td>
    `;
    rows.appendChild(tr);
  }
}

async function createUser() {
  const username = document.getElementById('new-name').value.trim();
  const password = document.getElementById('new-pass').value;
  const is_admin = document.getElementById('new-admin').value === 'true';
  const msg = document.getElementById('create-msg');
  try {
    await api('/api/admin/users', {method:'POST', body:JSON.stringify({username,password,is_admin})});
    msg.textContent = t('created_success');
    await loadUsers();
  } catch (e) {
    msg.textContent = `${t('created_failed')}: ${e.message}`;
  }
}

async function toggleUser(userId, current) {
  await api(`/api/admin/users/${userId}/status`, {method:'POST', body:JSON.stringify({is_active: !current})});
  await loadUsers();
}

async function resetPwd(userId) {
  const newPwd = prompt(t('prompt_new_password'));
  if (!newPwd) return;
  await api(`/api/admin/users/${userId}/password`, {method:'POST', body:JSON.stringify({new_password:newPwd})});
  alert(t('reset_ok'));
}

async function logout() { await api('/logout', {method:'POST'}); location.href = '/'; }
function back() { location.href = '/app'; }

(async function init() {
  applyI18n();
  try {
    await loadCsrfToken();
    await loadUsers();
  } catch {
    location.href = '/app';
  }
})();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    if current_user(request):
        return RedirectResponse(url="/app", status_code=302)
    return HTMLResponse(AUTH_HTML)


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
    except sqlite3.IntegrityError:
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
    return HTMLResponse(APP_HTML)


@app.get("/kb", response_class=HTMLResponse)
def kb_page(request: Request) -> Any:
    if not current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return HTMLResponse(KB_HTML)


@app.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request) -> Any:
    if not current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return HTMLResponse(GROUPS_HTML)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request) -> Any:
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    if user["is_admin"] == 0:
        return RedirectResponse(url="/app", status_code=302)
    return HTMLResponse(ADMIN_HTML)


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
                g.name COLLATE NOCASE ASC
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
                ORDER BY g.name COLLATE NOCASE ASC
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
                ORDER BY g.group_type ASC, g.name COLLATE NOCASE ASC
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
            ORDER BY g.group_type ASC, g.name COLLATE NOCASE ASC
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
    now = now_utc().isoformat()
    with db_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO groups (name, group_type, created_by, created_at) VALUES (?, ?, ?, ?)",
                (name[:80], group_type, user["id"], now),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Group with same name and type already exists")
        group_id = cur.lastrowid
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
            WHERE gm.group_id = ?
            ORDER BY CASE gm.role WHEN 'admin' THEN 0 ELSE 1 END, u.username COLLATE NOCASE ASC
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
            WHERE gm.group_id = ? AND gm.status IN ('pending', 'invited')
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
        if row["status"] == "approved":
            raise HTTPException(status_code=400, detail="Cannot reject an approved member")
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


@app.get("/api/experiments")
def list_experiments(request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, owner_user_id, conversation_id, title, hypothesis, status,
                   traffic_allocation_json, result_json, created_at, updated_at
            FROM experiments
            WHERE owner_user_id = ?
            ORDER BY updated_at DESC
            """,
            (user["id"],),
        ).fetchall()
    data = []
    for row in rows:
        item = dict(row)
        item["traffic_allocation"] = _json_loads(item.pop("traffic_allocation_json"), {})
        item["result"] = _json_loads(item.pop("result_json"), {})
        data.append(item)
    return data


@app.post("/api/experiments")
def create_experiment(body: ExperimentCreateInput, request: Request) -> Any:
    user = must_login(request)
    now = now_utc().isoformat()
    conversation_id = body.conversation_id
    if conversation_id is not None:
        conversation_owner_or_404(user["id"], conversation_id)
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO experiments (
                owner_user_id, conversation_id, title, hypothesis, status,
                traffic_allocation_json, result_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'draft', ?, '{}', ?, ?)
            """,
            (
                user["id"],
                conversation_id,
                body.title.strip()[:160],
                body.hypothesis.strip()[:2000],
                _json_dumps(body.traffic_allocation if isinstance(body.traffic_allocation, dict) else {}),
                now,
                now,
            ),
        )
        experiment_id = cur.lastrowid
    return {"ok": True, "id": experiment_id}


@app.get("/api/experiments/{experiment_id}")
def get_experiment(experiment_id: int, request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        exp = conn.execute(
            """
            SELECT id, owner_user_id, conversation_id, title, hypothesis, status,
                   traffic_allocation_json, result_json, created_at, updated_at
            FROM experiments
            WHERE id = ? AND owner_user_id = ?
            """,
            (experiment_id, user["id"]),
        ).fetchone()
        if not exp:
            raise HTTPException(status_code=404, detail="Experiment not found")
        variants = conn.execute(
            """
            SELECT id, variant_key, content, created_at
            FROM experiment_variants
            WHERE experiment_id = ?
            ORDER BY id ASC
            """,
            (experiment_id,),
        ).fetchall()
    item = dict(exp)
    item["traffic_allocation"] = _json_loads(item.pop("traffic_allocation_json"), {})
    item["result"] = _json_loads(item.pop("result_json"), {})
    item["variants"] = [dict(v) for v in variants]
    return item


@app.post("/api/experiments/{experiment_id}/variants")
def upsert_experiment_variant(experiment_id: int, body: ExperimentVariantInput, request: Request) -> Any:
    user = must_login(request)
    key = body.variant_key.strip().lower()
    now = now_utc().isoformat()
    with db_conn() as conn:
        exp = conn.execute(
            "SELECT id FROM experiments WHERE id = ? AND owner_user_id = ?",
            (experiment_id, user["id"]),
        ).fetchone()
        if not exp:
            raise HTTPException(status_code=404, detail="Experiment not found")
        conn.execute(
            """
            INSERT INTO experiment_variants (experiment_id, variant_key, content, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(experiment_id, variant_key) DO UPDATE SET content = excluded.content
            """,
            (experiment_id, key[:40], body.content.strip()[:10000], now),
        )
        conn.execute(
            "UPDATE experiments SET updated_at = ? WHERE id = ?",
            (now, experiment_id),
        )
    return {"ok": True}


@app.patch("/api/experiments/{experiment_id}/status")
def update_experiment_status(experiment_id: int, body: ExperimentStatusInput, request: Request) -> Any:
    user = must_login(request)
    status = body.status.strip().lower()
    if status not in {"draft", "running", "paused", "completed", "archived"}:
        raise HTTPException(status_code=400, detail="Unsupported experiment status")
    now = now_utc().isoformat()
    with db_conn() as conn:
        exp = conn.execute(
            "SELECT id FROM experiments WHERE id = ? AND owner_user_id = ?",
            (experiment_id, user["id"]),
        ).fetchone()
        if not exp:
            raise HTTPException(status_code=404, detail="Experiment not found")
        conn.execute(
            """
            UPDATE experiments
            SET status = ?, result_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, _json_dumps(body.result if isinstance(body.result, dict) else {}), now, experiment_id),
        )
    return {"ok": True}


@app.get("/api/kb/list")
def list_brand_kb(request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        rows = conn.execute(
            """
            WITH visible AS (
                SELECT b.*, u.username AS owner_username, g.name AS share_group_name
                FROM brand_kb_versions b
                LEFT JOIN users u ON u.id = b.owner_id
                LEFT JOIN groups g ON g.id = b.share_group_id
                LEFT JOIN group_memberships gm
                  ON gm.group_id = b.share_group_id AND gm.user_id = ? AND gm.status = 'approved'
                WHERE b.owner_id = ?
                   OR (b.visibility IN ('task', 'company') AND gm.user_id IS NOT NULL)
            ),
            latest AS (
                SELECT kb_key, MAX(version) AS latest_version
                FROM visible
                GROUP BY kb_key
            )
            SELECT v.kb_key, v.kb_name, v.version, v.owner_id, v.owner_username, v.visibility,
                   v.share_group_id, v.share_group_name, v.brand_voice, v.created_at,
                   v.positioning_json, v.glossary_json, v.forbidden_words_json, v.required_terms_json,
                   v.claims_policy_json, v.examples_json, v.notes
            FROM visible v
            JOIN latest l ON l.kb_key = v.kb_key AND l.latest_version = v.version
            ORDER BY v.kb_name COLLATE NOCASE ASC, v.kb_key ASC
            """
            ,
            (user["id"], user["id"]),
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
        raise HTTPException(status_code=404, detail="KB not found")
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
        raise HTTPException(status_code=404, detail="KB not found")
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
        raise HTTPException(status_code=404, detail="KB version not found")
    if existing["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only owner can update this KB version")

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
            raise HTTPException(status_code=404, detail="KB version not found")
        if exists["owner_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Only owner can delete this KB version")
        in_use = conn.execute(
            "SELECT id FROM conversations WHERE kb_key = ? AND kb_version = ? LIMIT 1",
            (key, version),
        ).fetchone()
        if in_use:
            raise HTTPException(status_code=400, detail="KB version is currently used by a conversation")
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
            SELECT c.id, c.user_id, c.title, c.model_id, c.task_mode, c.visibility, c.share_group_id,
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
    visibility, share_group_id = _validate_share_group_for_user(user["id"], body.visibility, body.share_group_id)
    default_title = "新营销任务" if task_mode == "marketing" else "新对话"
    title = (body.title or default_title).strip() or default_title
    now = now_utc().isoformat()
    model_id = DEFAULT_MODEL_ID
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO conversations (user_id, title, model_id, task_mode, visibility, share_group_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user["id"], title[:120], model_id, task_mode, visibility, share_group_id, now, now),
        )
        conv_id = cur.lastrowid
    return {
        "id": conv_id,
        "user_id": user["id"],
        "owner_username": user["username"],
        "title": title[:120],
        "model_id": model_id,
        "task_mode": task_mode,
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
            raise HTTPException(status_code=400, detail="Both kb_key and kb_version are required")
        kb_key = _normalize_kb_key(body.kb_key or "")
        kb_version = body.kb_version
        with db_conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM brand_kb_versions WHERE kb_key = ? AND version = ?",
                (kb_key, kb_version),
            ).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="KB version not found")
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
            raise HTTPException(status_code=403, detail="No access to this KB version")
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
        cur = conn.execute(
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
        doc_id = cur.lastrowid
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


@app.post("/api/conversations/{conversation_id}/messages")
def send_message(conversation_id: int, body: MessageInput, request: Request) -> Any:
    user = must_login(request)
    conversation = conversation_visible_or_404(user["id"], conversation_id)

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息不能为空")

    now = now_utc().isoformat()
    with db_conn() as conn:
        user_cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (conversation_id, content, now),
        )
        user_message_id = user_cur.lastrowid

    context = {
        "channel": body.channel,
        "product": body.product,
        "audience": body.audience,
        "objective": body.objective,
        "brand_voice": body.brand_voice,
        "ui_language": body.ui_language,
        "model_id": conversation["model_id"],
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

    model_fallback_used = False
    original_model_id = conversation["model_id"]
    agent_output = invoke({"prompt": content, "tool_args": context})

    if "error" in agent_output and original_model_id != DEFAULT_MODEL_ID:
        fallback_context = dict(context)
        fallback_context["model_id"] = DEFAULT_MODEL_ID
        fallback_output = invoke({"prompt": content, "tool_args": fallback_context})
        if "error" not in fallback_output:
            model_fallback_used = True
            agent_output = fallback_output
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
        assistant_text = f"[错误] {message}"
        if details:
            assistant_text += f"\n{details}"
    elif not model_fallback_used:
        assistant_text = agent_output.get("result", "")

    now2 = now_utc().isoformat()
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
            (conversation_id, assistant_text, now2),
        )
        assistant_message_id = cur.lastrowid

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
                    DEFAULT_MODEL_ID if model_fallback_used else original_model_id,
                    _json_dumps(orchestrator.get("brief")),
                    _json_dumps(orchestrator.get("plan")),
                    _json_dumps(orchestrator.get("evaluation")),
                    now2,
                ),
            )

        if conversation["title"] in {"新对话", "新营销任务"}:
            new_title = content[:30]
            conn.execute(
                "UPDATE conversations SET title = ?, model_id = ?, updated_at = ? WHERE id = ?",
                (
                    new_title,
                    DEFAULT_MODEL_ID if model_fallback_used else original_model_id,
                    now2,
                    conversation_id,
                ),
            )
        else:
            conn.execute(
                "UPDATE conversations SET model_id = ?, updated_at = ? WHERE id = ?",
                (
                    DEFAULT_MODEL_ID if model_fallback_used else original_model_id,
                    now2,
                    conversation_id,
                ),
            )

    _refresh_conversation_summary(conversation_id)

    return {
        "assistant_message": {
            "role": "assistant",
            "content": assistant_text,
            "created_at": now2,
        }
    }


class AdminStatusInput(BaseModel):
    is_active: bool


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
            cur = conn.execute(
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
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
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
