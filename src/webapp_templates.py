"""HTML templates used by the FastAPI web app routes."""

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
    invalid_credentials: '用户名或密码错误',
    account_disabled: '账号已被禁用',
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
    invalid_credentials: 'Invalid username or password',
    account_disabled: 'This account is disabled',
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
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    if (res.status === 401) { err.textContent = t('invalid_credentials'); return; }
    if (res.status === 403) { err.textContent = t('account_disabled'); return; }
    err.textContent = data.detail || t('login_failed');
    return;
  }
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
      --bg:#dce7f5;
      --bg-soft:#dceee7;
      --pane:rgba(255,255,255,.56);
      --pane-strong:rgba(255,255,255,.72);
      --pane-solid:#ffffff;
      --line:rgba(170,186,209,.55);
      --line-strong:rgba(136,160,191,.68);
      --txt:#102037;
      --muted:#4f647f;
      --accent:#0b6fde;
      --accent-2:#0ea979;
      --danger:#cf3f3f;
      --bot:rgba(243,248,255,.72);
      --user:rgba(233,248,239,.72);
      --shadow:0 22px 44px rgba(17,35,62,.16);
      --sidebar-width:320px;
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      font-family:"IBM Plex Sans","Segoe UI",sans-serif;
      background:
        radial-gradient(980px 580px at -4% -20%,#eef5ff 0%,transparent 62%),
        radial-gradient(920px 520px at 104% -24%,#e8fff4 0%,transparent 64%),
        radial-gradient(760px 480px at 50% 108%,#eaf1ff 0%,transparent 68%),
        linear-gradient(160deg,var(--bg),var(--bg-soft));
      color:var(--txt);
      height:100vh;
      overflow:hidden;
    }
    body::before {
      content:"";
      position:fixed;
      inset:-18%;
      pointer-events:none;
      background:
        radial-gradient(520px 300px at 18% 24%,rgba(255,255,255,.42),transparent 70%),
        radial-gradient(500px 280px at 82% 14%,rgba(255,255,255,.34),transparent 72%),
        radial-gradient(600px 340px at 60% 84%,rgba(255,255,255,.24),transparent 74%);
      filter:blur(16px) saturate(120%);
      opacity:.9;
      z-index:0;
    }
    body.sidebar-resizing {
      user-select:none;
      cursor:col-resize;
    }
    body.sidebar-resizing * {
      cursor:col-resize !important;
    }
    .app-shell {
      height:100vh;
      display:grid;
      grid-template-rows:auto 1fr;
      gap:8px;
      padding:8px;
      min-height:0;
      position:relative;
      z-index:1;
    }
    .global-bar {
      border:1px solid var(--line);
      border-radius:16px;
      background:var(--pane);
      box-shadow:var(--shadow);
      backdrop-filter: blur(22px) saturate(145%);
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:10px;
      padding:6px 10px;
    }
    .global-left {
      display:flex;
      align-items:center;
      gap:8px;
      min-width:0;
    }
    .global-title {
      font-family:"Sora","IBM Plex Sans",sans-serif;
      font-size:15px;
      font-weight:700;
      letter-spacing:.2px;
      white-space:nowrap;
    }
    .mobile-sidebar-btn { display:none; }
    .global-actions { display:flex; align-items:center; gap:6px; flex-wrap:wrap; justify-content:flex-end; }
    .root {
      min-height:0;
      height:100%;
      display:grid;
      grid-template-columns:minmax(220px,var(--sidebar-width)) 10px minmax(0,1fr);
      gap:8px;
      min-width:0;
      transition:grid-template-columns .18s ease;
    }
    .root.sidebar-collapsed {
      grid-template-columns:0 14px minmax(0,1fr);
      gap:6px;
    }
    .splitter {
      border:1px solid rgba(160,179,204,.42);
      border-radius:10px;
      background:rgba(255,255,255,.34);
      backdrop-filter: blur(14px);
      cursor:col-resize;
      position:relative;
      transition:background .16s ease, border-color .16s ease;
      min-height:0;
    }
    .splitter::before {
      content:"";
      position:absolute;
      top:50%;
      left:50%;
      transform:translate(-50%, -50%);
      width:3px;
      height:46px;
      border-radius:999px;
      background:linear-gradient(180deg,rgba(102,128,162,.2),rgba(102,128,162,.7),rgba(102,128,162,.2));
    }
    .splitter:hover {
      background:rgba(255,255,255,.52);
      border-color:rgba(126,152,186,.66);
    }
    .root.sidebar-collapsed .splitter {
      border:1px solid rgba(160,179,204,.42);
      background:rgba(255,255,255,.5);
      pointer-events:auto;
      cursor:pointer;
    }
    .sidebar {
      border:1px solid var(--line);
      background:var(--pane);
      border-radius:24px;
      padding:12px;
      display:flex;
      flex-direction:column;
      box-shadow:var(--shadow);
      backdrop-filter: blur(22px) saturate(145%);
      overflow:hidden;
      min-height:0;
      min-width:0;
      transition:opacity .16s ease, transform .16s ease, padding .16s ease, border-color .16s ease;
    }
    .root.sidebar-collapsed .sidebar {
      opacity:0;
      transform:translateX(-8px);
      pointer-events:none;
      padding:0;
      border-width:0;
      box-shadow:none;
    }
    .sidebar-backdrop {
      display:none;
      position:fixed;
      inset:0;
      background:rgba(14,24,41,.22);
      backdrop-filter: blur(3px);
      z-index:35;
    }
    .topline { display:flex; flex-direction:column; gap:6px; margin-bottom:8px; }
    .topline-row { display:flex; align-items:center; justify-content:space-between; gap:8px; }
    .topline strong { font-family:"Sora","IBM Plex Sans",sans-serif; font-size:16px; letter-spacing:.1px; display:block; margin:0; }
    .side-toggle-btn {
      padding:4px 8px;
      font-size:11px;
      border-radius:9px;
      white-space:nowrap;
    }
    .quick-actions { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
    .quick-secondary {
      display:grid;
      grid-template-columns:1fr;
      gap:6px;
    }
    .badge {
      font-size:12px;
      color:var(--muted);
      padding:7px 10px;
      border:1px solid rgba(147,168,198,.44);
      border-radius:12px;
      margin-top:10px;
      background:rgba(248,252,255,.56);
    }
    .btn {
      border:1px solid var(--line);
      background:rgba(255,255,255,.58);
      color:var(--txt);
      padding:7px 9px;
      border-radius:10px;
      cursor:pointer;
      font-weight:600;
      transition:.16s ease;
      backdrop-filter: blur(14px) saturate(135%);
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
      background:linear-gradient(180deg,rgba(255,255,255,.72),rgba(255,255,255,.58));
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
    .lang { display:flex; gap:6px; padding:4px; border:1px solid var(--line); border-radius:999px; width:max-content; background:rgba(255,255,255,.52); backdrop-filter: blur(14px); }
    .lang .btn { padding:6px 10px; border-radius:999px; border:0; box-shadow:none; }
    .lang .btn:hover { transform:none; box-shadow:none; background:#f2f6fb; }
    .lang .btn.active { background:var(--accent); color:#fff; }

    .main {
      display:grid;
      grid-template-rows:auto 1fr auto auto;
      border:1px solid var(--line);
      border-radius:24px;
      background:var(--pane);
      box-shadow:var(--shadow);
      backdrop-filter: blur(24px) saturate(150%);
      overflow:hidden;
      min-height:0;
      min-width:0;
    }
    .head {
      border-bottom:1px solid var(--line);
      background:var(--pane-strong);
      padding:6px 10px;
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:10px;
    }
    .head strong {
      font-family:"Sora","IBM Plex Sans",sans-serif;
      font-size:15px;
      max-width:38%;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .head-controls {
      display:grid;
      grid-template-columns:repeat(3, minmax(122px, 1fr));
      gap:4px 6px;
      align-items:end;
      width:min(820px, 100%);
    }
    .control {
      display:flex;
      flex-direction:column;
      gap:2px;
      min-width:0;
    }
    .control label { font-size:10px; color:var(--muted); line-height:1.05; }
    .control select {
      border:1px solid var(--line);
      border-radius:9px;
      padding:4px 8px;
      background:rgba(255,255,255,.6);
      min-width:0;
      color:var(--txt);
      height:30px;
      font-size:12px;
    }
    .head-actions {
      grid-column:1 / -1;
      display:flex;
      align-items:center;
      gap:5px;
      flex-wrap:wrap;
      margin-top:0;
    }
    .head-actions .btn {
      padding:5px 7px;
      font-size:11px;
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
      white-space:normal;
      box-shadow:0 10px 20px rgba(12,26,48,.06);
      animation:riseIn .2s ease;
    }
    .msg.user { background:var(--user); align-self:flex-end; border-color:#bfe6cf; }
    .msg.assistant { background:var(--bot); align-self:flex-start; border-color:#c9daf3; }
    .msg-content { font-size:15px; line-height:1.62; color:var(--txt); }
    .msg-content p { margin:0 0 10px; }
    .msg-content p:last-child { margin-bottom:0; }
    .msg-content h1, .msg-content h2, .msg-content h3, .msg-content h4 {
      margin:4px 0 10px;
      font-family:"Sora","IBM Plex Sans",sans-serif;
      line-height:1.35;
    }
    .msg-content h1 { font-size:22px; }
    .msg-content h2 { font-size:19px; }
    .msg-content h3 { font-size:17px; }
    .msg-content h4 { font-size:15px; }
    .msg-content ul, .msg-content ol { margin:0 0 10px 18px; padding:0; }
    .msg-content li { margin:3px 0; }
    .msg-content li.check-item {
      list-style:none;
      margin-left:-18px;
      display:flex;
      align-items:flex-start;
      gap:8px;
    }
    .msg-content li.check-item input[type="checkbox"] {
      margin-top:2px;
      width:14px;
      height:14px;
      accent-color:#1f6fd8;
      pointer-events:none;
    }
    .msg-content li.check-item span { flex:1; }
    .msg-content blockquote {
      margin:8px 0 12px;
      padding:8px 12px;
      border-left:3px solid #8eb6ef;
      background:#f5f9ff;
      border-radius:8px;
    }
    .msg-content blockquote p { margin:0; }
    .msg-content hr {
      border:0;
      border-top:1px solid #cfd9ea;
      margin:12px 0;
    }
    .msg-content code {
      font-family:"IBM Plex Mono",ui-monospace,monospace;
      font-size:12px;
      background:#eef4ff;
      border:1px solid #d8e4f7;
      border-radius:6px;
      padding:1px 4px;
    }
    .msg-content pre {
      margin:8px 0 12px;
      padding:10px;
      border:1px solid #d6dfec;
      border-radius:10px;
      background:#f8fbff;
      overflow:auto;
    }
    .msg-content pre code {
      border:0;
      background:transparent;
      padding:0;
      font-size:12px;
      line-height:1.55;
      white-space:pre;
    }
    .msg-content table {
      width:100%;
      border-collapse:collapse;
      margin:8px 0 12px;
      background:#fff;
      border:1px solid #d6dfec;
      border-radius:8px;
      overflow:hidden;
      display:block;
      overflow-x:auto;
    }
    .msg-content thead tr { background:#f4f8ff; }
    .msg-content th, .msg-content td {
      border:1px solid #d6dfec;
      padding:8px 10px;
      text-align:left;
      vertical-align:top;
      min-width:120px;
      white-space:normal;
      font-size:13px;
    }
    .msg-content strong { font-weight:700; }
    .msg-content em { font-style:italic; }
    .msg-content a { color:#0a67d3; text-decoration:none; border-bottom:1px dashed #86b6ec; }
    .msg-content a:hover { border-bottom-style:solid; }
    .trace-panel {
      border-top:1px solid var(--line);
      background:rgba(255,255,255,.48);
      padding:8px 10px;
      max-height:34vh;
      overflow:auto;
    }
    .trace-panel.hidden { display:none; }
    .trace-panel.compact {
      max-height:58px;
      overflow:hidden;
    }
    .trace-head {
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:8px;
      margin-bottom:8px;
    }
    .trace-head strong {
      font-family:"Sora","IBM Plex Sans",sans-serif;
      font-size:13px;
    }
    .trace-tools {
      display:flex;
      align-items:center;
      gap:6px;
      flex-wrap:wrap;
    }
    .trace-tools label {
      font-size:11px;
      color:var(--muted);
    }
    .trace-tools .btn {
      padding:5px 8px;
      font-size:11px;
    }
    .trace-tools select {
      width:auto;
      min-width:180px;
      height:30px;
      padding:4px 8px;
      font-size:12px;
    }
    .trace-body.hidden { display:none; }
    .trace-empty {
      border:1px dashed var(--line-strong);
      border-radius:10px;
      padding:8px;
      color:var(--muted);
      font-size:12px;
      background:#f9fbfe;
    }
    .trace-grid {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:8px;
      margin-top:8px;
    }
    .trace-grid.hidden { display:none; }
    .trace-stage {
      border:1px solid var(--line);
      border-radius:10px;
      padding:8px;
      background:rgba(255,255,255,.62);
    }
    .trace-stage h4 {
      margin:0 0 6px;
      font-size:12px;
      font-family:"Sora","IBM Plex Sans",sans-serif;
    }
    .trace-line {
      font-size:12px;
      color:var(--txt);
      margin-bottom:4px;
    }
    .trace-line .k {
      color:var(--muted);
      margin-right:4px;
    }
    .trace-story {
      font-size:12px;
      line-height:1.55;
      color:var(--txt);
      background:rgba(248,252,255,.58);
      border:1px solid rgba(211,225,243,.7);
      border-radius:8px;
      padding:7px 8px;
      margin-top:6px;
      white-space:pre-wrap;
    }
    .trace-stage.full { grid-column:1 / -1; }
    .trace-bullets {
      margin:6px 0 0;
      padding-left:16px;
      font-size:12px;
      line-height:1.5;
      color:var(--txt);
    }
    .score-grid {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:6px;
      margin-top:6px;
    }
    .score-item {
      border:1px solid var(--line);
      border-radius:8px;
      padding:6px;
      background:#f9fcff;
      font-size:12px;
    }
    .score-item .k { color:var(--muted); font-size:11px; }
    .score-item .v { font-weight:700; font-family:"IBM Plex Mono",ui-monospace,monospace; }
    .reason-list {
      margin:6px 0 0;
      padding-left:16px;
      font-size:12px;
      color:var(--txt);
    }
    .composer {
      border-top:1px solid var(--line);
      background:rgba(255,255,255,.5);
      padding:8px 10px;
      height:230px;
      min-height:144px;
      max-height:34vh;
      overflow:auto;
      resize:vertical;
    }
    .composer.compact {
      height:56px;
      min-height:0;
      max-height:56px;
      overflow:hidden;
      resize:none;
    }
    .composer-head {
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:8px;
      margin-bottom:6px;
    }
    .composer-head strong {
      font-family:"Sora","IBM Plex Sans",sans-serif;
      font-size:13px;
    }
    .composer-head .btn {
      width:auto;
      padding:5px 8px;
      font-size:11px;
    }
    .composer-content.hidden { display:none; }
    textarea, input, select {
      width:100%;
      border:1px solid var(--line);
      border-radius:10px;
      padding:8px 10px;
      background:rgba(255,255,255,.62);
      color:var(--txt);
      font-family:inherit;
      transition:.16s ease;
    }
    textarea:focus, input:focus, select:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(10,103,211,.14); }
    textarea { min-height:70px; resize:vertical; }
    #input { min-height:88px; max-height:34vh; }
    .brief-card {
      border:1px solid var(--line);
      background:linear-gradient(180deg,rgba(250,253,255,.62),rgba(248,253,251,.54));
      border-radius:12px;
      padding:8px;
      margin-bottom:6px;
    }
    .brief-card.hidden { display:none; }
    .shared-kb-bind {
      border:1px solid var(--line);
      background:linear-gradient(180deg,rgba(250,253,255,.62),rgba(248,253,251,.54));
      border-radius:12px;
      padding:8px;
      margin-bottom:6px;
    }
    .shared-kb-bind-grid {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:8px;
    }
    .shared-kb-bind label {
      font-size:12px;
      color:var(--muted);
      display:block;
      margin-bottom:4px;
    }
    .brief-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .brief-grid .full { grid-column:1 / -1; }
    .brief-grid label { font-size:12px; color:var(--muted); display:block; margin-bottom:4px; }
    .brief-grid textarea { min-height:58px; }
    .brief-grid select[multiple] { min-height:96px; }
    .output-sections {
      display:flex;
      flex-wrap:wrap;
      gap:6px;
      margin-top:4px;
    }
    .output-option {
      display:inline-flex;
      align-items:center;
      gap:6px;
      border:1px solid var(--line);
      border-radius:999px;
      background:rgba(255,255,255,.62);
      padding:5px 10px;
      font-size:12px;
      color:var(--txt);
      cursor:pointer;
      user-select:none;
    }
    .output-option input {
      width:auto;
      margin:0;
      accent-color:var(--accent);
    }
    .action { margin-top:6px; display:flex; justify-content:space-between; align-items:center; gap:8px; }
    .upload { margin-top:6px; display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
    .upload label { font-size:12px; color:var(--muted); }
    input[type="file"] {
      width:auto;
      max-width:340px;
      font-size:12px;
      padding:7px;
      border-radius:10px;
      background:rgba(255,255,255,.62);
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
      background:rgba(255,255,255,.64);
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
      background:rgba(255,255,255,.54);
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
      .root { grid-template-columns:minmax(220px, 300px) 8px minmax(0,1fr); }
      .head strong { max-width:100%; font-size:16px; }
      .head { flex-direction:column; align-items:flex-start; }
      .head-controls { width:100%; grid-template-columns:repeat(2, minmax(130px, 1fr)); }
    }
    @media (max-width: 900px) {
      body { background:linear-gradient(160deg,var(--bg),var(--bg-soft)); }
      .app-shell { padding:6px; gap:6px; }
      .global-bar {
        border-radius:12px;
        padding:7px;
        flex-direction:column;
        align-items:stretch;
        gap:6px;
      }
      .global-left { justify-content:space-between; }
      .global-title { font-size:14px; }
      .mobile-sidebar-btn {
        display:inline-flex;
        width:auto;
        padding:6px 10px;
        font-size:12px;
      }
      .global-actions {
        width:100%;
        justify-content:flex-start;
        flex-wrap:nowrap;
        overflow-x:auto;
        padding-bottom:2px;
      }
      .global-actions > .btn { flex:0 0 auto; }
      .root { grid-template-columns:1fr; gap:8px; }
      .root.sidebar-collapsed { grid-template-columns:1fr; }
      .sidebar, .main { border-radius:16px; }
      .sidebar {
        position:fixed;
        left:8px;
        top:84px;
        bottom:8px;
        width:min(88vw, 340px);
        height:auto;
        max-height:none;
        border-right:1px solid var(--line);
        transform:translateX(calc(-100% - 12px));
        transition:transform .18s ease;
        z-index:40;
      }
      .root.mobile-sidebar-open .sidebar { transform:translateX(0); }
      .root.mobile-sidebar-open .sidebar-backdrop { display:block; }
      .splitter, .side-toggle-btn { display:none; }
      .quick-actions { grid-template-columns:1fr; }
      .shared-kb-bind-grid { grid-template-columns:1fr; }
      .head-controls { grid-template-columns:1fr; }
      .msg { max-width:96%; }
      .brief-grid { grid-template-columns:1fr; }
      .action { flex-direction:column; align-items:stretch; }
      .action .btn { width:100%; }
      input[type="file"] { width:100%; max-width:none; }
      .composer { max-height:40vh; }
      .trace-grid { grid-template-columns:1fr; }
      .trace-tools select { min-width:120px; width:100%; }
      .sidebar-backdrop { display:none; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <div class="global-bar">
      <div class="global-left">
        <button class="btn mobile-sidebar-btn" type="button" id="mobile-sidebar-btn" onclick="toggleMobileSidebar()">Menu</button>
        <div class="global-title" data-i18n="app_brand">Marketing Copilot</div>
      </div>
      <div class="global-actions">
        <div class="lang">
          <button class="btn" id="lang-zh" onclick="setLang('zh')">中文</button>
          <button class="btn" id="lang-en" onclick="setLang('en')">EN</button>
        </div>
        <button class="btn" onclick="gotoGroups()" data-i18n="group_mgmt">组管理</button>
        <button class="btn" onclick="gotoExperiments()" data-i18n="experiments_nav">实验中心</button>
        <button class="btn" onclick="changePassword()" data-i18n="change_password">修改密码</button>
        <button class="btn" onclick="gotoAdmin()" id="admin-btn" style="display:none" data-i18n="user_mgmt">用户管理</button>
        <button class="btn" onclick="logout()" data-i18n="logout">退出</button>
      </div>
    </div>

    <div class="root" id="app-root">
      <aside class="sidebar">
        <div class="topline">
          <div class="topline-row">
            <strong data-i18n="conversation_list">会话记录</strong>
            <button class="btn side-toggle-btn" type="button" id="toggle-sidebar-btn" onclick="toggleSidebar()">收起侧栏</button>
          </div>
          <div class="quick-actions">
            <button class="btn accent" onclick="createConversation('chat')" data-i18n="new_chat_conversation">+ 新对话</button>
            <button class="btn" onclick="createConversation('marketing')" data-i18n="new_marketing_conversation">+ 营销任务</button>
          </div>
          <div class="quick-secondary">
            <button class="btn" onclick="gotoKB()" data-i18n="kb_mgmt">Knowledge Base 管理</button>
          </div>
        </div>
        <div class="badge" id="user-badge"></div>
        <div class="chat-list" id="chat-list"></div>
      </aside>
      <div class="sidebar-backdrop" id="sidebar-backdrop" onclick="closeMobileSidebar()"></div>
      <div class="splitter" id="sidebar-splitter" role="separator" aria-orientation="vertical" aria-label="Resize sidebar"></div>

      <section class="main">
        <div class="head">
          <strong id="chat-title" data-i18n="no_conversation">未选择会话</strong>
          <div class="head-controls">
            <div class="control">
              <label for="model-select" data-i18n="model_label">模型</label>
              <select id="model-select" onchange="changeModel()"></select>
            </div>
            <div class="control">
              <label for="thinking-depth-select" data-i18n="thinking_depth_label">思考深度</label>
              <select id="thinking-depth-select" onchange="changeThinkingDepth()">
                <option value="low" data-i18n="thinking_depth_low">标准（1x）</option>
                <option value="medium" data-i18n="thinking_depth_medium">深入（2x）</option>
                <option value="high" data-i18n="thinking_depth_high">深度（4x）</option>
              </select>
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
              <button class="btn" onclick="toggleTracePanel()" id="toggle-trace-btn">编排轨迹</button>
              <button class="btn" onclick="renameConversation()" data-i18n="rename_chat">重命名</button>
              <button class="btn" onclick="deleteConversation()" data-i18n="delete_chat">删除聊天</button>
            </div>
          </div>
        </div>

        <div class="messages" id="messages"></div>

        <div class="trace-panel hidden" id="trace-panel">
          <div class="trace-head">
            <strong data-i18n="trace_title">编排轨迹</strong>
            <div class="trace-tools">
              <label for="trace-run-select" data-i18n="trace_run_label">记录</label>
              <select id="trace-run-select" onchange="onTraceRunChange()"></select>
              <button class="btn" type="button" id="toggle-trace-content-btn" onclick="toggleTraceCompact()">收起</button>
            </div>
          </div>
          <div class="trace-body" id="trace-body">
            <div class="trace-empty" id="trace-empty"></div>
            <div class="trace-grid hidden" id="trace-grid">
              <section class="trace-stage">
                <h4 data-i18n="trace_stage_brief">BriefNormalizer</h4>
                <div class="trace-story" id="trace-brief-story"></div>
                <div class="trace-line"><span class="k" data-i18n="trace_constraints">约束</span></div>
                <ul class="trace-bullets" id="trace-brief-constraints-list"></ul>
                <div class="trace-line"><span class="k" data-i18n="trace_missing">缺失字段</span></div>
                <ul class="trace-bullets" id="trace-brief-missing-list"></ul>
                <div class="trace-line"><span class="k" data-i18n="trace_assumptions">可执行假设</span></div>
                <ul class="trace-bullets" id="trace-brief-assumptions-list"></ul>
              </section>

              <section class="trace-stage">
                <h4 data-i18n="trace_stage_plan">Planner</h4>
                <div class="trace-story" id="trace-plan-story"></div>
                <div class="trace-line"><span class="k" data-i18n="trace_experiment_matrix">实验矩阵</span></div>
                <ul class="trace-bullets" id="trace-plan-experiments-list"></ul>
              </section>

              <section class="trace-stage full">
                <h4 data-i18n="trace_stage_generator">Generator</h4>
                <div class="trace-story" id="trace-generator-story"></div>
              </section>

              <section class="trace-stage full">
                <h4 data-i18n="trace_stage_eval">Evaluator</h4>
                <div class="trace-story" id="trace-eval-story"></div>
                <div class="score-grid" id="trace-eval-scores"></div>
                <div class="trace-line"><span class="k" data-i18n="trace_reasons">可追踪理由</span></div>
                <ol class="reason-list" id="trace-eval-reasons"></ol>
              </section>
            </div>
          </div>
        </div>

        <div class="composer" id="composer">
        <div class="composer-head">
          <strong data-i18n="composer_title">输入区</strong>
          <button class="btn" type="button" id="toggle-composer-btn" onclick="toggleComposer()">收起</button>
        </div>
        <div class="composer-content" id="composer-content">
        <div class="shared-kb-bind">
          <div class="shared-kb-bind-grid">
            <div>
              <label for="kb-select" data-i18n="kb_label">Knowledge Base</label>
              <select id="kb-select" onchange="changeKBKey()"></select>
            </div>
            <div>
              <label for="kb-version-select" data-i18n="kb_version_label">Knowledge Base Version</label>
              <select id="kb-version-select" onchange="changeKBVersion()"></select>
            </div>
          </div>
        </div>
        <div class="brief-card hidden" id="marketing-brief">
          <div class="brief-grid">
            <div>
              <label for="brief-channel" data-i18n="brief_channel">Channel</label>
              <select id="brief-channel" multiple size="6">
                <option value="email">email</option>
                <option value="linkedin">linkedin</option>
                <option value="x">x</option>
                <option value="wechat">wechat</option>
                <option value="landing_page">landing_page</option>
                <option value="other">other</option>
              </select>
              <div class="hint" data-i18n="brief_channel_hint">可多选（按住 Ctrl/Cmd 可连续选择）。</div>
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
            <div class="full">
              <label for="brief-extra" data-i18n="brief_extra_requirements">Extra Requirements</label>
              <textarea id="brief-extra"></textarea>
            </div>
            <div class="full">
              <label data-i18n="output_sections_label">输出内容模块</label>
              <div class="output-sections" id="output-sections">
                <label class="output-option">
                  <input type="checkbox" value="brief" />
                  <span data-i18n="output_section_brief">Brief</span>
                </label>
                <label class="output-option">
                  <input type="checkbox" value="plan" />
                  <span data-i18n="output_section_plan">Plan</span>
                </label>
                <label class="output-option">
                  <input type="checkbox" value="generator" checked />
                  <span data-i18n="output_section_generator">Marketing Content</span>
                </label>
                <label class="output-option">
                  <input type="checkbox" value="evaluation" />
                  <span data-i18n="output_section_evaluation">Evaluation</span>
                </label>
              </div>
              <div class="hint" data-i18n="output_sections_hint">可多选；不选时默认返回生成内容。</div>
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
    sidebar_collapse: '收起侧栏',
    sidebar_expand: '展开侧栏',
    mobile_sidebar_open: '菜单',
    mobile_sidebar_close: '关闭',
    new_conversation: '+ 新对话',
    new_chat_conversation: '+ 新对话',
    new_marketing_conversation: '+ 营销任务',
    no_conversation: '未选择会话',
    model_label: '模型',
    thinking_depth_label: '思考深度',
    thinking_depth_low: '标准（1x）',
    thinking_depth_medium: '深入（2x）',
    thinking_depth_high: '深度（4x）',
    mode_label: '任务模式',
    kb_label: 'Knowledge Base',
    kb_version_label: 'Knowledge Base 版本',
    kb_create: '新建 Knowledge Base 版本',
    kb_mgmt: 'Knowledge Base 管理',
    group_mgmt: '组管理',
    experiments_nav: '实验中心',
    change_password: '修改密码',
    force_change_password: '为了安全，请先修改默认密码。',
    old_password_prompt: '请输入当前密码',
    new_password_prompt: '请输入新密码（至少8位）',
    password_changed: '密码已更新，请重新登录',
    export_chat: '导出聊天',
    rename_chat: '重命名',
    brief_channel: '渠道',
    brief_channel_hint: '可多选（按住 Ctrl/Cmd 可连续选择）。',
    brief_prompt: '任务指令',
    brief_product: '产品',
    brief_audience: '受众',
    brief_objective: '目标',
    brief_extra_requirements: '额外要求',
    output_sections_label: '输出内容模块',
    output_sections_hint: '可多选；不选时默认返回生成内容。',
    output_section_brief: 'Brief（需求归一化）',
    output_section_plan: 'Plan（策略与实验）',
    output_section_generator: 'Marketing Content（生成内容）',
    output_section_evaluation: 'Evaluator（评分与风险）',
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
    request_timeout: '请求超时，请稍后重试',
    default_chat_title: '新对话',
    default_marketing_title: '新营销任务',
    upload_failed: '上传失败',
    upload_success: '上传成功',
    delete_confirm: '确定删除该聊天及其所有消息与文档吗？',
    rename_prompt: '输入新的聊天名称',
    no_chat_selected: '请先选择一个聊天',
    documents_title: '文档',
    kb_none: '不使用 Knowledge Base',
    kb_no_version: '无可用 Knowledge Base 版本',
    kb_key_prompt: '输入 Knowledge Base Key（建议英文）',
    kb_key_required: 'Knowledge Base Key 不能为空',
    kb_name_prompt: '输入 Knowledge Base 名称',
    kb_brand_voice_prompt: '输入品牌语调（可选）',
    kb_notes_prompt: '输入备注（可选）',
    kb_create_success: 'Knowledge Base 版本已创建:',
    kb_create_failed: '创建 Knowledge Base 失败',
    export_failed: '导出失败',
    rename_failed: '重命名失败',
    conversations_empty: '还没有会话，点击上方按钮开始。',
    messages_empty: '从这里开始和 Agent 对话。',
    documents_empty: '暂无上传文档。',
    trace_show: '显示编排轨迹',
    trace_hide: '隐藏编排轨迹',
    trace_compact_hide: '收起',
    trace_compact_show: '展开',
    trace_title: '编排轨迹',
    trace_run_label: '记录',
    trace_empty: '暂无可展示的编排记录。',
    trace_stage_brief: 'BriefNormalizer',
    trace_stage_plan: 'Planner',
    trace_stage_generator: 'Generator',
    trace_stage_eval: 'Evaluator',
    trace_objective: '目标',
    trace_audience: '受众',
    trace_constraints: '约束',
    trace_missing: '缺失字段',
    trace_assumptions: '可执行假设',
    trace_strategy: '策略',
    trace_experiment_matrix: '实验矩阵',
    trace_generator_output: '生成资产',
    trace_reasons: '可追踪理由',
    trace_verdict: '综合结论',
    trace_verdict_pass: '通过',
    trace_verdict_needs_revision: '需修改',
    trace_generator_preview: '以下是本次生成结果摘要：',
    trace_brief_sentence_prefix: '这次任务将聚焦于',
    trace_for_audience: '面向',
    trace_channels: '覆盖渠道',
    trace_strategy_sentence_prefix: '策略将采用',
    trace_pillars: '核心信息支柱',
    trace_funnel_stage: '漏斗阶段',
    trace_offer: '报价/利益点策略',
    trace_expected_impact: '预期影响',
    composer_title: '输入区',
    composer_hide: '收起',
    composer_show: '展开',
    score_brand: '品牌一致性',
    score_clarity: '清晰度',
    score_conversion: '转化潜力',
    score_compliance: '合规风险',
    trace_na: '无',
    shared_from: '共享自',
    no_group_needed: '无需组',
    choose_group: '请选择组'
  },
  en: {
    page_title: 'Marketing Copilot',
    app_brand: 'Marketing Copilot',
    conversation_list: 'Conversations',
    sidebar_collapse: 'Collapse Sidebar',
    sidebar_expand: 'Expand Sidebar',
    mobile_sidebar_open: 'Menu',
    mobile_sidebar_close: 'Close',
    new_conversation: '+ New Chat',
    new_chat_conversation: '+ Chat',
    new_marketing_conversation: '+ Marketing',
    no_conversation: 'No conversation selected',
    model_label: 'Model',
    thinking_depth_label: 'Thinking Depth',
    thinking_depth_low: 'Standard (1x)',
    thinking_depth_medium: 'Deep (2x)',
    thinking_depth_high: 'Maximum (4x)',
    mode_label: 'Task Mode',
    kb_label: 'Knowledge Base',
    kb_version_label: 'Knowledge Base Version',
    kb_create: 'New Knowledge Base Version',
    kb_mgmt: 'Knowledge Base Management',
    group_mgmt: 'Group Management',
    experiments_nav: 'Experiments',
    change_password: 'Change Password',
    force_change_password: 'For security, please change your default password first.',
    old_password_prompt: 'Enter current password',
    new_password_prompt: 'Enter new password (at least 8 characters)',
    password_changed: 'Password updated. Please sign in again.',
    export_chat: 'Export Chat',
    rename_chat: 'Rename',
    brief_channel: 'Channel',
    brief_channel_hint: 'Multi-select supported (hold Ctrl/Cmd to select multiple).',
    brief_prompt: 'Prompt',
    brief_product: 'Product',
    brief_audience: 'Audience',
    brief_objective: 'Objective',
    brief_extra_requirements: 'Extra Requirements',
    output_sections_label: 'Output Sections',
    output_sections_hint: 'Select one or more sections. If none is selected, marketing content is returned by default.',
    output_section_brief: 'Brief',
    output_section_plan: 'Plan',
    output_section_generator: 'Marketing Content',
    output_section_evaluation: 'Evaluation',
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
    request_timeout: 'Request timed out. Please try again.',
    default_chat_title: 'New Chat',
    default_marketing_title: 'New Marketing Task',
    upload_failed: 'Upload failed',
    upload_success: 'Upload succeeded',
    delete_confirm: 'Delete this chat with all messages and documents?',
    rename_prompt: 'Enter a new conversation title',
    no_chat_selected: 'Please select a conversation first',
    documents_title: 'Documents',
    kb_none: 'No Knowledge Base',
    kb_no_version: 'No Knowledge Base versions',
    kb_key_prompt: 'Enter Knowledge Base key (recommended: lowercase id)',
    kb_key_required: 'Knowledge Base key is required',
    kb_name_prompt: 'Enter Knowledge Base display name',
    kb_brand_voice_prompt: 'Enter brand voice (optional)',
    kb_notes_prompt: 'Enter notes (optional)',
    kb_create_success: 'Knowledge Base version created:',
    kb_create_failed: 'Failed to create Knowledge Base',
    export_failed: 'Export failed',
    rename_failed: 'Rename failed',
    conversations_empty: 'No conversations yet. Start one from above.',
    messages_empty: 'Start chatting with your agent here.',
    documents_empty: 'No uploaded documents yet.',
    trace_show: 'Show Orchestration Trace',
    trace_hide: 'Hide Orchestration Trace',
    trace_compact_hide: 'Collapse',
    trace_compact_show: 'Expand',
    trace_title: 'Orchestration Trace',
    trace_run_label: 'Run',
    trace_empty: 'No orchestration trace available yet.',
    trace_stage_brief: 'BriefNormalizer',
    trace_stage_plan: 'Planner',
    trace_stage_generator: 'Generator',
    trace_stage_eval: 'Evaluator',
    trace_objective: 'Objective',
    trace_audience: 'Audience',
    trace_constraints: 'Constraints',
    trace_missing: 'Missing Fields',
    trace_assumptions: 'Executable Assumptions',
    trace_strategy: 'Strategy',
    trace_experiment_matrix: 'Experiment Matrix',
    trace_generator_output: 'Marketing Content',
    trace_reasons: 'Traceable Reasons',
    trace_verdict: 'Overall Verdict',
    trace_verdict_pass: 'Pass',
    trace_verdict_needs_revision: 'Needs Revision',
    trace_generator_preview: 'Summary of generated output:',
    trace_brief_sentence_prefix: 'This run focuses on',
    trace_for_audience: 'for',
    trace_channels: 'across channels',
    trace_strategy_sentence_prefix: 'The strategy is built around',
    trace_pillars: 'Message pillars',
    trace_funnel_stage: 'Funnel stage',
    trace_offer: 'Offer strategy',
    trace_expected_impact: 'Expected impact',
    composer_title: 'Composer',
    composer_hide: 'Collapse',
    composer_show: 'Expand',
    score_brand: 'Brand Consistency',
    score_clarity: 'Clarity',
    score_conversion: 'Conversion Potential',
    score_compliance: 'Compliance Risk',
    trace_na: 'N/A',
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
let activeMessages = [];
let orchestratorRuns = [];
let activeTraceRunId = null;
let tracePanelVisible = false;
let traceCompact = false;
let composerCollapsed = false;
const SIDEBAR_WIDTH_MIN = 240;
const SIDEBAR_WIDTH_MAX = 520;
const SIDEBAR_WIDTH_KEY = 'nova_sidebar_width';
const SIDEBAR_COLLAPSED_KEY = 'nova_sidebar_collapsed';
let sidebarWidth = Number(localStorage.getItem(SIDEBAR_WIDTH_KEY) || 320);
if (!Number.isFinite(sidebarWidth)) {
  sidebarWidth = 320;
}
let sidebarCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1';
let sidebarResizerBound = false;
let sidebarResizing = false;
let mobileSidebarOpen = false;

function currentConversation() {
  return conversations.find((x) => x.id === activeConversationId) || null;
}

function defaultConversationTitle(taskMode='chat') {
  return taskMode === 'marketing' ? t('default_marketing_title') : t('default_chat_title');
}

function normalizeThinkingDepth(value) {
  const depth = String(value || '').toLowerCase();
  if (depth === 'medium' || depth === 'high') return depth;
  return 'low';
}

function isSystemDefaultConversationTitle(title) {
  const value = String(title || '').trim();
  return value === '新对话'
    || value === '新营销任务'
    || value === 'New Chat'
    || value === 'New Marketing Task';
}

function conversationDisplayTitle(conversation) {
  const mode = conversation && conversation.task_mode === 'marketing' ? 'marketing' : 'chat';
  const rawTitle = String((conversation && conversation.title) || '').trim();
  if (!rawTitle) return defaultConversationTitle(mode);
  if (isSystemDefaultConversationTitle(rawTitle)) return defaultConversationTitle(mode);
  return rawTitle;
}

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || key;
}

function setLang(lang) {
  currentLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('nova_lang', currentLang);
  applyI18n();
}

function clampSidebarWidth(width) {
  const num = Number(width);
  if (!Number.isFinite(num)) return 320;
  return Math.max(SIDEBAR_WIDTH_MIN, Math.min(SIDEBAR_WIDTH_MAX, num));
}

function isMobileLayout() {
  return window.innerWidth <= 900;
}

function syncMobileSidebarButton() {
  const btn = document.getElementById('mobile-sidebar-btn');
  if (!btn) return;
  btn.textContent = mobileSidebarOpen ? t('mobile_sidebar_close') : t('mobile_sidebar_open');
  btn.setAttribute('aria-expanded', mobileSidebarOpen ? 'true' : 'false');
}

function syncSidebarToggleButton() {
  const btn = document.getElementById('toggle-sidebar-btn');
  if (!btn) return;
  btn.textContent = sidebarCollapsed ? t('sidebar_expand') : t('sidebar_collapse');
}

function applySidebarLayout() {
  const root = document.getElementById('app-root');
  if (!root) return;
  if (isMobileLayout()) {
    root.classList.remove('sidebar-collapsed');
    root.classList.toggle('mobile-sidebar-open', mobileSidebarOpen);
    root.style.removeProperty('--sidebar-width');
    syncSidebarToggleButton();
    syncMobileSidebarButton();
    return;
  }
  mobileSidebarOpen = false;
  root.classList.remove('mobile-sidebar-open');
  sidebarWidth = clampSidebarWidth(sidebarWidth);
  root.style.setProperty('--sidebar-width', `${sidebarWidth}px`);
  root.classList.toggle('sidebar-collapsed', sidebarCollapsed);
  syncSidebarToggleButton();
  syncMobileSidebarButton();
}

function toggleSidebar() {
  if (isMobileLayout()) {
    toggleMobileSidebar();
    return;
  }
  sidebarCollapsed = !sidebarCollapsed;
  localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? '1' : '0');
  applySidebarLayout();
}

function toggleMobileSidebar() {
  if (!isMobileLayout()) return;
  mobileSidebarOpen = !mobileSidebarOpen;
  applySidebarLayout();
}

function closeMobileSidebar() {
  if (!isMobileLayout() || !mobileSidebarOpen) return;
  mobileSidebarOpen = false;
  applySidebarLayout();
}

function bindSidebarResizer() {
  if (sidebarResizerBound) return;
  sidebarResizerBound = true;
  const root = document.getElementById('app-root');
  const splitter = document.getElementById('sidebar-splitter');
  if (!root || !splitter) return;

  const updateWidthFromClientX = (clientX) => {
    const rect = root.getBoundingClientRect();
    sidebarWidth = clampSidebarWidth(clientX - rect.left);
    root.style.setProperty('--sidebar-width', `${sidebarWidth}px`);
  };

  splitter.addEventListener('mousedown', (event) => {
    if (isMobileLayout() || sidebarCollapsed) return;
    sidebarResizing = true;
    document.body.classList.add('sidebar-resizing');
    updateWidthFromClientX(event.clientX);
    event.preventDefault();
  });

  splitter.addEventListener('click', () => {
    if (isMobileLayout()) return;
    if (sidebarCollapsed && !sidebarResizing) {
      toggleSidebar();
    }
  });

  window.addEventListener('mousemove', (event) => {
    if (!sidebarResizing) return;
    updateWidthFromClientX(event.clientX);
  });

  window.addEventListener('mouseup', () => {
    if (!sidebarResizing) return;
    sidebarResizing = false;
    document.body.classList.remove('sidebar-resizing');
    localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
  });

  window.addEventListener('resize', () => {
    applySidebarLayout();
  });
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeMobileSidebar();
    }
  });
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
  } else {
    const active = currentConversation();
    if (active) {
      document.getElementById('chat-title').textContent = conversationDisplayTitle(active);
    }
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
  syncThinkingDepthSelect();
  syncTaskModeSelect();
  syncTaskModeUI();
  syncConversationVisibilityUI();
  syncTraceToggleButton();
  syncTraceCompactButton();
  syncComposerToggleButton();
  syncSidebarToggleButton();
  applySidebarLayout();
  renderTracePanel();
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

function selectedOutputSections() {
  const checks = [...document.querySelectorAll('#output-sections input[type="checkbox"]')];
  return checks.filter((item) => item.checked).map((item) => item.value);
}

function selectedChannels() {
  const select = document.getElementById('brief-channel');
  if (!select) return [];
  return [...select.options]
    .filter((option) => option.selected && option.value)
    .map((option) => option.value.trim().toLowerCase())
    .filter(Boolean);
}

async function api(url, options={}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = options.body instanceof FormData ? {} : {'Content-Type':'application/json'};
  if (csrfToken && ['POST','PUT','PATCH','DELETE'].includes(method)) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  const controller = options.signal ? null : new AbortController();
  const signal = options.signal || (controller ? controller.signal : undefined);
  const timeoutMs = 305000;
  const timeoutId = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  let res;
  try {
    res = await fetch(url, {headers, ...options, signal});
  } catch (err) {
    if (err && err.name === 'AbortError') {
      const timeoutError = new Error(t('request_timeout'));
      timeoutError.status = 408;
      throw timeoutError;
    }
    throw err;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }

  let data = {};
  let rawText = '';
  const contentType = (res.headers.get('content-type') || '').toLowerCase();
  if (contentType.includes('application/json')) {
    try { data = await res.json(); } catch (_) {}
  } else {
    try { rawText = await res.text(); } catch (_) {}
  }
  if (!res.ok) {
    const detail = (data && typeof data.detail === 'string' && data.detail.trim())
      ? data.detail.trim()
      : (rawText || '').trim();
    const isTimeout = [408, 502, 503, 504].includes(res.status) || /timed?\\s*out/i.test(detail);
    const message = isTimeout
      ? t('request_timeout')
      : (detail || `${t('request_failed')} (HTTP ${res.status})`);
    const error = new Error(message);
    error.status = res.status;
    throw error;
  }
  return data;
}

function parseSseBlock(block) {
  const lines = block.split('\\n');
  let event = 'message';
  const dataParts = [];
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue;
    if (line.startsWith('event:')) {
      event = line.slice(6).trim() || 'message';
      continue;
    }
    if (line.startsWith('data:')) {
      dataParts.push(line.slice(5).trim());
    }
  }
  let data = {};
  const raw = dataParts.join('\\n');
  if (raw) {
    try { data = JSON.parse(raw); } catch (_) { data = {raw}; }
  }
  return {event, data};
}

async function streamMessage(url, payload, onDelta) {
  const headers = {'Content-Type':'application/json'};
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  const controller = new AbortController();
  const timeoutMs = 305000;
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (err) {
    if (err && err.name === 'AbortError') {
      const timeoutError = new Error(t('request_timeout'));
      timeoutError.status = 408;
      throw timeoutError;
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }

  if (!res.ok) {
    let data = {};
    let rawText = '';
    try { data = await res.json(); } catch (_) {
      try { rawText = await res.text(); } catch (_) {}
    }
    const detail = (data && typeof data.detail === 'string' && data.detail.trim())
      ? data.detail.trim()
      : (rawText || '').trim();
    const isTimeout = [408, 502, 503, 504].includes(res.status) || /timed?\\s*out/i.test(detail);
    const message = isTimeout ? t('request_timeout') : (detail || `${t('request_failed')} (HTTP ${res.status})`);
    const error = new Error(message);
    error.status = res.status;
    throw error;
  }

  if (!res.body) {
    throw new Error(t('request_failed'));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let finalMessage = null;

  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    const blocks = buffer.split('\\n\\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {
      const parsed = parseSseBlock(block);
      if (parsed.event === 'delta' && parsed.data && typeof parsed.data.text === 'string') {
        onDelta(parsed.data.text);
      } else if (parsed.event === 'done' && parsed.data && parsed.data.assistant_message) {
        finalMessage = parsed.data.assistant_message;
      }
    }
  }

  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer);
    if (parsed.event === 'done' && parsed.data && parsed.data.assistant_message) {
      finalMessage = parsed.data.assistant_message;
    }
  }
  return finalMessage;
}

function createStreamRenderer(node, box) {
  let renderedText = '';
  let pendingText = '';
  let running = false;
  let finished = false;
  let resolveDone = null;
  const donePromise = new Promise((resolve) => { resolveDone = resolve; });

  async function flush() {
    if (running) return;
    running = true;
    while (pendingText.length) {
      const step = Math.min(24, Math.max(4, Math.ceil(pendingText.length * 0.18)));
      renderedText += pendingText.slice(0, step);
      pendingText = pendingText.slice(step);
      setMessageContent(node, renderedText);
      box.scrollTop = box.scrollHeight;
      await new Promise((resolve) => setTimeout(resolve, 18));
    }
    running = false;
    if (finished && resolveDone) {
      resolveDone(renderedText);
    }
  }

  return {
    push(deltaText) {
      if (!deltaText) return;
      pendingText += String(deltaText);
      flush();
    },
    async finish(finalText='') {
      const knownLength = renderedText.length + pendingText.length;
      if (finalText && finalText.length > knownLength) {
        pendingText += finalText.slice(knownLength);
        flush();
      }
      finished = true;
      if (!running && !pendingText.length && resolveDone) {
        resolveDone(renderedText);
      }
      return donePromise;
    }
  };
}

async function loadCsrfToken() {
  const res = await fetch('/api/csrf');
  if (!res.ok) throw new Error('csrf');
  const data = await res.json();
  csrfToken = data.csrf_token || '';
}

function fmt(ts) {
  try { return new Date(ts).toLocaleString(); } catch (_) { return ts; }
}

function listText(items) {
  if (!Array.isArray(items) || !items.length) return t('trace_na');
  const normalized = items.map((x) => String(x || '').trim()).filter(Boolean);
  if (!normalized.length) return t('trace_na');
  const separator = currentLang === 'en' ? ', ' : '、';
  return normalized.join(separator);
}

function listValues(items) {
  if (!Array.isArray(items)) return [];
  return items.map((x) => String(x || '').trim()).filter(Boolean);
}

function renderBulletList(containerId, items) {
  const box = document.getElementById(containerId);
  if (!box) return;
  box.innerHTML = '';
  const values = listValues(items);
  if (!values.length) {
    const li = document.createElement('li');
    li.textContent = t('trace_na');
    box.appendChild(li);
    return;
  }
  for (const value of values) {
    const li = document.createElement('li');
    li.textContent = value;
    box.appendChild(li);
  }
}

function shortText(value, maxLen=420) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return t('trace_na');
  return text.length > maxLen ? `${text.slice(0, maxLen)}...` : text;
}

function selectedTraceRun() {
  if (!orchestratorRuns.length) return null;
  if (!activeTraceRunId) return orchestratorRuns[0];
  return orchestratorRuns.find((x) => x.id === activeTraceRunId) || orchestratorRuns[0];
}

function syncTraceToggleButton() {
  const btn = document.getElementById('toggle-trace-btn');
  if (!btn) return;
  btn.textContent = tracePanelVisible ? t('trace_hide') : t('trace_show');
}

function syncTraceCompactButton() {
  const btn = document.getElementById('toggle-trace-content-btn');
  if (!btn) return;
  btn.textContent = traceCompact ? t('trace_compact_show') : t('trace_compact_hide');
}

function syncComposerToggleButton() {
  const btn = document.getElementById('toggle-composer-btn');
  if (!btn) return;
  btn.textContent = composerCollapsed ? t('composer_show') : t('composer_hide');
}

function toggleTraceCompact(forceCompact = null) {
  traceCompact = typeof forceCompact === 'boolean' ? forceCompact : !traceCompact;
  const panel = document.getElementById('trace-panel');
  const body = document.getElementById('trace-body');
  if (panel) panel.classList.toggle('compact', traceCompact);
  if (body) body.classList.toggle('hidden', traceCompact);
  syncTraceCompactButton();
}

function toggleComposer(forceCollapsed = null) {
  composerCollapsed = typeof forceCollapsed === 'boolean' ? forceCollapsed : !composerCollapsed;
  const composer = document.getElementById('composer');
  const content = document.getElementById('composer-content');
  if (composer) composer.classList.toggle('compact', composerCollapsed);
  if (content) content.classList.toggle('hidden', composerCollapsed);
  syncComposerToggleButton();
}

function toggleTracePanel(forceVisible = null) {
  tracePanelVisible = typeof forceVisible === 'boolean' ? forceVisible : !tracePanelVisible;
  const panel = document.getElementById('trace-panel');
  if (panel) panel.classList.toggle('hidden', !tracePanelVisible);
  syncTraceToggleButton();
  if (!tracePanelVisible) return;
  toggleTraceCompact(false);
  renderTracePanel();
}

function renderTraceRunSelect() {
  const select = document.getElementById('trace-run-select');
  if (!select) return;
  const previous = select.value;
  select.innerHTML = '';
  for (const run of orchestratorRuns) {
    const option = document.createElement('option');
    option.value = String(run.id);
    option.textContent = `${fmt(run.created_at)} · #${run.id}`;
    select.appendChild(option);
  }
  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  } else if (activeTraceRunId && [...select.options].some((opt) => opt.value === String(activeTraceRunId))) {
    select.value = String(activeTraceRunId);
  } else if (select.options.length) {
    select.value = select.options[0].value;
  }
}

function renderTracePanel() {
  syncTraceToggleButton();
  syncTraceCompactButton();
  const empty = document.getElementById('trace-empty');
  const grid = document.getElementById('trace-grid');
  if (!empty || !grid) return;

  renderTraceRunSelect();
  const run = selectedTraceRun();
  if (!run) {
    empty.textContent = t('trace_empty');
    empty.classList.remove('hidden');
    grid.classList.add('hidden');
    return;
  }

  const brief = run.brief || {};
  const plan = run.plan || {};
  const strategy = plan.strategy || {};
  const evaluation = run.evaluation || {};
  const responseMsg = activeMessages.find((m) => m.id === run.response_message_id);

  const sentenceSep = currentLang === 'en' ? '. ' : '。';
  const partSep = currentLang === 'en' ? ', ' : '，';
  const briefStory = `${t('trace_brief_sentence_prefix')} ${brief.objective || t('trace_na')}${partSep}${
    t('trace_for_audience')
  } ${brief.audience || t('trace_na')}${partSep}${t('trace_channels')} ${listText(brief.channel_plan)}${sentenceSep}`;
  document.getElementById('trace-brief-story').textContent = briefStory;
  renderBulletList('trace-brief-constraints-list', brief.constraints);
  renderBulletList('trace-brief-missing-list', brief.missing_info);
  renderBulletList('trace-brief-assumptions-list', brief.assumptions);

  const labelSep = currentLang === 'en' ? ': ' : '：';
  const planStory = `${t('trace_strategy_sentence_prefix')} ${strategy.positioning_angle || t('trace_na')}${sentenceSep}${
    t('trace_pillars')
  }${labelSep}${listText(strategy.message_pillars)}${sentenceSep}${t('trace_funnel_stage')}${labelSep}${
    strategy.funnel_stage || t('trace_na')
  }${sentenceSep}${t('trace_offer')}${labelSep}${strategy.offer_strategy || t('trace_na')}${sentenceSep}`;
  document.getElementById('trace-plan-story').textContent = planStory;
  const experiments = Array.isArray(plan.experiment_matrix) ? plan.experiment_matrix : [];
  const experimentLines = experiments.map((item) => {
    const name = item && item.name ? item.name : t('trace_na');
    const variantA = item && item.variant_a ? item.variant_a : 'A';
    const variantB = item && item.variant_b ? item.variant_b : 'B';
    const impact = item && item.expected_impact ? item.expected_impact : t('trace_na');
    if (currentLang === 'en') {
      return `${name}: ${variantA} vs ${variantB} (${t('trace_expected_impact')}: ${impact})`;
    }
    return `${name}：${variantA} vs ${variantB}（${t('trace_expected_impact')}：${impact}）`;
  });
  renderBulletList('trace-plan-experiments-list', experimentLines);

  const generatedText = responseMsg ? responseMsg.content || '' : '';
  document.getElementById('trace-generator-story').textContent = `${t('trace_generator_preview')} ${shortText(generatedText, 520)}`;

  const verdictRaw = String(evaluation.overall_verdict || '').toLowerCase();
  const verdictText = verdictRaw === 'pass'
    ? t('trace_verdict_pass')
    : verdictRaw === 'needs_revision'
      ? t('trace_verdict_needs_revision')
      : (verdictRaw || t('trace_na'));
  document.getElementById('trace-eval-story').textContent = `${t('trace_verdict')}: ${verdictText}`;

  const scores = evaluation.scores || {};
  const scoreBox = document.getElementById('trace-eval-scores');
  scoreBox.innerHTML = '';
  const scoreKeys = [
    ['brand_consistency', t('score_brand')],
    ['clarity', t('score_clarity')],
    ['conversion_potential', t('score_conversion')],
    ['compliance_risk', t('score_compliance')],
  ];
  for (const [key, label] of scoreKeys) {
    const item = document.createElement('div');
    item.className = 'score-item';
    item.innerHTML = `<div class="k">${label}</div><div class="v">${scores[key] ?? t('trace_na')}</div>`;
    scoreBox.appendChild(item);
  }

  const reasonBox = document.getElementById('trace-eval-reasons');
  reasonBox.innerHTML = '';
  const reasons = Array.isArray(evaluation.reasons) ? evaluation.reasons : [];
  if (reasons.length) {
    for (const reason of reasons.slice(0, 6)) {
      const li = document.createElement('li');
      const dimension = reason && reason.dimension ? `[${reason.dimension}] ` : '';
      const text = reason && reason.reason ? reason.reason : t('trace_na');
      const evidence = reason && reason.evidence ? ` (${reason.evidence})` : '';
      li.textContent = `${dimension}${text}${evidence}`;
      reasonBox.appendChild(li);
    }
  } else {
    const li = document.createElement('li');
    li.textContent = t('trace_na');
    reasonBox.appendChild(li);
  }

  empty.classList.add('hidden');
  grid.classList.remove('hidden');
}

function onTraceRunChange() {
  const select = document.getElementById('trace-run-select');
  activeTraceRunId = select && select.value ? Number(select.value) : null;
  renderTracePanel();
}

async function loadOrchestratorRuns(conversationId) {
  if (!conversationId) {
    orchestratorRuns = [];
    activeTraceRunId = null;
    renderTracePanel();
    return;
  }
  try {
    orchestratorRuns = await api(`/api/conversations/${conversationId}/orchestrator-runs`);
  } catch (_) {
    orchestratorRuns = [];
  }
  if (!orchestratorRuns.some((x) => x.id === activeTraceRunId)) {
    activeTraceRunId = orchestratorRuns.length ? orchestratorRuns[0].id : null;
  }
  renderTracePanel();
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function safeHref(rawUrl) {
  const candidate = String(rawUrl || '').trim();
  if (/^https?:\/\//i.test(candidate)) return candidate;
  if (/^mailto:/i.test(candidate)) return candidate;
  return '';
}

function formatInline(rawText) {
  let text = escapeHtml(rawText);
  const codeTokens = [];
  text = text.replace(/`([^`]+)`/g, (_, code) => {
    // Use a token that does not conflict with markdown markers like "_" or "*".
    const token = `@@CODETOKEN${codeTokens.length}@@`;
    codeTokens.push(`<code>${escapeHtml(code)}</code>`);
    return token;
  });

  text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, url) => {
    const href = safeHref(url);
    if (!href) return `${label} (${url})`;
    return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  // Keep inline emphasis conservative to avoid breaking placeholders like {PRODUCT_NAME}.
  text = text.replace(/\*\*([^*\\n]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*\\n]+)\*/g, '<em>$1</em>');

  for (let idx = 0; idx < codeTokens.length; idx += 1) {
    text = text.replace(`@@CODETOKEN${idx}@@`, codeTokens[idx]);
  }
  return text;
}

function isTableSeparatorLine(line) {
  const text = line.trim();
  if (!text.includes('|')) return false;
  const normalized = text.replace(/^\|/, '').replace(/\|$/, '');
  const cells = normalized.split('|').map((x) => x.trim());
  if (!cells.length) return false;
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function splitTableRow(line) {
  const normalized = String(line || '').trim().replace(/^\|/, '').replace(/\|$/, '');
  return normalized.split('|').map((x) => x.trim());
}

function isTsvLine(line) {
  const raw = String(line || '');
  if (!raw.includes('\t')) return false;
  const cells = raw.split('\t').map((x) => x.trim()).filter((x) => x.length > 0);
  return cells.length >= 2;
}

function splitTsvRow(line) {
  return String(line || '').split('\t').map((x) => x.trim());
}

function normalizeTableRow(row, width) {
  const cells = Array.isArray(row) ? row.slice(0, width) : [];
  while (cells.length < width) cells.push('');
  return cells;
}

function isParagraphStop(line) {
  const text = line.trim();
  if (!text) return true;
  if (/^```/.test(text)) return true;
  if (/^#{1,4}\s+/.test(text)) return true;
  if (/^(-{3,}|\*{3,}|_{3,})$/.test(text)) return true;
  if (/^>\s?/.test(text)) return true;
  if (/^[-*+]\s+/.test(text)) return true;
  if (/^\d+\.\s+/.test(text)) return true;
  if (/\t/.test(text)) return true;
  return false;
}

function markdownToHtml(rawText) {
  const lines = String(rawText || '').replace(/\\r\\n?/g, '\\n').split('\\n');
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }

    if (/^```/.test(trimmed)) {
      const codeLines = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i].trim())) {
        codeLines.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      out.push(`<pre><code>${escapeHtml(codeLines.join('\\n'))}</code></pre>`);
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      out.push(`<h${level}>${formatInline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      out.push('<hr />');
      i += 1;
      continue;
    }

    if (trimmed.includes('|') && i + 1 < lines.length && isTableSeparatorLine(lines[i + 1])) {
      const headers = splitTableRow(trimmed);
      i += 2;
      const rows = [];
      while (i < lines.length) {
        const rowLine = lines[i].trim();
        if (!rowLine || !rowLine.includes('|') || isTableSeparatorLine(rowLine)) break;
        rows.push(splitTableRow(rowLine));
        i += 1;
      }
      const width = Math.max(headers.length, ...rows.map((row) => row.length), 1);
      const normalizedHeaders = normalizeTableRow(headers, width);
      const normalizedRows = rows.map((row) => normalizeTableRow(row, width));
      const thead = `<thead><tr>${normalizedHeaders.map((cell) => `<th>${formatInline(cell)}</th>`).join('')}</tr></thead>`;
      const tbody = rows.length
        ? `<tbody>${normalizedRows.map((row) => `<tr>${row.map((cell) => `<td>${formatInline(cell)}</td>`).join('')}</tr>`).join('')}</tbody>`
        : '';
      out.push(`<table>${thead}${tbody}</table>`);
      continue;
    }

    if (isTsvLine(line)) {
      const headers = splitTsvRow(line);
      const rows = [];
      let j = i + 1;
      while (j < lines.length && isTsvLine(lines[j])) {
        rows.push(splitTsvRow(lines[j]));
        j += 1;
      }
      if (rows.length) {
        const width = Math.max(headers.length, ...rows.map((row) => row.length), 1);
        const normalizedHeaders = normalizeTableRow(headers, width);
        const normalizedRows = rows.map((row) => normalizeTableRow(row, width));
        const thead = `<thead><tr>${normalizedHeaders.map((cell) => `<th>${formatInline(cell)}</th>`).join('')}</tr></thead>`;
        const tbody = `<tbody>${normalizedRows.map((row) => `<tr>${row.map((cell) => `<td>${formatInline(cell)}</td>`).join('')}</tr>`).join('')}</tbody>`;
        out.push(`<table>${thead}${tbody}</table>`);
        i = j;
        continue;
      }
    }

    if (/^[-*+]\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length) {
        const row = lines[i].trim();
        const match = row.match(/^[-*+]\s+(.+)$/);
        if (!match) break;
        const checkMatch = match[1].match(/^\[( |x|X)\]\s+(.+)$/);
        if (checkMatch) {
          const checked = checkMatch[1].toLowerCase() === 'x';
          items.push(
            `<li class="check-item"><input type="checkbox" disabled ${checked ? 'checked' : ''} /><span>${formatInline(checkMatch[2])}</span></li>`
          );
        } else {
          items.push(`<li>${formatInline(match[1])}</li>`);
        }
        i += 1;
      }
      out.push(`<ul>${items.join('')}</ul>`);
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length) {
        const row = lines[i].trim();
        const match = row.match(/^\d+\.\s+(.+)$/);
        if (!match) break;
        items.push(`<li>${formatInline(match[1])}</li>`);
        i += 1;
      }
      out.push(`<ol>${items.join('')}</ol>`);
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      const parts = [];
      while (i < lines.length && /^>\s?/.test(lines[i].trim())) {
        parts.push(lines[i].trim().replace(/^>\s?/, ''));
        i += 1;
      }
      out.push(`<blockquote><p>${parts.map((part) => formatInline(part)).join('<br />')}</p></blockquote>`);
      continue;
    }

    const paragraph = [];
    while (i < lines.length && !isParagraphStop(lines[i])) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    out.push(`<p>${paragraph.map((part) => formatInline(part)).join('<br />')}</p>`);
  }

  return out.join('');
}

function safeMessageHtml(rawText) {
  try {
    return markdownToHtml(rawText || '');
  } catch (_) {
    return `<p>${escapeHtml(rawText || '')}</p>`;
  }
}

function setMessageContent(node, rawText) {
  const content = document.createElement('div');
  content.className = 'msg-content';
  content.innerHTML = safeMessageHtml(rawText);
  node.innerHTML = '';
  node.appendChild(content);
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

function syncThinkingDepthSelect() {
  const select = document.getElementById('thinking-depth-select');
  const active = currentConversation();
  if (!activeConversationId || !active) {
    if (!select.value) {
      select.value = 'low';
    }
    select.disabled = false;
    return;
  }
  select.disabled = false;
  select.value = normalizeThinkingDepth(active.thinking_depth);
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
  syncThinkingDepthSelect();
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
      title.textContent = conversationDisplayTitle(c);
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
      const mode = target && target.task_mode ? target.task_mode : 'chat';
      document.getElementById('chat-title').textContent = conversationDisplayTitle({title: data.title, task_mode: mode});
    }
  } catch (e) {
    alert(`${t('rename_failed')}: ${e.message}`);
  } finally {
    editingConversationId = null;
    renderConversations();
  }
}

function renderMessages(items) {
  activeMessages = Array.isArray(items) ? items : [];
  const box = document.getElementById('messages');
  box.innerHTML = '';
  if (!activeMessages.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = t('messages_empty');
    box.appendChild(empty);
    return;
  }
  for (const m of activeMessages) {
    const div = document.createElement('div');
    div.className = 'msg ' + (m.role === 'user' ? 'user' : 'assistant');
    setMessageContent(div, m.content || '');
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
  syncThinkingDepthSelect();
  syncTaskModeSelect();
  await syncKBSelects();
  syncTaskModeUI();
  syncConversationVisibilityUI();
  if (!activeConversationId) {
    await loadOrchestratorRuns(null);
  }
}

async function createConversation(taskMode='chat') {
  const localizedDefaultTitle = defaultConversationTitle(taskMode);
  const selectedDepth = normalizeThinkingDepth(document.getElementById('thinking-depth-select')?.value);
  const created = await api('/api/conversations', {
    method:'POST',
    body:JSON.stringify({
      task_mode: taskMode,
      thinking_depth: selectedDepth,
      title: localizedDefaultTitle,
      ui_language: currentLang,
      visibility: 'private',
      share_group_id: null
    })
  });
  created.title = conversationDisplayTitle(created);
  conversations.unshift(created);
  activeConversationId = created.id;
  renderConversations();
  document.getElementById('chat-title').textContent = conversationDisplayTitle(created);
  renderMessages([]);
  await loadOrchestratorRuns(created.id);
  activeDocuments = [];
  renderDocuments();
  syncModelSelect();
  syncThinkingDepthSelect();
  syncTaskModeSelect();
  await syncKBSelects();
  syncTaskModeUI();
  syncConversationVisibilityUI();
  closeMobileSidebar();
}

async function openConversation(id) {
  activeConversationId = id;
  const conv = conversations.find(x => x.id === id);
  if (conv) document.getElementById('chat-title').textContent = conversationDisplayTitle(conv);
  renderConversations();
  const items = await api(`/api/conversations/${id}/messages`);
  renderMessages(items);
  await loadDocuments(id);
  await loadOrchestratorRuns(id);
  syncModelSelect();
  syncThinkingDepthSelect();
  syncTaskModeSelect();
  await syncKBSelects();
  syncTaskModeUI();
  syncConversationVisibilityUI();
  closeMobileSidebar();
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

async function changeThinkingDepth() {
  if (!activeConversationId) return;
  const thinkingDepth = normalizeThinkingDepth(document.getElementById('thinking-depth-select').value);
  const data = await api(`/api/conversations/${activeConversationId}/thinking-depth`, {
    method:'PATCH',
    body: JSON.stringify({ thinking_depth: thinkingDepth })
  });
  conversations = conversations.map((c) => (
    c.id === activeConversationId
      ? {...c, thinking_depth: data.thinking_depth, updated_at: data.updated_at}
      : c
  ));
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
    await loadOrchestratorRuns(null);
    activeDocuments = [];
    renderDocuments();
    syncModelSelect();
    syncThinkingDepthSelect();
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
  setMessageContent(pendingUser, content);
  box.appendChild(pendingUser);

  const pendingBot = document.createElement('div');
  pendingBot.className = 'msg assistant';
  setMessageContent(pendingBot, t('thinking'));
  box.appendChild(pendingBot);
  box.scrollTop = box.scrollHeight;
  const renderer = createStreamRenderer(pendingBot, box);

  try {
    const active = currentConversation();
    const payload = { content, ui_language: currentLang };
    if (active && active.task_mode === 'marketing') {
      const channels = selectedChannels();
      payload.channels = channels;
      payload.channel = channels.length ? channels[0] : null;
      payload.product = document.getElementById('brief-product').value.trim() || null;
      payload.audience = document.getElementById('brief-audience').value.trim() || null;
      payload.objective = document.getElementById('brief-objective').value.trim() || null;
      payload.extra_requirements = document.getElementById('brief-extra').value.trim() || null;
      payload.output_sections = selectedOutputSections();
    }
    let finalText = '';
    let streamSucceeded = false;
    if (typeof ReadableStream !== 'undefined') {
      try {
        const assistantMessage = await streamMessage(`/api/conversations/${activeConversationId}/messages/stream`, payload, (delta) => {
          renderer.push(delta);
        });
        if (assistantMessage && typeof assistantMessage.content === 'string') {
          finalText = assistantMessage.content;
        }
        streamSucceeded = true;
      } catch (streamErr) {
        console.warn('stream failed, fallback to non-stream mode:', streamErr);
      }
    }
    if (!streamSucceeded) {
      const data = await api(`/api/conversations/${activeConversationId}/messages`, {
        method:'POST',
        body: JSON.stringify(payload)
      });
      finalText = data && data.assistant_message ? (data.assistant_message.content || '') : '';
      renderer.push(finalText);
    }
    const rendered = await renderer.finish(finalText || '');
    setMessageContent(pendingBot, rendered || finalText || t('request_failed'));
    const refreshedItems = await api(`/api/conversations/${activeConversationId}/messages`);
    renderMessages(refreshedItems);
    await loadOrchestratorRuns(activeConversationId);
    await loadConversations();
    renderConversations();
  } catch (e) {
    setMessageContent(pendingBot, `${t('request_error')}: ${e.message}`);
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
function gotoExperiments() { location.href = '/experiments'; }

(async function init(){
  try {
    bindSidebarResizer();
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
  } catch (e) {
    if (e && e.status === 401) {
      location.href = '/';
      return;
    }
    const message = e && e.message ? e.message : t('request_failed');
    alert(`${t('request_failed')}: ${message}`);
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
  <title>Marketing Copilot - Knowledge Base</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap');
    :root {
      --bg:#dce7f5;
      --bg-soft:#dceee7;
      --line:rgba(170,186,209,.55);
      --line-strong:rgba(136,160,191,.68);
      --txt:#102037;
      --muted:#4f647f;
      --accent:#0b6fde;
      --danger:#c63939;
      --ok:#0f766e;
      --shadow:0 22px 44px rgba(17,35,62,.16);
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      font-family:"IBM Plex Sans","Segoe UI",sans-serif;
      background:
        radial-gradient(980px 580px at -4% -20%,#eef5ff 0%,transparent 62%),
        radial-gradient(920px 520px at 104% -24%,#e8fff4 0%,transparent 64%),
        radial-gradient(760px 480px at 50% 108%,#eaf1ff 0%,transparent 68%),
        linear-gradient(160deg,var(--bg),var(--bg-soft));
      color:var(--txt);
      min-height:100vh;
    }
    body::before {
      content:"";
      position:fixed;
      inset:-18%;
      pointer-events:none;
      background:
        radial-gradient(520px 300px at 18% 24%,rgba(255,255,255,.42),transparent 70%),
        radial-gradient(500px 280px at 82% 14%,rgba(255,255,255,.34),transparent 72%),
        radial-gradient(600px 340px at 60% 84%,rgba(255,255,255,.24),transparent 74%);
      filter:blur(16px) saturate(120%);
      opacity:.9;
      z-index:0;
    }
    .wrap {
      max-width:1240px;
      margin:14px auto;
      padding:0 12px;
      position:relative;
      z-index:1;
    }
    .top {
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:10px;
      margin-bottom:10px;
      padding:8px 10px;
      border:1px solid var(--line);
      border-radius:16px;
      background:rgba(255,255,255,.56);
      box-shadow:var(--shadow);
      backdrop-filter: blur(22px) saturate(145%);
    }
    .top h2 {
      font-family:"Sora","IBM Plex Sans",sans-serif;
      margin:0;
      font-size:19px;
      letter-spacing:.1px;
    }
    .toolbar {
      display:flex;
      gap:8px;
      align-items:center;
      flex-wrap:wrap;
      justify-content:flex-end;
    }
    .lang {
      display:flex;
      gap:6px;
      padding:4px;
      border:1px solid var(--line);
      border-radius:999px;
      background:rgba(255,255,255,.52);
      backdrop-filter: blur(14px);
    }
    .lang button {
      width:auto;
      padding:5px 10px;
      border-radius:999px;
      border:0;
      box-shadow:none;
      background:transparent;
    }
    .lang button.active {
      background:var(--accent);
      color:#fff;
    }
    .top-tabs {
      display:flex;
      gap:6px;
      align-items:center;
      flex-wrap:wrap;
    }
    .tab-btn {
      width:auto;
      padding:6px 9px;
      font-size:12px;
      border-radius:10px;
    }
    .layout {
      display:grid;
      grid-template-columns: 320px 1fr;
      gap:10px;
    }
    .card {
      background:rgba(255,255,255,.56);
      border:1px solid var(--line);
      border-radius:18px;
      padding:12px;
      box-shadow:var(--shadow);
      backdrop-filter: blur(22px) saturate(145%);
    }
    .card h3 {
      margin:0 0 8px;
      font-family:"Sora","IBM Plex Sans",sans-serif;
      font-size:16px;
    }
    .list { display:flex; flex-direction:column; gap:8px; max-height:620px; overflow:auto; padding-right:2px; }
    .item {
      border:1px solid var(--line);
      border-radius:11px;
      padding:8px;
      cursor:pointer;
      background:rgba(255,255,255,.62);
      transition:.16s ease;
    }
    .item:hover { transform:translateY(-1px); border-color:var(--line-strong); }
    .item.active { border-color:var(--accent); box-shadow:0 0 0 3px rgba(10,103,211,.14); background:#fbfdff; }
    .item .name { font-weight:700; font-size:13px; }
    .item .meta { color:var(--muted); font-size:11px; margin-top:4px; font-family:"IBM Plex Mono",ui-monospace,monospace; }
    .grid { display:grid; gap:8px; grid-template-columns:1fr 1fr; }
    .full { grid-column:1 / -1; }
    label { font-size:11px; color:var(--muted); display:block; margin-bottom:4px; font-weight:600; }
    input, select, textarea, button {
      width:100%;
      box-sizing:border-box;
      padding:8px 9px;
      border-radius:10px;
      border:1px solid var(--line);
      font-family:inherit;
      transition:.16s ease;
      color:var(--txt);
      background:rgba(255,255,255,.62);
      backdrop-filter: blur(12px) saturate(130%);
    }
    input:focus, select:focus, textarea:focus {
      outline:none;
      border-color:var(--accent);
      box-shadow:0 0 0 3px rgba(10,103,211,.14);
    }
    textarea { min-height:90px; font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:12px; }
    button { cursor:pointer; font-weight:600; }
    button:hover { border-color:var(--line-strong); transform:translateY(-1px); box-shadow:0 8px 14px rgba(15,30,60,.07); }
    button.primary { background:linear-gradient(120deg,var(--accent),#0987cf); border-color:transparent; color:#fff; }
    .actions {
      display:flex;
      gap:6px;
      flex-wrap:wrap;
      justify-content:flex-start;
    }
    .actions button {
      width:auto;
      padding:6px 9px;
      font-size:12px;
    }
    .msg {
      font-size:12px;
      margin-top:8px;
      color:var(--ok);
      min-height:20px;
      border-radius:10px;
      background:rgba(243,253,249,.7);
      border:1px solid #bde9d9;
      padding:7px 10px;
    }
    .warn { color:var(--danger); background:rgba(255,246,246,.74); border-color:#f0c9c9; }
    .empty {
      border:1px dashed var(--line-strong);
      border-radius:12px;
      padding:12px;
      text-align:center;
      color:var(--muted);
      background:rgba(255,255,255,.54);
      font-size:13px;
    }
    *::-webkit-scrollbar { width:10px; height:10px; }
    *::-webkit-scrollbar-thumb { background:#c7d5e8; border-radius:999px; border:2px solid rgba(255,255,255,.9); }
    *::-webkit-scrollbar-track { background:transparent; }
    @media (max-width: 960px) {
      .layout { grid-template-columns:1fr; }
      .top { flex-direction:column; align-items:flex-start; }
      .toolbar { justify-content:flex-start; width:100%; }
      .top-tabs { width:100%; }
      .actions button { width:100%; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <h2 data-i18n="title">Knowledge Base 管理</h2>
      <div class="toolbar">
        <div class="lang">
          <button id="lang-zh" onclick="setLang('zh')">中文</button>
          <button id="lang-en" onclick="setLang('en')">EN</button>
        </div>
        <div class="top-tabs">
          <button class="tab-btn" onclick="gotoExperiments()" data-i18n="experiments_nav">实验中心</button>
          <button class="tab-btn" onclick="backToApp()" data-i18n="back">返回聊天</button>
          <button class="tab-btn" onclick="logout()" data-i18n="logout">退出</button>
        </div>
      </div>
    </div>
    <div class="layout">
      <div class="card">
        <h3 data-i18n="kb_list">Knowledge Base 列表</h3>
        <div id="kb-list" class="list"></div>
      </div>
      <div class="card">
        <div class="grid">
          <div>
            <label for="kb-key-select" data-i18n="select_key">选择 Knowledge Base Key</label>
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
            <label for="kb-name" data-i18n="kb_name">Knowledge Base 名称</label>
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
    title: 'Knowledge Base 管理',
    experiments_nav: '实验中心',
    back: '返回聊天',
    logout: '退出',
    kb_list: 'Knowledge Base 列表',
    select_key: '选择 Knowledge Base Key',
    select_version: '选择版本',
    visibility_label: '可见范围',
    visibility_private: '仅自己',
    visibility_task: '任务小组',
    visibility_company: '公司组',
    group_label: '共享组',
    no_group_needed: '无需组',
    new_key: '新版本目标 Key（可新建）',
    kb_name: 'Knowledge Base 名称',
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
    delete_confirm: '确定删除该 Knowledge Base 版本吗？',
    required_key: '请输入 Knowledge Base Key',
    invalid_json: 'JSON 格式错误',
    kb_empty: '还没有 Knowledge Base 版本，请先在右侧创建。',
    shared_from: '共享自'
  },
  en: {
    title: 'Knowledge Base Management',
    experiments_nav: 'Experiments',
    back: 'Back to Chat',
    logout: 'Log Out',
    kb_list: 'Knowledge Base List',
    select_key: 'Select Knowledge Base Key',
    select_version: 'Select Version',
    visibility_label: 'Visibility',
    visibility_private: 'Private',
    visibility_task: 'Task Group',
    visibility_company: 'Company Group',
    group_label: 'Share Group',
    no_group_needed: 'No group needed',
    new_key: 'Target key for new version',
    kb_name: 'Knowledge Base Name',
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
    delete_confirm: 'Delete this Knowledge Base version?',
    required_key: 'Knowledge Base key is required',
    invalid_json: 'Invalid JSON',
    kb_empty: 'No Knowledge Base versions yet. Create one from the form.',
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
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const err = new Error(data.detail || 'Request failed');
    err.status = res.status;
    throw err;
  }
  return data;
}
async function loadCsrfToken() {
  const res = await fetch('/api/csrf');
  if (!res.ok) {
    let data = {};
    try { data = await res.json(); } catch (_) {}
    const err = new Error(data.detail || 'csrf');
    err.status = res.status;
    throw err;
  }
  const data = await res.json();
  csrfToken = data.csrf_token || '';
}
function isAuthError(err) {
  const status = err && typeof err === 'object' ? err.status : null;
  return status === 401;
}
function setInitError(message) {
  const msg = document.getElementById('create-msg');
  if (!msg) return;
  msg.textContent = `${t('save_fail')}: ${message || t('save_fail')}`;
  msg.className = 'small warn';
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
function gotoExperiments() { location.href = '/experiments'; }

(async function init() {
  applyI18n();
  try {
    await loadCsrfToken();
    me = await api('/api/me');
    await loadMyGroups();
    await refreshKBList();
  } catch (_) {
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
    .card-span-2 { grid-column:1 / -1; }
    h2, h3 { margin:0 0 10px; }
    .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px; }
    input, select, button { padding:8px 10px; border:1px solid #d6dfec; border-radius:10px; background:#fff; }
    button { cursor:pointer; font-weight:600; }
    button.danger { border-color:#fecaca; color:#b91c1c; background:#fff5f5; }
    button.danger:hover { background:#fee2e2; }
    .list { display:flex; flex-direction:column; gap:8px; max-height:260px; overflow:auto; }
    .item { border:1px solid #d6dfec; border-radius:10px; padding:8px; }
    .manage-groups { display:grid; gap:12px; }
    .group-panel { border:1px solid #d6dfec; border-radius:14px; padding:12px; background:linear-gradient(180deg,#ffffff,#f8fbff); }
    .panel-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; margin-bottom:10px; }
    .panel-head strong { display:block; margin-bottom:4px; }
    .panel-meta { font-size:12px; color:#5b6b80; }
    .pill { display:inline-flex; align-items:center; gap:4px; border:1px solid #d6dfec; border-radius:999px; padding:4px 8px; font-size:12px; color:#375072; background:#f8fbff; white-space:nowrap; }
    .panel-sections { display:grid; gap:10px; }
    .section-block { border-top:1px solid #e4ebf4; padding-top:10px; }
    .section-title { font-size:12px; font-weight:700; color:#5b6b80; text-transform:uppercase; letter-spacing:.04em; margin-bottom:6px; }
    .section-list { display:flex; flex-direction:column; gap:8px; }
    .section-list .item { padding:8px 10px; }
    .header-row { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:10px; flex-wrap:wrap; }
    .header-row select { min-width:240px; }
    .meta { font-size:12px; color:#5b6b80; margin-top:4px; }
    .small { font-size:12px; color:#5b6b80; }
    .ok { color:#0f766e; }
    .warn { color:#b91c1c; }
    @media (max-width: 980px) {
      .layout { grid-template-columns:1fr; }
      .top { flex-direction:column; align-items:flex-start; }
      .toolbar {
        width:100%;
        flex-wrap:nowrap;
        overflow-x:auto;
        padding-bottom:2px;
      }
      .toolbar button { flex:0 0 auto; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <h2 data-i18n="title">组管理</h2>
      <div class="toolbar">
        <button id="lang-zh" onclick="setLang('zh')">中文</button>
        <button id="lang-en" onclick="setLang('en')">EN</button>
        <button onclick="gotoExperiments()" data-i18n="experiments_nav">实验中心</button>
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
        <div id="my-groups" class="list"></div>
      </div>

      <div class="card">
        <h3 data-i18n="all_groups">可加入的组</h3>
        <div id="all-groups" class="list"></div>
        <h3 style="margin-top:14px" data-i18n="invites">我的邀请</h3>
        <div id="invites" class="list"></div>
      </div>

      <div class="card card-span-2">
        <div class="header-row">
          <h3 data-i18n="members">组成员</h3>
          <select id="manage-group-select" onchange="changeManageGroup()"></select>
        </div>
        <div id="manage-groups" class="manage-groups">
          <div class="group-panel">
            <div class="panel-sections">
              <div class="section-block">
                <div class="section-title" data-i18n="members">组成员</div>
                <div id="members" class="section-list"></div>
              </div>
              <div class="section-block">
                <div class="section-title" data-i18n="requests">待审批请求</div>
                <div id="requests" class="section-list"></div>
              </div>
              <div class="section-block">
                <div class="section-title" data-i18n="invite">邀请</div>
                <div class="row">
                  <input id="invite-username" data-i18n-placeholder="invite_user" placeholder="邀请用户名" />
                  <button id="invite-btn" onclick="inviteUser()" data-i18n="invite">邀请</button>
                </div>
                <div class="row">
                  <input id="transfer-user-id" data-i18n-placeholder="transfer_user_id" placeholder="新管理员 user_id" />
                  <button id="transfer-btn" onclick="transferAdmin()" data-i18n="transfer_admin">转移管理员</button>
                </div>
                <div id="manage-msg" class="small"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

<script>
const I18N = {
  zh: {
    title: '组管理',
    experiments_nav: '实验中心',
    back: '返回聊天',
    logout: '退出',
    create_group: '创建组',
    group_name: '组名称',
    company_group: '公司组',
    task_group: '任务小组',
    create: '创建',
    my_groups: '我的组',
    group_details: '分组详情',
    all_groups: '可加入的组',
    invites: '我的邀请',
    members: '组成员',
    requests: '待审批请求',
    invite_user: '邀请用户名',
    invite: '邀请',
    transfer_user_id: '新管理员 user_id',
    transfer_admin: '转移管理员',
    join: '申请加入',
    leave_group: '退出组',
    delete_group: '解散组',
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
    save_fail: '操作失败',
    request_failed: '请求失败',
    name_too_short: '组名称至少需要 2 个字符',
    auth_expired: '登录已过期，请重新登录',
    not_approved: '当前组成员资格未批准，暂不可查看详情',
    admin_only: '仅组管理员可查看审批请求并执行管理操作',
    confirm_leave_group: '确认退出这个组吗？',
    confirm_delete_group: '确认解散这个组吗？该组共享内容会转为私有。',
    left_group: '已退出组',
    deleted_group: '组已解散'
  },
  en: {
    title: 'Group Management',
    experiments_nav: 'Experiments',
    back: 'Back to Chat',
    logout: 'Log Out',
    create_group: 'Create Group',
    group_name: 'Group name',
    company_group: 'Company Group',
    task_group: 'Task Group',
    create: 'Create',
    my_groups: 'My Groups',
    group_details: 'Group Details',
    all_groups: 'Discover Groups',
    invites: 'My Invitations',
    members: 'Members',
    requests: 'Pending Requests',
    invite_user: 'Username to invite',
    invite: 'Invite',
    transfer_user_id: 'New admin user_id',
    transfer_admin: 'Transfer Admin',
    join: 'Request Join',
    leave_group: 'Leave Group',
    delete_group: 'Delete Group',
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
    save_fail: 'Operation failed',
    request_failed: 'Request failed',
    name_too_short: 'Group name must be at least 2 characters',
    auth_expired: 'Your session expired. Please sign in again.',
    not_approved: 'Your membership is not approved yet. Group details are unavailable.',
    admin_only: 'Only group admins can review requests and run management actions.',
    confirm_leave_group: 'Leave this group?',
    confirm_delete_group: 'Delete this group? Shared content under this group will become private.',
    left_group: 'You left the group.',
    deleted_group: 'Group deleted.'
  }
};

let currentLang = localStorage.getItem('nova_lang') || 'zh';
let me = null;
let myGroups = [];
let allGroups = [];
let groupInvites = [];
let manageGroups = [];
let activeManageGroupId = '';
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
  const res = await fetch(url, {headers, credentials:'same-origin', ...options});
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const err = new Error(data.detail || t('request_failed'));
    err.status = res.status;
    throw err;
  }
  return data;
}
async function loadCsrfToken() {
  const res = await fetch('/api/csrf', {credentials:'same-origin'});
  if (!res.ok) {
    let data = {};
    try { data = await res.json(); } catch (_) {}
    const err = new Error(data.detail || 'csrf');
    err.status = res.status;
    throw err;
  }
  const data = await res.json();
  csrfToken = data.csrf_token || '';
}
function isAuthError(err) {
  const status = err && typeof err === 'object' ? err.status : null;
  return status === 401;
}
function setInitError(message) {
  const msg = document.getElementById('create-msg');
  if (!msg) return;
  msg.textContent = `${t('save_fail')}: ${message || t('request_failed')}`;
  msg.className = 'small warn';
}
function roleLabel(role) { return role === 'admin' ? t('admin') : t('member'); }
function statusLabel(status) {
  if (status === 'approved') return t('approved');
  if (status === 'pending') return t('pending');
  if (status === 'invited') return t('invited');
  return status || '';
}
function groupTypeLabel(groupType) {
  return groupType === 'company' ? t('company_group') : t('task_group');
}
function canDeleteGroup(group) {
  if (!group || !me) return false;
  return Boolean(me.is_admin || (group.role === 'admin' && group.status === 'approved'));
}
function renderAll() {
  renderMyGroups();
  renderDiscoverGroups();
  renderInvites();
  renderManageGroupDetails();
}
function renderMyGroups() {
  const box = document.getElementById('my-groups');
  box.innerHTML = '';
  if (!myGroups.length) {
    box.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    return;
  }
  for (const g of myGroups) {
    const item = document.createElement('div');
    item.className = 'item';
    const actions = [];
    actions.push(`<button onclick="leaveGroup(${g.id})">${t('leave_group')}</button>`);
    if (canDeleteGroup(g)) {
      actions.push(`<button class="danger" onclick="deleteGroup(${g.id})">${t('delete_group')}</button>`);
    }
    item.innerHTML = `
      <div><strong>${g.name}</strong> (${groupTypeLabel(g.group_type)})</div>
      <div class="meta">${roleLabel(g.role)} · ${statusLabel(g.status)}</div>
      <div class="row" style="margin-top:6px">${actions.join('')}</div>
    `;
    box.appendChild(item);
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
    const actions = [];
    if (!g.my_status) {
      actions.push(`<button onclick="joinGroup(${g.id})">${t('join')}</button>`);
    }
    if (me && me.is_admin) {
      actions.push(`<button class="danger" onclick="deleteGroup(${g.id})">${t('delete_group')}</button>`);
    }
    item.innerHTML = `
      <div><strong>${g.name}</strong> (${groupTypeLabel(g.group_type)})</div>
      <div class="meta">${t('members')}: ${g.approved_member_count}${status ? ` · ${status}` : ''}</div>
      <div class="row" style="margin-top:6px">${actions.join('')}</div>`;
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
  await loadManageGroups();
  renderAll();
}
async function loadInvites() {
  groupInvites = await api('/api/groups/invitations');
}
function renderInvites() {
  const box = document.getElementById('invites');
  box.innerHTML = '';
  if (!groupInvites.length) {
    box.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    return;
  }
  for (const inv of groupInvites) {
    const item = document.createElement('div');
    item.className = 'item';
    item.innerHTML = `
      <div><strong>${inv.name}</strong> (${groupTypeLabel(inv.group_type)})</div>
      <div class="meta">${inv.invited_by || ''}</div>
      <div class="row" style="margin-top:6px">
        <button onclick="acceptInvite(${inv.group_id})">${t('accept')}</button>
        <button onclick="rejectInvite(${inv.group_id})">${t('reject')}</button>
      </div>`;
    box.appendChild(item);
  }
}
async function loadManageGroups() {
  const approvedGroups = myGroups.filter((g) => g.status === 'approved');
  if (!approvedGroups.length) {
    manageGroups = [];
    return;
  }
  manageGroups = await Promise.all(approvedGroups.map(async (group) => {
    let members = [];
    let requests = [];
    let memberError = '';
    let requestError = '';
    try {
      members = await api(`/api/groups/${group.id}/members`);
    } catch (e) {
      if (isAuthError(e)) throw e;
      memberError = e.message || t('request_failed');
    }
    if (group.role === 'admin') {
      try {
        requests = await api(`/api/groups/${group.id}/requests`);
      } catch (e) {
        if (isAuthError(e)) throw e;
        requestError = e.message || t('request_failed');
      }
    }
    return {...group, members, requests, memberError, requestError};
  }));
}
function changeManageGroup() {
  const select = document.getElementById('manage-group-select');
  activeManageGroupId = select && select.value ? String(select.value) : '';
  renderManageGroupDetails();
}
function toggleManageActions(enabled) {
  const inviteInput = document.getElementById('invite-username');
  const inviteBtn = document.getElementById('invite-btn');
  const transferInput = document.getElementById('transfer-user-id');
  const transferBtn = document.getElementById('transfer-btn');
  [inviteInput, inviteBtn, transferInput, transferBtn].forEach((el) => {
    if (el) el.disabled = !enabled;
  });
}
function renderManageGroupDetails() {
  const select = document.getElementById('manage-group-select');
  const membersBox = document.getElementById('members');
  const requestsBox = document.getElementById('requests');
  const manageMsg = document.getElementById('manage-msg');
  const container = document.getElementById('manage-groups');
  if (!select || !membersBox || !requestsBox || !manageMsg || !container) return;

  select.innerHTML = '';
  manageMsg.textContent = '';
  manageMsg.className = 'small';
  membersBox.innerHTML = '';
  requestsBox.innerHTML = '';

  if (!manageGroups.length) {
    activeManageGroupId = '';
    const option = document.createElement('option');
    option.value = '';
    option.textContent = t('no_data');
    select.appendChild(option);
    select.disabled = true;
    container.style.display = 'none';
    return;
  }

  container.style.display = '';
  select.disabled = false;
  for (const group of manageGroups) {
    const option = document.createElement('option');
    option.value = String(group.id);
    option.textContent = `${group.name} (${groupTypeLabel(group.group_type)})`;
    select.appendChild(option);
  }
  if (!activeManageGroupId || !manageGroups.some((group) => String(group.id) === String(activeManageGroupId))) {
    activeManageGroupId = String(manageGroups[0].id);
  }
  select.value = activeManageGroupId;

  const group = manageGroups.find((item) => String(item.id) === String(activeManageGroupId));
  if (!group) {
    membersBox.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    requestsBox.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    toggleManageActions(false);
    return;
  }

  if (group.memberError) {
    membersBox.innerHTML = `<div class="item small warn">${group.memberError}</div>`;
  } else if (!group.members.length) {
    membersBox.innerHTML = `<div class="item small">${t('no_data')}</div>`;
  } else {
    membersBox.innerHTML = group.members.map((member) => `
      <div class="item">
        <div><strong>${member.username}</strong> (#${member.user_id})</div>
        <div class="meta">${roleLabel(member.role)} · ${statusLabel(member.status)}</div>
      </div>
    `).join('');
  }

  if (group.role !== 'admin') {
    requestsBox.innerHTML = `<div class="item small">${t('admin_only')}</div>`;
    toggleManageActions(false);
    return;
  }

  toggleManageActions(true);
  if (group.requestError) {
    requestsBox.innerHTML = `<div class="item small warn">${group.requestError}</div>`;
    return;
  }
  if (!group.requests.length) {
    requestsBox.innerHTML = `<div class="item small">${t('no_data')}</div>`;
    return;
  }
  requestsBox.innerHTML = group.requests.map((request) => `
    <div class="item">
      <div><strong>${request.username}</strong> (#${request.user_id})</div>
      <div class="meta">${statusLabel(request.status)}</div>
      <div class="row" style="margin-top:6px">
        <button onclick="approveRequest(${group.id}, ${request.user_id})">${t('approve')}</button>
        <button onclick="rejectRequest(${group.id}, ${request.user_id})">${t('reject')}</button>
      </div>
    </div>
  `).join('');
}
async function createGroup() {
  const name = document.getElementById('new-group-name').value.trim();
  const group_type = document.getElementById('new-group-type').value;
  const msg = document.getElementById('create-msg');
  if (name.length < 2) {
    msg.textContent = t('name_too_short');
    msg.className = 'small warn';
    return;
  }
  try {
    if (!csrfToken) {
      await loadCsrfToken();
    }
    await api('/api/groups', {method:'POST', body: JSON.stringify({name, group_type})});
    document.getElementById('new-group-name').value = '';
    msg.textContent = t('save_ok');
    msg.className = 'small ok';
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    msg.textContent = `${t('save_fail')}: ${e.message}`;
    msg.className = 'small warn';
  }
}
async function joinGroup(groupId) {
  try {
    await api(`/api/groups/${groupId}/join`, {method:'POST'});
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    alert(e.message);
  }
}
async function leaveGroup(groupId) {
  if (!confirm(t('confirm_leave_group'))) return;
  const msg = document.getElementById('create-msg');
  try {
    await api(`/api/groups/${groupId}/leave`, {method:'POST'});
    msg.textContent = t('left_group');
    msg.className = 'small ok';
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    msg.textContent = `${t('save_fail')}: ${e.message}`;
    msg.className = 'small warn';
  }
}
async function deleteGroup(groupId) {
  if (!confirm(t('confirm_delete_group'))) return;
  const msg = document.getElementById('create-msg');
  try {
    await api(`/api/groups/${groupId}`, {method:'DELETE'});
    msg.textContent = t('deleted_group');
    msg.className = 'small ok';
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    msg.textContent = `${t('save_fail')}: ${e.message}`;
    msg.className = 'small warn';
  }
}
async function acceptInvite(groupId) {
  try {
    await api(`/api/groups/${groupId}/invitations/accept`, {method:'POST'});
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    alert(e.message);
  }
}
async function rejectInvite(groupId) {
  try {
    await api(`/api/groups/${groupId}/invitations/reject`, {method:'POST'});
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    alert(e.message);
  }
}
async function approveRequest(groupId, userId) {
  try {
    await api(`/api/groups/${groupId}/requests/${userId}/approve`, {method:'POST'});
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    alert(e.message);
  }
}
async function rejectRequest(groupId, userId) {
  try {
    await api(`/api/groups/${groupId}/requests/${userId}/reject`, {method:'POST'});
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    alert(e.message);
  }
}
function setManageMessage(message, kind) {
  const box = document.getElementById('manage-msg');
  if (!box) return;
  box.textContent = message;
  box.className = `small ${kind || ''}`.trim();
}
async function inviteUser() {
  if (!activeManageGroupId) return;
  const input = document.getElementById('invite-username');
  if (!input) return;
  const username = input.value.trim();
  if (!username) {
    setManageMessage(`${t('save_fail')}: ${t('invite_user')}`, 'warn');
    return;
  }
  try {
    await api(`/api/groups/${activeManageGroupId}/invite`, {method:'POST', body: JSON.stringify({username})});
    input.value = '';
    setManageMessage(t('save_ok'), 'ok');
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    setManageMessage(`${t('save_fail')}: ${e.message}`, 'warn');
  }
}
async function transferAdmin() {
  if (!activeManageGroupId) return;
  const input = document.getElementById('transfer-user-id');
  if (!input) return;
  const new_admin_user_id = Number(input.value);
  if (!new_admin_user_id) {
    setManageMessage(`${t('save_fail')}: ${t('transfer_user_id')}`, 'warn');
    return;
  }
  try {
    await api(`/api/groups/${activeManageGroupId}/transfer-admin`, {
      method:'POST',
      body: JSON.stringify({new_admin_user_id})
    });
    input.value = '';
    setManageMessage(t('save_ok'), 'ok');
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    setManageMessage(`${t('save_fail')}: ${e.message}`, 'warn');
  }
}
async function logout() { await api('/logout', {method:'POST'}); location.href = '/'; }
function backToApp() { location.href = '/app'; }
function gotoExperiments() { location.href = '/experiments'; }

(async function init() {
  applyI18n();
  try {
    await loadCsrfToken();
    await refreshData();
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    setInitError(e.message || 'init');
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
      .top { flex-direction:column; align-items:flex-start; }
      .toolbar {
        width:100%;
        flex-wrap:nowrap;
        overflow-x:auto;
        padding-bottom:2px;
      }
      .toolbar button { flex:0 0 auto; }
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
        <button onclick="gotoExperiments()" data-i18n="experiments_nav">Experiments</button>
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
    experiments_nav: '实验中心',
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
    experiments_nav: 'Experiments',
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
let csrfToken = '';

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
  try { return new Date(ts).toLocaleString(); } catch (_) { return ts; }
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
function gotoExperiments() { location.href = '/experiments'; }

(async function init() {
  applyI18n();
  try {
    await loadCsrfToken();
    await loadUsers();
  } catch (_) {
    location.href = '/app';
  }
})();
</script>
</body>
</html>
"""


EXPERIMENTS_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Marketing Copilot - Experiments</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap');
    :root {
      --bg:#dce7f5;
      --bg-soft:#dceee7;
      --line:rgba(170,186,209,.55);
      --line-strong:rgba(136,160,191,.68);
      --txt:#102037;
      --muted:#4f647f;
      --accent:#0b6fde;
      --ok:#0f766e;
      --danger:#c53939;
      --shadow:0 22px 44px rgba(17,35,62,.16);
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      font-family:"IBM Plex Sans","Segoe UI",sans-serif;
      background:
        radial-gradient(980px 580px at -4% -20%,#eef5ff 0%,transparent 62%),
        radial-gradient(920px 520px at 104% -24%,#e8fff4 0%,transparent 64%),
        radial-gradient(760px 480px at 50% 108%,#eaf1ff 0%,transparent 68%),
        linear-gradient(160deg,var(--bg),var(--bg-soft));
      color:var(--txt);
      min-height:100vh;
    }
    body::before {
      content:"";
      position:fixed;
      inset:-18%;
      pointer-events:none;
      background:
        radial-gradient(520px 300px at 18% 24%,rgba(255,255,255,.42),transparent 70%),
        radial-gradient(500px 280px at 82% 14%,rgba(255,255,255,.34),transparent 72%),
        radial-gradient(600px 340px at 60% 84%,rgba(255,255,255,.24),transparent 74%);
      filter:blur(16px) saturate(120%);
      opacity:.9;
      z-index:0;
    }
    .wrap {
      max-width:1240px;
      margin:14px auto;
      padding:0 12px;
      position:relative;
      z-index:1;
    }
    .top {
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:10px;
      margin-bottom:10px;
      padding:8px 10px;
      border:1px solid var(--line);
      border-radius:16px;
      background:rgba(255,255,255,.56);
      box-shadow:var(--shadow);
      backdrop-filter: blur(22px) saturate(145%);
    }
    .top h2 {
      margin:0;
      font-family:"Sora","IBM Plex Sans",sans-serif;
      font-size:19px;
      letter-spacing:.1px;
    }
    .toolbar {
      display:flex;
      gap:8px;
      align-items:center;
      flex-wrap:wrap;
      justify-content:flex-end;
    }
    .lang {
      display:flex;
      gap:6px;
      padding:4px;
      border:1px solid var(--line);
      border-radius:999px;
      background:rgba(255,255,255,.52);
      backdrop-filter: blur(14px);
    }
    .lang button {
      width:auto;
      padding:5px 10px;
      border-radius:999px;
      border:0;
      box-shadow:none;
      background:transparent;
    }
    .lang button.active {
      background:var(--accent);
      color:#fff;
    }
    .top-tabs {
      display:flex;
      gap:6px;
      align-items:center;
      flex-wrap:wrap;
    }
    .tab-btn {
      width:auto;
      padding:6px 9px;
      font-size:12px;
      border-radius:10px;
    }
    .layout { display:grid; grid-template-columns: 320px 1fr; gap:10px; }
    .card {
      background:rgba(255,255,255,.56);
      border:1px solid var(--line);
      border-radius:18px;
      padding:12px;
      box-shadow:var(--shadow);
      backdrop-filter: blur(22px) saturate(145%);
    }
    .card h3 { margin:0 0 8px; font-family:"Sora","IBM Plex Sans",sans-serif; font-size:16px; }
    label {
      font-size:11px;
      color:var(--muted);
      display:block;
      margin-bottom:4px;
      font-weight:600;
    }
    input, select, textarea, button {
      width:100%;
      box-sizing:border-box;
      padding:8px 9px;
      border-radius:10px;
      border:1px solid var(--line);
      font-family:inherit;
      color:var(--txt);
      background:rgba(255,255,255,.62);
      backdrop-filter: blur(12px) saturate(130%);
      transition:.16s ease;
    }
    textarea {
      min-height:90px;
      font-family:"IBM Plex Mono",ui-monospace,monospace;
      font-size:12px;
      resize:vertical;
    }
    input:focus, select:focus, textarea:focus {
      outline:none;
      border-color:var(--accent);
      box-shadow:0 0 0 3px rgba(10,103,211,.14);
    }
    button { cursor:pointer; font-weight:600; }
    button:hover { border-color:var(--line-strong); transform:translateY(-1px); box-shadow:0 8px 14px rgba(15,30,60,.07); }
    button.primary { background:linear-gradient(120deg,var(--accent),#0987cf); border-color:transparent; color:#fff; }
    .list {
      display:flex;
      flex-direction:column;
      gap:8px;
      max-height:620px;
      overflow:auto;
      padding-right:2px;
      margin-bottom:8px;
    }
    .item {
      border:1px solid var(--line);
      border-radius:11px;
      padding:8px;
      cursor:pointer;
      background:rgba(255,255,255,.62);
      transition:.16s ease;
    }
    .item:hover { transform:translateY(-1px); border-color:var(--line-strong); }
    .item.active { border-color:var(--accent); box-shadow:0 0 0 3px rgba(10,103,211,.14); background:#fbfdff; }
    .item .name { font-weight:700; font-size:13px; }
    .item .meta { color:var(--muted); font-size:11px; margin-top:4px; font-family:"IBM Plex Mono",ui-monospace,monospace; }
    .empty {
      border:1px dashed var(--line-strong);
      border-radius:12px;
      padding:12px;
      text-align:center;
      color:var(--muted);
      background:rgba(255,255,255,.54);
      font-size:13px;
    }
    .grid { display:grid; gap:8px; grid-template-columns:1fr 1fr; }
    .full { grid-column:1 / -1; }
    .section-title { margin:12px 0 8px; font-size:13px; font-weight:700; color:#1b2f4d; }
    .actions { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; justify-content:flex-start; }
    .actions button { width:auto; padding:6px 9px; font-size:12px; }
    .msg {
      font-size:12px;
      margin-top:8px;
      color:var(--ok);
      min-height:20px;
      border-radius:10px;
      background:rgba(243,253,249,.7);
      border:1px solid #bde9d9;
      padding:7px 10px;
    }
    .warn { color:var(--danger); background:rgba(255,246,246,.74); border-color:#f0c9c9; }
    #exp-detail-panel.hidden, #exp-detail-empty.hidden { display:none; }
    .mono { font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:12px; }
    .variant-card {
      border:1px solid var(--line);
      border-radius:12px;
      padding:8px;
      background:rgba(255,255,255,.62);
      margin-bottom:8px;
    }
    .variant-card .key {
      font-family:"IBM Plex Mono",ui-monospace,monospace;
      font-size:12px;
      color:#355174;
      margin-bottom:6px;
      text-transform:uppercase;
    }
    *::-webkit-scrollbar { width:10px; height:10px; }
    *::-webkit-scrollbar-thumb { background:#c7d5e8; border-radius:999px; border:2px solid rgba(255,255,255,.9); }
    *::-webkit-scrollbar-track { background:transparent; }
    @media (max-width: 1000px) {
      .layout { grid-template-columns:1fr; }
      .top { flex-direction:column; align-items:flex-start; }
      .toolbar { justify-content:flex-start; width:100%; }
      .top-tabs { width:100%; }
      .grid { grid-template-columns:1fr; }
      .actions button { width:100%; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <h2 data-i18n="title">实验中心</h2>
      <div class="toolbar">
        <div class="lang">
          <button id="lang-zh" onclick="setLang('zh')">中文</button>
          <button id="lang-en" onclick="setLang('en')">EN</button>
        </div>
        <div class="top-tabs">
          <button class="tab-btn" onclick="gotoApp()" data-i18n="back">返回聊天</button>
          <button class="tab-btn" onclick="gotoKB()" data-i18n="kb_nav">Knowledge Base 管理</button>
          <button class="tab-btn" onclick="gotoGroups()" data-i18n="group_nav">组管理</button>
          <button class="tab-btn" onclick="gotoAdmin()" id="admin-btn" style="display:none" data-i18n="admin_nav">用户管理</button>
          <button class="tab-btn" onclick="logout()" data-i18n="logout">退出</button>
        </div>
      </div>
    </div>

    <div class="layout">
      <div class="card">
        <h3 data-i18n="exp_list">实验列表</h3>
        <div id="exp-list" class="list"></div>

        <h3 data-i18n="create_exp">创建实验</h3>
        <label for="create-title" data-i18n="title_label">标题</label>
        <input id="create-title" />
        <label for="create-hypothesis" data-i18n="hypothesis_label">假设</label>
        <textarea id="create-hypothesis"></textarea>
        <label for="create-conversation" data-i18n="conversation_label">关联会话（可选）</label>
        <select id="create-conversation"></select>
        <label for="create-traffic" data-i18n="traffic_label">流量分配 JSON（可选）</label>
        <textarea id="create-traffic">{"A":50,"B":50}</textarea>
        <div class="actions">
          <button class="primary" onclick="createExperiment()" data-i18n="create_btn">创建</button>
        </div>
      </div>

      <div class="card">
        <h3 id="exp-detail-title" data-i18n="detail_title">实验详情</h3>
        <div id="exp-detail-empty" class="empty"></div>

        <div id="exp-detail-panel" class="hidden">
          <div class="grid">
            <div class="full">
              <label for="detail-name-input" data-i18n="detail_name">实验名称</label>
              <input id="detail-name-input" />
            </div>
            <div class="full">
              <label for="detail-hypothesis-input" data-i18n="detail_hypothesis">实验假设</label>
              <textarea id="detail-hypothesis-input"></textarea>
            </div>
            <div>
              <label for="status-select" data-i18n="status_label">状态</label>
              <select id="status-select">
                <option value="draft" data-i18n="status_draft">草稿</option>
                <option value="running" data-i18n="status_running">运行中</option>
                <option value="paused" data-i18n="status_paused">暂停</option>
                <option value="completed" data-i18n="status_completed">完成</option>
                <option value="archived" data-i18n="status_archived">归档</option>
              </select>
            </div>
            <div>
              <label data-i18n="updated_at">更新时间</label>
              <div id="detail-updated" class="mono"></div>
            </div>
            <div class="full">
              <label data-i18n="traffic_display">流量分配</label>
              <textarea id="detail-traffic"></textarea>
            </div>
            <div class="full">
              <label for="result-json" data-i18n="result_label">结果 JSON</label>
              <textarea id="result-json">{}</textarea>
            </div>
          </div>
          <div class="actions">
            <button onclick="saveExperimentMeta()" data-i18n="save_meta">保存实验信息</button>
            <button onclick="saveStatusAndResult()" data-i18n="save_status">保存状态与结果</button>
            <button onclick="deleteExperiment()" data-i18n="delete_experiment">删除实验</button>
          </div>

          <div class="section-title" data-i18n="variants_title">Variants</div>
          <div id="variant-list"></div>
          <div class="grid">
            <div>
              <label for="variant-key" data-i18n="variant_key_label">Variant Key</label>
              <input id="variant-key" placeholder="A" />
            </div>
            <div class="full">
              <label for="variant-content" data-i18n="variant_content_label">Variant Content</label>
              <textarea id="variant-content"></textarea>
            </div>
          </div>
          <div class="actions">
            <button onclick="saveVariant()" data-i18n="save_variant">保存 Variant</button>
          </div>
        </div>
      </div>
    </div>
    <div id="msg" class="msg"></div>
  </div>

<script>
const I18N = {
  zh: {
    title: '实验中心',
    back: '返回聊天',
    kb_nav: 'Knowledge Base 管理',
    group_nav: '组管理',
    admin_nav: '用户管理',
    logout: '退出',
    exp_list: '实验列表',
    create_exp: '创建实验',
    title_label: '标题',
    hypothesis_label: '假设',
    conversation_label: '关联会话（可选）',
    traffic_label: '流量分配 JSON（可选）',
    create_btn: '创建',
    detail_title: '实验详情',
    detail_name: '实验名称',
    detail_hypothesis: '实验假设',
    status_label: '状态',
    status_draft: '草稿',
    status_running: '运行中',
    status_paused: '暂停',
    status_completed: '完成',
    status_archived: '归档',
    updated_at: '更新时间',
    traffic_display: '流量分配',
    result_label: '结果 JSON',
    save_meta: '保存实验信息',
    save_status: '保存状态与结果',
    delete_experiment: '删除实验',
    variants_title: '实验 Variants',
    variant_key_label: 'Variant Key',
    variant_content_label: 'Variant 内容',
    save_variant: '保存 Variant',
    request_failed: '请求失败',
    no_experiments: '还没有实验，请先创建。',
    no_selected: '请选择一个实验查看详情。',
    no_variants: '暂无 variants',
    conv_none: '不关联会话',
    create_ok: '实验创建成功',
    update_ok: '实验已更新',
    variant_ok: 'Variant 已保存',
    delete_ok: '实验已删除',
    delete_confirm: '确定删除这个实验吗？',
    invalid_json: 'JSON 格式错误',
    required_title: '标题不能为空',
    required_hypothesis: '假设不能为空',
    required_variant_key: 'Variant key 不能为空',
    required_variant_content: 'Variant 内容不能为空'
  },
  en: {
    title: 'Experiments',
    back: 'Back to Chat',
    kb_nav: 'Knowledge Base Management',
    group_nav: 'Group Management',
    admin_nav: 'User Management',
    logout: 'Log Out',
    exp_list: 'Experiments',
    create_exp: 'Create Experiment',
    title_label: 'Title',
    hypothesis_label: 'Hypothesis',
    conversation_label: 'Conversation (optional)',
    traffic_label: 'Traffic Allocation JSON (optional)',
    create_btn: 'Create',
    detail_title: 'Experiment Detail',
    detail_name: 'Title',
    detail_hypothesis: 'Hypothesis',
    status_label: 'Status',
    status_draft: 'Draft',
    status_running: 'Running',
    status_paused: 'Paused',
    status_completed: 'Completed',
    status_archived: 'Archived',
    updated_at: 'Updated At',
    traffic_display: 'Traffic Allocation',
    result_label: 'Result JSON',
    save_meta: 'Save Experiment Meta',
    save_status: 'Save Status & Result',
    delete_experiment: 'Delete Experiment',
    variants_title: 'Variants',
    variant_key_label: 'Variant Key',
    variant_content_label: 'Variant Content',
    save_variant: 'Save Variant',
    request_failed: 'Request failed',
    no_experiments: 'No experiments yet. Create one first.',
    no_selected: 'Select an experiment to view details.',
    no_variants: 'No variants yet',
    conv_none: 'No linked conversation',
    create_ok: 'Experiment created',
    update_ok: 'Experiment updated',
    variant_ok: 'Variant saved',
    delete_ok: 'Experiment deleted',
    delete_confirm: 'Delete this experiment?',
    invalid_json: 'Invalid JSON',
    required_title: 'Title is required',
    required_hypothesis: 'Hypothesis is required',
    required_variant_key: 'Variant key is required',
    required_variant_content: 'Variant content is required'
  }
};

let currentLang = localStorage.getItem('nova_lang') || 'zh';
let csrfToken = '';
let me = null;
let conversations = [];
let experiments = [];
let activeExperiment = null;

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || key;
}

function setMsg(text, isWarn=false) {
  const el = document.getElementById('msg');
  el.textContent = text || '';
  el.classList.toggle('warn', !!isWarn);
}

function statusLabel(status) {
  return t(`status_${status}`) || status;
}

function fmt(ts) {
  try { return new Date(ts).toLocaleString(); } catch (_) { return ts || ''; }
}

function parseJsonObject(text, fallback={}) {
  const raw = (text || '').trim();
  if (!raw) return fallback;
  const value = JSON.parse(raw);
  if (!value || Array.isArray(value) || typeof value !== 'object') {
    throw new Error(t('invalid_json'));
  }
  return value;
}

function pretty(value) {
  try { return JSON.stringify(value || {}, null, 2); } catch (_) { return '{}'; }
}

function setLang(lang) {
  currentLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('nova_lang', currentLang);
  applyI18n();
  renderConversationSelect();
  renderExperiments();
  renderExperimentDetail();
}

function applyI18n() {
  document.title = t('title');
  document.documentElement.lang = currentLang === 'en' ? 'en' : 'zh-CN';
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
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
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const err = new Error(data.detail || t('request_failed'));
    err.status = res.status;
    throw err;
  }
  return data;
}

async function loadCsrfToken() {
  const res = await fetch('/api/csrf');
  if (!res.ok) {
    let data = {};
    try { data = await res.json(); } catch (_) {}
    const err = new Error(data.detail || 'csrf');
    err.status = res.status;
    throw err;
  }
  const data = await res.json();
  csrfToken = data.csrf_token || '';
}

function isAuthError(err) {
  const status = err && typeof err === 'object' ? err.status : null;
  return status === 401;
}

function renderConversationSelect() {
  const select = document.getElementById('create-conversation');
  const previous = select.value;
  select.innerHTML = '';
  const none = document.createElement('option');
  none.value = '';
  none.textContent = t('conv_none');
  select.appendChild(none);

  const ownConversations = conversations.filter((c) => me && c.user_id === me.id);
  for (const c of ownConversations) {
    const option = document.createElement('option');
    option.value = String(c.id);
    option.textContent = c.title;
    select.appendChild(option);
  }
  if ([...select.options].some((opt) => opt.value === previous)) {
    select.value = previous;
  }
}

function renderExperiments() {
  const box = document.getElementById('exp-list');
  box.innerHTML = '';
  if (!experiments.length) {
    box.innerHTML = `<div class="empty">${t('no_experiments')}</div>`;
    return;
  }
  for (const exp of experiments) {
    const div = document.createElement('div');
    div.className = 'item' + (activeExperiment && exp.id === activeExperiment.id ? ' active' : '');
    div.onclick = () => openExperiment(exp.id);
    div.innerHTML = `
      <div class="name">${exp.title}</div>
      <div class="meta">${statusLabel(exp.status)} · ${fmt(exp.updated_at)}</div>
    `;
    box.appendChild(div);
  }
}

function renderVariants(variants) {
  const box = document.getElementById('variant-list');
  box.innerHTML = '';
  if (!variants || !variants.length) {
    box.innerHTML = `<div class="empty">${t('no_variants')}</div>`;
    return;
  }
  for (const variant of variants) {
    const card = document.createElement('div');
    card.className = 'variant-card';
    card.innerHTML = `
      <div class="key">${variant.variant_key}</div>
      <div class="mono">${(variant.content || '').replace(/</g, '&lt;')}</div>
    `;
    box.appendChild(card);
  }
}

function renderExperimentDetail() {
  const empty = document.getElementById('exp-detail-empty');
  const panel = document.getElementById('exp-detail-panel');
  if (!activeExperiment) {
    empty.textContent = t('no_selected');
    empty.classList.remove('hidden');
    panel.classList.add('hidden');
    return;
  }
  empty.classList.add('hidden');
  panel.classList.remove('hidden');
  document.getElementById('detail-name-input').value = activeExperiment.title || '';
  document.getElementById('detail-hypothesis-input').value = activeExperiment.hypothesis || '';
  document.getElementById('detail-updated').textContent = fmt(activeExperiment.updated_at);
  document.getElementById('detail-traffic').value = pretty(activeExperiment.traffic_allocation || {});
  document.getElementById('status-select').value = activeExperiment.status || 'draft';
  document.getElementById('result-json').value = pretty(activeExperiment.result || {});
  renderVariants(activeExperiment.variants || []);
}

async function refreshExperiments() {
  experiments = await api('/api/experiments');
  renderExperiments();
  if (!activeExperiment && experiments.length) {
    await openExperiment(experiments[0].id);
  }
}

async function createExperiment() {
  const title = document.getElementById('create-title').value.trim();
  const hypothesis = document.getElementById('create-hypothesis').value.trim();
  const conversationRaw = document.getElementById('create-conversation').value;
  if (!title) {
    setMsg(t('required_title'), true);
    return;
  }
  if (!hypothesis) {
    setMsg(t('required_hypothesis'), true);
    return;
  }
  try {
    const payload = {
      title,
      hypothesis,
      conversation_id: conversationRaw ? Number(conversationRaw) : null,
      traffic_allocation: parseJsonObject(document.getElementById('create-traffic').value, {}),
    };
    const created = await api('/api/experiments', {
      method:'POST',
      body: JSON.stringify(payload),
    });
    setMsg(t('create_ok'));
    document.getElementById('create-title').value = '';
    document.getElementById('create-hypothesis').value = '';
    await refreshExperiments();
    if (created && created.id) {
      await openExperiment(created.id);
    }
  } catch (e) {
    setMsg(`${t('request_failed')}: ${e.message}`, true);
  }
}

async function openExperiment(experimentId) {
  try {
    activeExperiment = await api(`/api/experiments/${experimentId}`);
    renderExperiments();
    renderExperimentDetail();
  } catch (e) {
    setMsg(`${t('request_failed')}: ${e.message}`, true);
  }
}

async function saveExperimentMeta() {
  if (!activeExperiment) return;
  const title = document.getElementById('detail-name-input').value.trim();
  const hypothesis = document.getElementById('detail-hypothesis-input').value.trim();
  if (!title) {
    setMsg(t('required_title'), true);
    return;
  }
  if (!hypothesis) {
    setMsg(t('required_hypothesis'), true);
    return;
  }
  try {
    await api(`/api/experiments/${activeExperiment.id}`, {
      method:'PATCH',
      body: JSON.stringify({
        title,
        hypothesis,
        traffic_allocation: parseJsonObject(document.getElementById('detail-traffic').value, {}),
      }),
    });
    setMsg(t('update_ok'));
    await openExperiment(activeExperiment.id);
    experiments = await api('/api/experiments');
    renderExperiments();
  } catch (e) {
    setMsg(`${t('request_failed')}: ${e.message}`, true);
  }
}

async function saveStatusAndResult() {
  if (!activeExperiment) return;
  try {
    const payload = {
      status: document.getElementById('status-select').value,
      result: parseJsonObject(document.getElementById('result-json').value, {}),
    };
    await api(`/api/experiments/${activeExperiment.id}/status`, {
      method:'PATCH',
      body: JSON.stringify(payload),
    });
    setMsg(t('update_ok'));
    await openExperiment(activeExperiment.id);
    experiments = await api('/api/experiments');
    renderExperiments();
  } catch (e) {
    setMsg(`${t('request_failed')}: ${e.message}`, true);
  }
}

async function deleteExperiment() {
  if (!activeExperiment) return;
  if (!confirm(t('delete_confirm'))) return;
  try {
    const deletingId = activeExperiment.id;
    await api(`/api/experiments/${deletingId}`, {method:'DELETE'});
    setMsg(t('delete_ok'));
    activeExperiment = null;
    await refreshExperiments();
    if (!experiments.length) {
      renderExperimentDetail();
    }
  } catch (e) {
    setMsg(`${t('request_failed')}: ${e.message}`, true);
  }
}

async function saveVariant() {
  if (!activeExperiment) return;
  const variant_key = document.getElementById('variant-key').value.trim();
  const content = document.getElementById('variant-content').value.trim();
  if (!variant_key) {
    setMsg(t('required_variant_key'), true);
    return;
  }
  if (!content) {
    setMsg(t('required_variant_content'), true);
    return;
  }
  try {
    await api(`/api/experiments/${activeExperiment.id}/variants`, {
      method:'POST',
      body: JSON.stringify({variant_key, content}),
    });
    setMsg(t('variant_ok'));
    document.getElementById('variant-content').value = '';
    await openExperiment(activeExperiment.id);
  } catch (e) {
    setMsg(`${t('request_failed')}: ${e.message}`, true);
  }
}

async function logout() {
  await api('/logout', {method:'POST'});
  location.href = '/';
}

function gotoApp() { location.href = '/app'; }
function gotoKB() { location.href = '/kb'; }
function gotoGroups() { location.href = '/groups'; }
function gotoAdmin() { location.href = '/admin'; }

(async function init() {
  applyI18n();
  try {
    await loadCsrfToken();
    me = await api('/api/me');
    if (me && me.is_admin) {
      document.getElementById('admin-btn').style.display = 'inline-block';
    }
    try {
      conversations = await api('/api/conversations');
    } catch (e) {
      if (isAuthError(e)) throw e;
      conversations = [];
      setMsg(`${t('request_failed')}: ${e.message}`, true);
    }
    renderConversationSelect();
    try {
      await refreshExperiments();
      renderExperimentDetail();
    } catch (e) {
      if (isAuthError(e)) throw e;
      experiments = [];
      activeExperiment = null;
      renderExperiments();
      renderExperimentDetail();
      setMsg(`${t('request_failed')}: ${e.message}`, true);
    }
  } catch (e) {
    if (isAuthError(e)) {
      location.href = '/';
      return;
    }
    setMsg(`${t('request_failed')}: ${e.message}`, true);
  }
})();
</script>
</body>
</html>
"""
