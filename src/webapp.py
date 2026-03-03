import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from main import invoke


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "webapp.db"
SESSION_COOKIE = "nova_session"
SESSION_DAYS = 7

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
            """
        )

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


class RegisterInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class LoginInput(BaseModel):
    username: str
    password: str


class ConversationCreateInput(BaseModel):
    title: str | None = None


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


AUTH_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>novaRed 登录</title>
  <style>
    :root { --bg:#f5f7fb; --card:#ffffff; --line:#d9deea; --txt:#1b2430; --muted:#5a6472; --accent:#1f6feb; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:linear-gradient(160deg,#eef3ff,#f9fafc 45%,#ecf7f3); color:var(--txt); min-height:100vh; display:grid; place-items:center; }
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
  <div class="wrap">
    <div class="card">
      <h2>登录</h2>
      <p>进入你的营销 Agent 工作台。</p>
      <input id="login-username" placeholder="用户名" />
      <input id="login-password" placeholder="密码" type="password" />
      <button onclick="login()">登录</button>
      <div id="login-err" class="err"></div>
      <div class="note">首次可用默认管理员账号：admin / admin123456</div>
    </div>
    <div class="card">
      <h2>注册</h2>
      <p>创建个人账号后可保存自己的对话记录。</p>
      <input id="reg-username" placeholder="用户名（3-32 位）" />
      <input id="reg-password" placeholder="密码（至少 8 位）" type="password" />
      <button onclick="registerUser()">创建账号</button>
      <div id="reg-err" class="err"></div>
    </div>
  </div>

<script>
async function login() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const err = document.getElementById('login-err');
  err.textContent = '';
  const res = await fetch('/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username,password})});
  const data = await res.json();
  if (!res.ok) { err.textContent = data.detail || '登录失败'; return; }
  location.href = '/app';
}

async function registerUser() {
  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value;
  const err = document.getElementById('reg-err');
  err.textContent = '';
  const res = await fetch('/register', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username,password})});
  const data = await res.json();
  if (!res.ok) { err.textContent = data.detail || '注册失败'; return; }
  location.href = '/app';
}
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
    .chat-title { font-size:14px; font-weight:600; }
    .chat-time { font-size:12px; color:var(--muted); margin-top:4px; }

    .main { display:grid; grid-template-rows:auto 1fr auto; }
    .head { border-bottom:1px solid var(--line); background:#fff; padding:12px 16px; display:flex; justify-content:space-between; align-items:center; }
    .messages { padding:18px; overflow:auto; display:flex; flex-direction:column; gap:12px; }
    .msg { max-width:840px; border:1px solid var(--line); border-radius:12px; padding:12px; line-height:1.5; white-space:pre-wrap; }
    .msg.user { background:var(--user); align-self:flex-end; }
    .msg.assistant { background:var(--bot); align-self:flex-start; }
    .composer { border-top:1px solid var(--line); background:#fff; padding:12px; }
    textarea { width:100%; min-height:90px; resize:vertical; border:1px solid var(--line); border-radius:10px; padding:10px; }
    .action { margin-top:8px; display:flex; justify-content:space-between; align-items:center; gap:10px; }
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
        <strong>会话记录</strong>
        <button class="btn accent" onclick="createConversation()">+ 新对话</button>
      </div>
      <div class="badge" id="user-badge"></div>
      <div class="chat-list" id="chat-list"></div>
    </aside>

    <section class="main">
      <div class="head">
        <strong id="chat-title">未选择会话</strong>
        <div>
          <button class="btn" onclick="gotoAdmin()" id="admin-btn" style="display:none">用户管理</button>
          <button class="btn" onclick="logout()">退出</button>
        </div>
      </div>

      <div class="messages" id="messages"></div>

      <div class="composer">
        <textarea id="input" placeholder="输入你的营销任务，例如：给 B2B SaaS 产品写 3 个 LinkedIn 开场文案"></textarea>
        <div class="action">
          <span class="hint">每个用户仅能访问自己的会话和消息。</span>
          <button class="btn accent" onclick="sendMessage()">发送</button>
        </div>
      </div>
    </section>
  </div>

<script>
let me = null;
let conversations = [];
let activeConversationId = null;

async function api(url, options={}) {
  const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error(data.detail || '请求失败');
  return data;
}

function fmt(ts) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

function renderConversations() {
  const list = document.getElementById('chat-list');
  list.innerHTML = '';
  for (const c of conversations) {
    const div = document.createElement('div');
    div.className = 'chat-item' + (c.id === activeConversationId ? ' active' : '');
    div.onclick = () => openConversation(c.id);
    div.innerHTML = `<div class="chat-title">${c.title}</div><div class="chat-time">${fmt(c.updated_at)}</div>`;
    list.appendChild(div);
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
  document.getElementById('user-badge').textContent = `当前用户：${me.username}`;
  if (me.is_admin) document.getElementById('admin-btn').style.display = 'inline-block';
}

async function loadConversations() {
  conversations = await api('/api/conversations');
  renderConversations();
  if (!activeConversationId && conversations.length) {
    openConversation(conversations[0].id);
  }
}

async function createConversation() {
  const created = await api('/api/conversations', {method:'POST', body:JSON.stringify({})});
  conversations.unshift(created);
  activeConversationId = created.id;
  renderConversations();
  document.getElementById('chat-title').textContent = created.title;
  renderMessages([]);
}

async function openConversation(id) {
  activeConversationId = id;
  const conv = conversations.find(x => x.id === id);
  if (conv) document.getElementById('chat-title').textContent = conv.title;
  renderConversations();
  const items = await api(`/api/conversations/${id}/messages`);
  renderMessages(items);
}

async function sendMessage() {
  if (!activeConversationId) await createConversation();
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
  pendingBot.textContent = '思考中...';
  box.appendChild(pendingBot);
  box.scrollTop = box.scrollHeight;

  try {
    const data = await api(`/api/conversations/${activeConversationId}/messages`, {
      method:'POST',
      body: JSON.stringify({ content })
    });
    pendingBot.textContent = data.assistant_message.content;
    await loadConversations();
    renderConversations();
  } catch (e) {
    pendingBot.textContent = `请求失败：${e.message}`;
  }
}

async function logout() {
  await api('/logout', {method:'POST'});
  location.href = '/';
}

function gotoAdmin() { location.href = '/admin'; }

(async function init(){
  try {
    await loadMe();
    await loadConversations();
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
  <title>用户管理</title>
  <style>
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f8fc; color:#1f2a37; }
    .wrap { max-width:980px; margin:20px auto; padding:0 14px; }
    .top { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; }
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
      <h2>用户管理</h2>
      <div>
        <button onclick="back()">返回聊天</button>
        <button onclick="logout()">退出</button>
      </div>
    </div>

    <div class="card">
      <h3>创建用户</h3>
      <input id="new-name" placeholder="用户名" />
      <input id="new-pass" placeholder="密码" type="password" />
      <select id="new-admin">
        <option value="false">普通用户</option>
        <option value="true">管理员</option>
      </select>
      <button onclick="createUser()">创建</button>
      <div class="small" id="create-msg"></div>
    </div>

    <div class="card">
      <h3>用户列表</h3>
      <table>
        <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </div>

<script>
async function api(url, options={}) {
  const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  let data = {};
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error(data.detail || '请求失败');
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
      <td>${u.is_admin ? '管理员' : '普通用户'}</td>
      <td>${u.is_active ? '启用' : '禁用'}</td>
      <td>${fmt(u.created_at)}</td>
      <td>
        <button onclick="toggleUser(${u.id}, ${u.is_active})">${u.is_active ? '禁用' : '启用'}</button>
        <button onclick="resetPwd(${u.id})">重置密码</button>
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
    msg.textContent = '创建成功';
    await loadUsers();
  } catch (e) {
    msg.textContent = `创建失败：${e.message}`;
  }
}

async function toggleUser(userId, current) {
  await api(`/api/admin/users/${userId}/status`, {method:'POST', body:JSON.stringify({is_active: !current})});
  await loadUsers();
}

async function resetPwd(userId) {
  const newPwd = prompt('输入新密码（至少8位）');
  if (!newPwd) return;
  await api(`/api/admin/users/${userId}/password`, {method:'POST', body:JSON.stringify({new_password:newPwd})});
  alert('密码已重置');
}

async function logout() { await api('/logout', {method:'POST'}); location.href = '/'; }
function back() { location.href = '/app'; }

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


@app.get("/api/conversations")
def list_conversations(request: Request) -> Any:
    user = must_login(request)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, title, created_at, updated_at
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
    title = (body.title or "新对话").strip() or "新对话"
    now = now_utc().isoformat()
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user["id"], title[:120], now, now),
        )
        conv_id = cur.lastrowid
    return {
        "id": conv_id,
        "title": title[:120],
        "created_at": now,
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
        "extra_requirements": body.extra_requirements,
    }

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

        if conversation["title"] == "新对话":
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
