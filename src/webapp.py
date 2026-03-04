import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import sqlite3
import uuid
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

SUPPORTED_MODELS = [
    "us.amazon.nova-micro-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-pro-v1:0",
]
TASK_MODES = {"chat", "marketing"}
SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log", ".py", ".html", ".xml", ".yaml", ".yml"}

DEFAULT_ADMIN_USER = os.getenv("NOVARED_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("NOVARED_ADMIN_PASSWORD", "admin123456")


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
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
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

            CREATE TABLE IF NOT EXISTS brand_kb_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_key TEXT NOT NULL,
                kb_name TEXT NOT NULL,
                version INTEGER NOT NULL,
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

        admin_exists = conn.execute(
            "SELECT id FROM users WHERE username = ?", (DEFAULT_ADMIN_USER,)
        ).fetchone()
        if not admin_exists:
            salt, pwd_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
            conn.execute(
                """
                INSERT INTO users (username, password_salt, password_hash, is_admin, is_active, created_at)
                VALUES (?, ?, ?, 1, 1, ?)
                """,
                (DEFAULT_ADMIN_USER, salt, pwd_hash, now_utc().isoformat()),
            )


app = FastAPI(title="novaRed Web Chat")


@app.on_event("startup")
def startup() -> None:
    init_db()


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


def create_session(user_id: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = now_utc() + timedelta(days=SESSION_DAYS)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, token, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (user_id, token, expires_at.isoformat(), now_utc().isoformat()),
        )
    return token, expires_at


def conversation_owner_or_404(user_id: int, conversation_id: int) -> sqlite3.Row:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
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


def _build_document_context(conversation_id: int) -> str:
    with db_conn() as conn:
        docs = conn.execute(
            """
            SELECT filename, text_content
            FROM documents
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()
    if not docs:
        return ""
    parts = ["Attached documents context (use when relevant):"]
    for doc in docs:
        parts.append(f"\n[Document: {doc['filename']}]\n{doc['text_content']}")
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


def _kb_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "kb_key": row["kb_key"],
        "kb_name": row["kb_name"],
        "version": row["version"],
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


class LoginInput(BaseModel):
    username: str
    password: str


class ConversationCreateInput(BaseModel):
    title: str | None = None
    task_mode: str | None = None


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
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


class BrandKBInput(BaseModel):
    kb_key: str = Field(min_length=1, max_length=80)
    kb_name: str | None = Field(default=None, max_length=120)
    brand_voice: str | None = Field(default=None, max_length=500)
    positioning: dict[str, Any] = Field(default_factory=dict)
    glossary: list[Any] = Field(default_factory=list)
    forbidden_words: list[Any] = Field(default_factory=list)
    required_terms: list[Any] = Field(default_factory=list)
    claims_policy: dict[str, Any] = Field(default_factory=dict)
    examples: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=4000)


class ConversationKBInput(BaseModel):
    kb_key: str | None = Field(default=None, max_length=80)
    kb_version: int | None = Field(default=None, ge=1)


class ConversationModeInput(BaseModel):
    task_mode: str


class BrandKBUpdateInput(BaseModel):
    kb_name: str | None = Field(default=None, max_length=120)
    brand_voice: str | None = Field(default=None, max_length=500)
    positioning: dict[str, Any] = Field(default_factory=dict)
    glossary: list[Any] = Field(default_factory=list)
    forbidden_words: list[Any] = Field(default_factory=list)
    required_terms: list[Any] = Field(default_factory=list)
    claims_policy: dict[str, Any] = Field(default_factory=dict)
    examples: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=4000)


AUTH_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>novaRed</title>
  <style>
    :root { --bg:#f5f7fb; --card:#ffffff; --line:#d9deea; --txt:#1b2430; --muted:#5a6472; --accent:#1f6feb; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:linear-gradient(160deg,#eef3ff,#f9fafc 45%,#ecf7f3); color:var(--txt); min-height:100vh; display:grid; place-items:center; }
    .lang { position:fixed; top:14px; right:14px; display:flex; gap:6px; }
    .lang button { width:auto; padding:7px 10px; border:1px solid var(--line); background:#fff; color:var(--txt); }
    .lang button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
    .wrap { width:min(900px,94vw); display:grid; grid-template-columns:1fr 1fr; gap:16px; }
    .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px; box-shadow:0 12px 40px rgba(22,34,66,.06); }
    h2 { margin:0 0 10px; }
    p { color:var(--muted); margin:0 0 16px; font-size:14px; }
    input { width:100%; padding:10px; border:1px solid var(--line); border-radius:10px; margin-bottom:10px; }
    button { width:100%; border:0; border-radius:10px; padding:10px; background:var(--accent); color:#fff; font-weight:600; cursor:pointer; }
    .err { color:#d1242f; font-size:13px; min-height:20px; }
    .note { margin-top:8px; font-size:12px; color:var(--muted); }
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
      <p data-i18n="register_subtitle">创建个人账号后可保存自己的对话记录。</p>
      <input id="reg-username" data-i18n-placeholder="reg_username" placeholder="用户名（3-32 位）" />
      <input id="reg-password" data-i18n-placeholder="reg_password" placeholder="密码（至少 8 位）" type="password" />
      <button onclick="registerUser()" data-i18n="register_btn">创建账号</button>
      <div id="reg-err" class="err"></div>
    </div>
  </div>

<script>
const I18N = {
  zh: {
    page_title: 'novaRed 登录',
    login_title: '登录',
    login_subtitle: '进入你的营销 Agent 工作台。',
    login_btn: '登录',
    register_title: '注册',
    register_subtitle: '创建个人账号后可保存自己的对话记录。',
    register_btn: '创建账号',
    username: '用户名',
    password: '密码',
    reg_username: '用户名（3-32 位）',
    reg_password: '密码（至少 8 位）',
    default_admin: '首次可用默认管理员账号：admin / admin123456',
    login_failed: '登录失败',
    register_failed: '注册失败'
  },
  en: {
    page_title: 'novaRed Sign In',
    login_title: 'Sign In',
    login_subtitle: 'Access your marketing agent workspace.',
    login_btn: 'Sign In',
    register_title: 'Register',
    register_subtitle: 'Create your account to keep your own chat history.',
    register_btn: 'Create Account',
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

async function registerUser() {
  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value;
  const err = document.getElementById('reg-err');
  err.textContent = '';
  const res = await fetch('/register', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username,password})});
  const data = await res.json();
  if (!res.ok) { err.textContent = data.detail || t('register_failed'); return; }
  location.href = '/app';
}
applyI18n();
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
  <title>novaRed Chat</title>
  <style>
    :root { --bg:#f4f6fb; --pane:#ffffff; --line:#d8deea; --txt:#1b2430; --muted:#5f6b7a; --accent:#0f6fff; --bot:#f2f6ff; --user:#e8f6ef; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--txt); }
    .root { height:100vh; display:grid; grid-template-columns:280px 1fr; }
    .sidebar { border-right:1px solid var(--line); background:linear-gradient(180deg,#f6f9ff,#fdfefe); padding:14px; display:flex; flex-direction:column; }
    .topline { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:12px; }
    .badge { font-size:12px; color:var(--muted); }
    .btn { border:1px solid var(--line); background:#fff; padding:8px 10px; border-radius:10px; cursor:pointer; }
    .btn.accent { background:var(--accent); color:#fff; border-color:var(--accent); }
    .chat-list { overflow:auto; display:flex; flex-direction:column; gap:8px; margin-top:10px; }
    .chat-item { border:1px solid var(--line); border-radius:10px; padding:10px; background:#fff; cursor:pointer; }
    .chat-item.active { border-color:var(--accent); box-shadow:0 0 0 2px rgba(15,111,255,.15); }
    .chat-row { display:flex; justify-content:space-between; align-items:center; gap:8px; }
    .chat-title { font-size:14px; font-weight:600; }
    .chat-title-input { width:100%; font-size:14px; font-weight:600; border:1px solid var(--accent); border-radius:6px; padding:3px 6px; background:#fff; }
    .mode-pill { font-size:11px; border:1px solid #bfd3ff; color:#1657c9; background:#eef4ff; border-radius:999px; padding:2px 8px; white-space:nowrap; }
    .chat-time { font-size:12px; color:var(--muted); margin-top:4px; }
    .lang { display:flex; gap:6px; }
    .lang .btn { padding:6px 9px; }
    .lang .btn.active { background:var(--accent); color:#fff; border-color:var(--accent); }

    .main { display:grid; grid-template-rows:auto 1fr auto; }
    .head { border-bottom:1px solid var(--line); background:#fff; padding:12px 16px; display:flex; justify-content:space-between; align-items:center; gap:10px; }
    .head-controls { display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .head-controls label { font-size:12px; color:var(--muted); }
    .head-controls select { border:1px solid var(--line); border-radius:10px; padding:7px; background:#fff; }
    .messages { padding:18px; overflow:auto; display:flex; flex-direction:column; gap:12px; }
    .msg { max-width:840px; border:1px solid var(--line); border-radius:12px; padding:12px; line-height:1.5; white-space:pre-wrap; }
    .msg.user { background:var(--user); align-self:flex-end; }
    .msg.assistant { background:var(--bot); align-self:flex-start; }
    .composer { border-top:1px solid var(--line); background:#fff; padding:12px; }
    textarea { width:100%; min-height:90px; resize:vertical; border:1px solid var(--line); border-radius:10px; padding:10px; }
    .brief-card { border:1px solid var(--line); background:#f9fbff; border-radius:10px; padding:10px; margin-bottom:8px; }
    .brief-card.hidden { display:none; }
    .brief-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .brief-grid .full { grid-column:1 / -1; }
    .brief-grid label { font-size:12px; color:var(--muted); display:block; margin-bottom:4px; }
    .brief-grid input, .brief-grid select, .brief-grid textarea { width:100%; border:1px solid var(--line); border-radius:8px; padding:8px; background:#fff; }
    .brief-grid textarea { min-height:72px; }
    .action { margin-top:8px; display:flex; justify-content:space-between; align-items:center; gap:10px; }
    .upload { margin-top:8px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .doc-list { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; }
    .doc-pill { display:inline-flex; align-items:center; gap:6px; font-size:12px; border:1px solid var(--line); border-radius:999px; padding:4px 10px; background:#fff; }
    .doc-pill button { border:0; background:transparent; cursor:pointer; color:#b42318; font-size:12px; padding:0; }
    .hint { font-size:12px; color:var(--muted); }

    @media (max-width: 900px) {
      .root { grid-template-columns:1fr; }
      .sidebar { height:35vh; border-right:0; border-bottom:1px solid var(--line); }
    }
  </style>
</head>
<body>
  <div class="root">
    <aside class="sidebar">
      <div class="topline">
        <strong data-i18n="conversation_list">会话记录</strong>
        <div style="display:flex; gap:6px;">
          <button class="btn accent" onclick="createConversation('chat')" data-i18n="new_chat_conversation">+ 新对话</button>
          <button class="btn" onclick="createConversation('marketing')" data-i18n="new_marketing_conversation">+ 营销任务</button>
        </div>
      </div>
      <div class="lang">
        <button class="btn" id="lang-zh" onclick="setLang('zh')">中文</button>
        <button class="btn" id="lang-en" onclick="setLang('en')">EN</button>
      </div>
      <div class="badge" id="user-badge"></div>
      <div class="chat-list" id="chat-list"></div>
    </aside>

    <section class="main">
      <div class="head">
        <strong id="chat-title" data-i18n="no_conversation">未选择会话</strong>
        <div class="head-controls">
          <label for="model-select" data-i18n="model_label">模型</label>
          <select id="model-select" onchange="changeModel()"></select>
          <label for="task-mode-select" data-i18n="mode_label">任务模式</label>
          <select id="task-mode-select" onchange="changeTaskMode()">
            <option value="chat" data-i18n="mode_chat">普通聊天</option>
            <option value="marketing" data-i18n="mode_marketing">营销任务</option>
          </select>
          <button class="btn" onclick="gotoKB()" data-i18n="kb_mgmt">KB 管理</button>
          <button class="btn" onclick="exportConversation()" data-i18n="export_chat">导出聊天</button>
          <button class="btn" onclick="renameConversation()" data-i18n="rename_chat">重命名</button>
          <button class="btn" onclick="deleteConversation()" data-i18n="delete_chat">删除聊天</button>
          <button class="btn" onclick="gotoAdmin()" id="admin-btn" style="display:none" data-i18n="user_mgmt">用户管理</button>
          <button class="btn" onclick="logout()" data-i18n="logout">退出</button>
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

<script>
const I18N = {
  zh: {
    page_title: 'novaRed Chat',
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
    delete_chat: '删除聊天',
    user_mgmt: '用户管理',
    logout: '退出',
    upload_label: '上传文档',
    upload_btn: '上传',
    input_placeholder: '输入你的营销任务，例如：给 B2B SaaS 产品写 3 个 LinkedIn 开场文案',
    hint: '每个用户仅能访问自己的会话和消息。',
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
    rename_failed: '重命名失败'
  },
  en: {
    page_title: 'novaRed Chat',
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
    delete_chat: 'Delete Chat',
    user_mgmt: 'User Management',
    logout: 'Log Out',
    upload_label: 'Upload document',
    upload_btn: 'Upload',
    input_placeholder: 'Type your marketing task, e.g., write 3 LinkedIn hooks for a B2B SaaS launch',
    hint: 'Each user can only access their own conversations and messages.',
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
    rename_failed: 'Rename failed'
  }
};

let me = null;
let conversations = [];
let models = [];
let kbList = [];
let kbVersions = [];
let activeConversationId = null;
let activeDocuments = [];
let suppressKBChange = false;
let editingConversationId = null;
let currentLang = localStorage.getItem('nova_lang') || 'zh';

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
  syncTaskModeSelect();
  syncTaskModeUI();
}

function syncTaskModeUI() {
  const brief = document.getElementById('marketing-brief');
  const active = currentConversation();
  const mode = active && active.task_mode ? active.task_mode : 'chat';
  const marketingMode = mode === 'marketing';
  brief.classList.toggle('hidden', !marketingMode);
  document.getElementById('input').placeholder = marketingMode
    ? t('input_placeholder')
    : (currentLang === 'en'
      ? 'Type a free-form message to chat with the agent'
      : '输入任意消息进行普通聊天');
}

async function api(url, options={}) {
  const headers = options.body instanceof FormData ? {} : {'Content-Type':'application/json'};
  const res = await fetch(url, {headers, ...options});
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error(data.detail || t('request_failed'));
  return data;
}

function fmt(ts) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

function renderDocuments() {
  const box = document.getElementById('doc-list');
  box.innerHTML = '';
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

async function loadModels() {
  const data = await api('/api/models');
  models = data.models || [];
  syncModelSelect();
  syncTaskModeSelect();
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
    time.textContent = fmt(c.updated_at);

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
}

async function createConversation(taskMode='chat') {
  const created = await api('/api/conversations', {method:'POST', body:JSON.stringify({task_mode: taskMode})});
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
    const payload = { content };
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

(async function init(){
  try {
    applyI18n();
    await loadMe();
    await loadModels();
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
  <title>Brand KB</title>
  <style>
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f5f8fc; color:#1f2937; }
    .wrap { max-width:1100px; margin:18px auto; padding:0 14px; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:12px; }
    .toolbar { display:flex; gap:8px; align-items:center; }
    .toolbar button.active { background:#0f6fff; color:#fff; border-color:#0f6fff; }
    .layout { display:grid; grid-template-columns: 320px 1fr; gap:12px; }
    .card { background:#fff; border:1px solid #d8deea; border-radius:12px; padding:12px; }
    .list { display:flex; flex-direction:column; gap:8px; max-height:560px; overflow:auto; }
    .item { border:1px solid #d8deea; border-radius:10px; padding:8px; cursor:pointer; }
    .item.active { border-color:#0f6fff; box-shadow:0 0 0 2px rgba(15,111,255,.12); }
    .item .name { font-weight:600; font-size:14px; }
    .item .meta { color:#64748b; font-size:12px; margin-top:4px; }
    .grid { display:grid; gap:8px; grid-template-columns:1fr 1fr; }
    .full { grid-column:1 / -1; }
    label { font-size:12px; color:#475569; display:block; margin-bottom:4px; }
    input, select, textarea, button { width:100%; box-sizing:border-box; padding:8px; border-radius:8px; border:1px solid #d8deea; }
    textarea { min-height:90px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
    button { cursor:pointer; background:#fff; }
    button.primary { background:#0f6fff; border-color:#0f6fff; color:#fff; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; }
    .actions button { width:auto; }
    .msg { font-size:12px; margin-top:8px; color:#0f766e; min-height:18px; }
    .warn { color:#b91c1c; }
    @media (max-width: 960px) { .layout { grid-template-columns:1fr; } }
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
            <label for="kb-positioning" data-i18n="positioning">Positioning (JSON)</label>
            <textarea id="kb-positioning">{}</textarea>
          </div>
          <div class="full">
            <label for="kb-glossary" data-i18n="glossary">Glossary (JSON Array)</label>
            <textarea id="kb-glossary">[]</textarea>
          </div>
          <div class="full">
            <label for="kb-forbidden" data-i18n="forbidden">Forbidden Words (JSON Array)</label>
            <textarea id="kb-forbidden">[]</textarea>
          </div>
          <div class="full">
            <label for="kb-required" data-i18n="required">Required Terms (JSON Array)</label>
            <textarea id="kb-required">[]</textarea>
          </div>
          <div class="full">
            <label for="kb-claims" data-i18n="claims">Claims Policy (JSON)</label>
            <textarea id="kb-claims">{}</textarea>
          </div>
          <div class="full">
            <label for="kb-examples" data-i18n="examples">Examples (JSON / null)</label>
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
    new_key: '新版本目标 Key（可新建）',
    kb_name: 'KB 名称',
    brand_voice: '品牌语调',
    positioning: '定位 (JSON)',
    glossary: '术语表 (JSON 数组)',
    forbidden: '禁用词 (JSON 数组)',
    required: '必需词 (JSON 数组)',
    claims: '声明策略 (JSON)',
    examples: '示例 (JSON / null)',
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
    invalid_json: 'JSON 格式错误'
  },
  en: {
    title: 'Brand KB Management',
    back: 'Back to Chat',
    logout: 'Log Out',
    kb_list: 'KB List',
    select_key: 'Select KB Key',
    select_version: 'Select Version',
    new_key: 'Target key for new version',
    kb_name: 'KB Name',
    brand_voice: 'Brand Voice',
    positioning: 'Positioning (JSON)',
    glossary: 'Glossary (JSON Array)',
    forbidden: 'Forbidden Words (JSON Array)',
    required: 'Required Terms (JSON Array)',
    claims: 'Claims Policy (JSON)',
    examples: 'Examples (JSON / null)',
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
    invalid_json: 'Invalid JSON'
  }
};

let currentLang = localStorage.getItem('nova_lang') || 'zh';
let kbList = [];
let kbVersions = [];

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
}
function setLang(lang) {
  currentLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('nova_lang', currentLang);
  applyI18n();
}
async function api(url, options={}) {
  const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  let data = {};
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}
function parseJSON(raw, fallback) {
  const text = (raw || '').trim();
  if (!text) return fallback;
  return JSON.parse(text);
}
function stringify(value) {
  if (value === null || value === undefined) return 'null';
  return JSON.stringify(value, null, 2);
}
function renderKBList() {
  const box = document.getElementById('kb-list');
  box.innerHTML = '';
  for (const kb of kbList) {
    const div = document.createElement('div');
    div.className = 'item';
    div.onclick = async () => {
      document.getElementById('kb-key-select').value = kb.kb_key;
      await changeKBKey();
    };
    div.innerHTML = `<div class="name">${kb.kb_name}</div><div class="meta">${kb.kb_key} · v${kb.version}</div>`;
    box.appendChild(div);
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
}
function collectPayload() {
  return {
    kb_name: document.getElementById('kb-name').value.trim() || null,
    brand_voice: document.getElementById('kb-brand-voice').value.trim() || null,
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
async function changeKBKey() {
  const key = document.getElementById('kb-key-select').value;
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
    await api('/api/me');
    await refreshKBList();
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
  <title>Admin</title>
  <style>
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f8fc; color:#1f2a37; }
    .wrap { max-width:980px; margin:20px auto; padding:0 14px; }
    .top { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; }
    .toolbar { display:flex; gap:6px; align-items:center; }
    .toolbar button.active { background:#0f6fff; color:#fff; border-color:#0f6fff; }
    .card { background:#fff; border:1px solid #d8deea; border-radius:12px; padding:14px; margin-bottom:14px; }
    input, select { padding:8px; border:1px solid #d8deea; border-radius:8px; margin-right:6px; }
    button { padding:8px 10px; border:1px solid #d8deea; border-radius:8px; background:#fff; cursor:pointer; }
    table { width:100%; border-collapse:collapse; }
    th, td { padding:8px; border-bottom:1px solid #edf1f7; text-align:left; }
    .small { font-size:12px; color:#64748b; }
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
      <input id="new-name" data-i18n-placeholder="username" placeholder="用户名" />
      <input id="new-pass" data-i18n-placeholder="password" placeholder="密码" type="password" />
      <select id="new-admin">
        <option value="false" data-i18n="normal_user">普通用户</option>
        <option value="true" data-i18n="admin_user">管理员</option>
      </select>
      <button onclick="createUser()" data-i18n="create">创建</button>
      <div class="small" id="create-msg"></div>
    </div>

    <div class="card">
      <h3 data-i18n="user_list">用户列表</h3>
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
  const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  let data = {};
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error(data.detail || t('request_failed'));
  return data;
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

applyI18n();
loadUsers().catch(() => location.href = '/app');
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
    try:
        with db_conn() as conn:
            conn.execute(
                """
                INSERT INTO users (username, password_salt, password_hash, is_admin, is_active, created_at)
                VALUES (?, ?, ?, 0, 1, ?)
                """,
                (username, salt, pwd_hash, now_utc().isoformat()),
            )
            user_id = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="用户名已存在")

    token, exp = create_session(user_id)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        expires=exp.strftime("%a, %d %b %Y %H:%M:%S GMT"),
    )
    return response


@app.post("/login")
def login(body: LoginInput) -> Any:
    with db_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (body.username.strip(),)).fetchone()
    if not user or not verify_password(body.password, user["password_salt"], user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user["is_active"] == 0:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token, exp = create_session(user["id"])
    response = JSONResponse({"ok": True})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        expires=exp.strftime("%a, %d %b %Y %H:%M:%S GMT"),
    )
    return response


@app.post("/logout")
def logout(request: Request) -> Any:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with db_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
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
    }


@app.get("/api/kb/list")
def list_brand_kb(request: Request) -> Any:
    must_login(request)
    with db_conn() as conn:
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT kb_key, MAX(version) AS latest_version
                FROM brand_kb_versions
                GROUP BY kb_key
            )
            SELECT b.kb_key, b.kb_name, b.version, b.brand_voice, b.created_at
            FROM brand_kb_versions b
            JOIN latest l ON l.kb_key = b.kb_key AND l.latest_version = b.version
            ORDER BY b.kb_name COLLATE NOCASE ASC, b.kb_key ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/kb/{kb_key}/versions")
def list_brand_kb_versions(kb_key: str, request: Request) -> Any:
    must_login(request)
    key = _normalize_kb_key(kb_key)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT kb_key, kb_name, version, created_at
            FROM brand_kb_versions
            WHERE kb_key = ?
            ORDER BY version DESC
            """,
            (key,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="KB not found")
    return [dict(r) for r in rows]


@app.get("/api/kb/{kb_key}")
def get_brand_kb(kb_key: str, request: Request, version: int | None = None) -> Any:
    must_login(request)
    key = _normalize_kb_key(kb_key)
    with db_conn() as conn:
        if version is None:
            row = conn.execute(
                """
                SELECT kb_key, kb_name, version, brand_voice, positioning_json, glossary_json,
                       forbidden_words_json, required_terms_json, claims_policy_json, examples_json, notes, created_at
                FROM brand_kb_versions
                WHERE kb_key = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (key,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT kb_key, kb_name, version, brand_voice, positioning_json, glossary_json,
                       forbidden_words_json, required_terms_json, claims_policy_json, examples_json, notes, created_at
                FROM brand_kb_versions
                WHERE kb_key = ? AND version = ?
                """,
                (key, version),
            ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="KB not found")
    return _kb_row_to_dict(row)


@app.post("/api/kb")
def create_brand_kb(body: BrandKBInput, request: Request) -> Any:
    must_login(request)

    kb_key = _normalize_kb_key(body.kb_key)
    kb_name = (body.kb_name or kb_key).strip() or kb_key
    brand_voice = body.brand_voice.strip() if body.brand_voice else None
    notes = body.notes.strip() if body.notes else None
    forbidden_words = _normalize_string_list(body.forbidden_words)
    required_terms = _normalize_string_list(body.required_terms)
    now = now_utc().isoformat()

    with db_conn() as conn:
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM brand_kb_versions WHERE kb_key = ?",
            (kb_key,),
        ).fetchone()["next_version"]
        conn.execute(
            """
            INSERT INTO brand_kb_versions (
                kb_key, kb_name, version, brand_voice, positioning_json, glossary_json,
                forbidden_words_json, required_terms_json, claims_policy_json, examples_json, notes, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kb_key,
                kb_name[:120],
                version,
                brand_voice,
                _json_dumps(body.positioning),
                _json_dumps(body.glossary),
                _json_dumps(forbidden_words),
                _json_dumps(required_terms),
                _json_dumps(body.claims_policy),
                _json_dumps(body.examples) if body.examples is not None else None,
                notes,
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT kb_key, kb_name, version, brand_voice, positioning_json, glossary_json,
                   forbidden_words_json, required_terms_json, claims_policy_json, examples_json, notes, created_at
            FROM brand_kb_versions
            WHERE kb_key = ? AND version = ?
            """,
            (kb_key, version),
        ).fetchone()
    return _kb_row_to_dict(row)


@app.put("/api/kb/{kb_key}/{version}")
def update_brand_kb(kb_key: str, version: int, body: BrandKBUpdateInput, request: Request) -> Any:
    must_login(request)
    key = _normalize_kb_key(kb_key)
    kb_name = (body.kb_name or key).strip() or key
    brand_voice = body.brand_voice.strip() if body.brand_voice else None
    notes = body.notes.strip() if body.notes else None
    forbidden_words = _normalize_string_list(body.forbidden_words)
    required_terms = _normalize_string_list(body.required_terms)

    with db_conn() as conn:
        exists = conn.execute(
            "SELECT id FROM brand_kb_versions WHERE kb_key = ? AND version = ?",
            (key, version),
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="KB version not found")
        conn.execute(
            """
            UPDATE brand_kb_versions
            SET kb_name = ?, brand_voice = ?, positioning_json = ?, glossary_json = ?,
                forbidden_words_json = ?, required_terms_json = ?, claims_policy_json = ?,
                examples_json = ?, notes = ?
            WHERE kb_key = ? AND version = ?
            """,
            (
                kb_name[:120],
                brand_voice,
                _json_dumps(body.positioning),
                _json_dumps(body.glossary),
                _json_dumps(forbidden_words),
                _json_dumps(required_terms),
                _json_dumps(body.claims_policy),
                _json_dumps(body.examples) if body.examples is not None else None,
                notes,
                key,
                version,
            ),
        )
        row = conn.execute(
            """
            SELECT kb_key, kb_name, version, brand_voice, positioning_json, glossary_json,
                   forbidden_words_json, required_terms_json, claims_policy_json, examples_json, notes, created_at
            FROM brand_kb_versions
            WHERE kb_key = ? AND version = ?
            """,
            (key, version),
        ).fetchone()
    return _kb_row_to_dict(row)


@app.delete("/api/kb/{kb_key}/{version}")
def delete_brand_kb(kb_key: str, version: int, request: Request) -> Any:
    must_login(request)
    key = _normalize_kb_key(kb_key)
    with db_conn() as conn:
        exists = conn.execute(
            "SELECT id FROM brand_kb_versions WHERE kb_key = ? AND version = ?",
            (key, version),
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="KB version not found")
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
            SELECT id, title, model_id, task_mode, kb_key, kb_version, created_at, updated_at
            FROM conversations
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/conversations")
def create_conversation(body: ConversationCreateInput, request: Request) -> Any:
    user = must_login(request)
    task_mode = _normalize_task_mode(body.task_mode)
    default_title = "新营销任务" if task_mode == "marketing" else "新对话"
    title = (body.title or default_title).strip() or default_title
    now = now_utc().isoformat()
    model_id = DEFAULT_MODEL_ID
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (user_id, title, model_id, task_mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], title[:120], model_id, task_mode, now, now),
        )
        conv_id = cur.lastrowid
    return {
        "id": conv_id,
        "title": title[:120],
        "model_id": model_id,
        "task_mode": task_mode,
        "kb_key": None,
        "kb_version": None,
        "created_at": now,
        "updated_at": now,
    }


class ConversationModelInput(BaseModel):
    model_id: str = Field(min_length=3, max_length=128)


class ConversationTitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)


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
            kb_row = conn.execute(
                "SELECT kb_name FROM brand_kb_versions WHERE kb_key = ? AND version = ?",
                (kb_key, kb_version),
            ).fetchone()
        if not kb_row:
            raise HTTPException(status_code=404, detail="KB version not found")
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
    conversation_owner_or_404(user["id"], conversation_id)
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


@app.get("/api/conversations/{conversation_id}/export")
def export_conversation(conversation_id: int, request: Request) -> Any:
    user = must_login(request)
    conversation = conversation_owner_or_404(user["id"], conversation_id)
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
        f"- Task mode: {mode}",
        f"- Model: {conversation['model_id']}",
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
    conversation_owner_or_404(user["id"], conversation_id)
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
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        path = Path(row["file_path"])
        if path.exists():
            path.unlink()
    return {"ok": True}


@app.post("/api/conversations/{conversation_id}/messages")
def send_message(conversation_id: int, body: MessageInput, request: Request) -> Any:
    user = must_login(request)
    conversation = conversation_owner_or_404(user["id"], conversation_id)

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息不能为空")

    now = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (conversation_id, content, now),
        )

    context = {
        "channel": body.channel,
        "product": body.product,
        "audience": body.audience,
        "objective": body.objective,
        "brand_voice": body.brand_voice,
        "model_id": conversation["model_id"],
    }
    extra_parts = []
    if body.extra_requirements:
        extra_parts.append(body.extra_requirements)
    kb_context = _build_brand_kb_context(conversation["kb_key"], conversation["kb_version"])
    if kb_context:
        extra_parts.append(kb_context)
    doc_context = _build_document_context(conversation_id)
    if doc_context:
        extra_parts.append(doc_context)
    context["extra_requirements"] = "\n\n".join(extra_parts) if extra_parts else None

    agent_output = invoke({"prompt": content, "tool_args": context})
    if "error" in agent_output:
        assistant_text = f"[错误] {agent_output['error'].get('message', 'unknown')}"
    else:
        assistant_text = agent_output.get("result", "")

    now2 = now_utc().isoformat()
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
            (conversation_id, assistant_text, now2),
        )

        if conversation["title"] in {"新对话", "新营销任务"}:
            new_title = content[:30]
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (new_title, now2, conversation_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now2, conversation_id),
            )

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
