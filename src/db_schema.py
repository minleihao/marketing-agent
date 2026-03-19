from __future__ import annotations

import json
from typing import Any

from db_backend import (
    DATA_DIR,
    DB_BACKEND,
    UPLOAD_DIR,
    _insert_and_get_id,
    _pull_db_from_s3,
    db_conn,
    hash_password,
    now_utc,
    verify_password,
)


GENERAL_GROUP_NAME = "General Group"
GENERAL_GROUP_TYPE = "company"
DEFAULT_SHARED_KBS = (
    {
        "kb_key": "default_brand_guidelines",
        "kb_name": "Default Brand Guidelines",
        "brand_voice": "Clear, credible, customer-centric, and benefit-led.",
        "positioning": {
            "category": "Marketing enablement",
            "promise": "Turn rough ideas into professional marketing content without losing clarity or trust.",
        },
        "glossary": [
            {"preferred": "customer problem", "avoid": "pain point overload"},
            {"preferred": "proof point", "avoid": "empty claim"},
            {"preferred": "call to action", "avoid": "hard sell"},
        ],
        "forbidden_words": ["guaranteed", "perfect", "instant", "no-risk"],
        "required_terms": ["audience", "value proposition", "call to action"],
        "claims_policy": {
            "require_source": True,
            "avoid_unverified_superlatives": True,
            "encourage_risk_disclosure": True,
        },
        "examples": [
            {
                "name": "Headline pattern",
                "content": "Lead with the audience and business outcome before naming the feature.",
            }
        ],
        "notes": "System default shared Knowledge Base managed by admin for all users in General Group.",
    },
    {
        "kb_key": "default_campaign_playbook",
        "kb_name": "Default Campaign Playbook",
        "brand_voice": "Structured, actionable, and performance-aware.",
        "positioning": {
            "category": "Campaign planning",
            "promise": "Help teams move from brief to channel-ready assets with clear execution logic.",
        },
        "glossary": [
            {"preferred": "primary KPI", "avoid": "vanity metric"},
            {"preferred": "test hypothesis", "avoid": "random variation"},
            {"preferred": "message pillar", "avoid": "miscellaneous point"},
        ],
        "forbidden_words": ["viral", "guaranteed ROI", "sure win"],
        "required_terms": ["objective", "audience", "channel", "success metric"],
        "claims_policy": {
            "require_source": True,
            "state_assumptions_explicitly": True,
            "flag_compliance_sensitive_copy": True,
        },
        "examples": [
            {
                "name": "Execution checklist",
                "content": "Every deliverable should include audience, offer, CTA, KPI, and risk note when relevant.",
            }
        ],
        "notes": "System default shared Knowledge Base managed by admin for all users in General Group.",
    },
)

DEFAULT_SHARED_CONVERSATIONS = (
    {
        "title": "Sample Marketing Chat",
        "task_mode": "marketing",
        "thinking_depth": "medium",
        "kb_key": "default_campaign_playbook",
        "kb_version": 1,
        "messages": (
            (
                "user",
                (
                    "Create a launch-ready marketing package for a B2B analytics platform aimed at operations leaders. "
                    "Include email and LinkedIn guidance, keep the tone credible, and avoid hype."
                ),
            ),
            (
                "assistant",
                (
                    "## Launch Recommendation\n\n"
                    "**Primary angle:** Position the platform as the fastest way for operations teams to turn messy reporting into weekly decision-making discipline.\n\n"
                    "## Channel Plan\n\n"
                    "| Channel | Goal | Message angle | CTA |\n"
                    "| --- | --- | --- | --- |\n"
                    "| Email | Drive demo intent | Replace fragmented dashboards with one operational rhythm | Book a 20-minute walkthrough |\n"
                    "| LinkedIn | Build credibility | Show how operations teams surface delays earlier with shared visibility | Read the launch overview |\n\n"
                    "## Marketing Content\n\n"
                    "**Email subject line options**\n"
                    "- A simpler weekly operating review for growing teams\n"
                    "- Stop chasing updates across five dashboards\n\n"
                    "**LinkedIn draft**\n"
                    "Operations teams do not need more dashboards. They need a shared operating rhythm.\n\n"
                    "Our analytics platform helps teams turn fragmented updates into one weekly review flow so risks, bottlenecks, and decisions are visible earlier.\n\n"
                    "If your team is scaling and reporting still feels manual, this is the moment to simplify the system behind it.\n\n"
                    "**CTA:** Book a walkthrough or review the launch overview.\n\n"
                    "## Risk Note\n\n"
                    "- Avoid unverified ROI claims.\n"
                    "- Add one customer proof point before publishing."
                ),
            ),
        ),
    },
    {
        "title": "Sample General Chat",
        "task_mode": "chat",
        "thinking_depth": "low",
        "kb_key": "default_brand_guidelines",
        "kb_version": 1,
        "messages": (
            (
                "user",
                "What is a practical agenda for a weekly marketing check-in that keeps the team aligned without wasting time?",
            ),
            (
                "assistant",
                (
                    "A good 30-minute weekly marketing check-in usually works best with five blocks:\n\n"
                    "1. **Performance snapshot**: Review the two or three metrics that matter most this week.\n"
                    "2. **Campaign progress**: Confirm what shipped, what slipped, and why.\n"
                    "3. **Risks and blockers**: Surface dependencies early instead of leaving them for side conversations.\n"
                    "4. **Decisions needed**: Spend real time on tradeoffs that need leadership input.\n"
                    "5. **Next actions**: End with owners, deadlines, and one clear priority per workstream.\n\n"
                    "If the team keeps drifting into status updates, switch to a written pre-read and use the meeting only for decisions and blockers."
                ),
            ),
        ),
    },
)


def _escape_sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _seed_admin_user(
    conn: Any,
    *,
    default_admin_user: str,
    default_admin_password: str,
    enforce_default_admin_password_change: bool,
) -> None:
    admin_exists = conn.execute(
        "SELECT id, password_salt, password_hash FROM users WHERE username = ?",
        (default_admin_user,),
    ).fetchone()
    if not admin_exists:
        salt, pwd_hash = hash_password(default_admin_password)
        conn.execute(
            """
            INSERT INTO users (username, password_salt, password_hash, is_admin, is_active, must_change_password, created_at)
            VALUES (?, ?, ?, 1, 1, ?, ?)
            """,
            (
                default_admin_user,
                salt,
                pwd_hash,
                1 if (enforce_default_admin_password_change and default_admin_password == "admin123456") else 0,
                now_utc().isoformat(),
            ),
        )
    elif verify_password(default_admin_password, admin_exists["password_salt"], admin_exists["password_hash"]):
        conn.execute(
            "UPDATE users SET must_change_password = ? WHERE id = ?",
            (1 if enforce_default_admin_password_change else 0, admin_exists["id"]),
        )
    elif not enforce_default_admin_password_change:
        conn.execute(
            "UPDATE users SET must_change_password = 0 WHERE id = ?",
            (admin_exists["id"],),
        )


def _lookup_user_id(conn: Any, username: str) -> int:
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        raise RuntimeError(f"User not found during initialization: {username}")
    return int(row["id"])


def _ensure_general_group(conn: Any, admin_user_id: int) -> int:
    now = now_utc().isoformat()
    row = conn.execute(
        "SELECT id FROM groups WHERE name = ? AND group_type = ?",
        (GENERAL_GROUP_NAME, GENERAL_GROUP_TYPE),
    ).fetchone()
    if row:
        group_id = int(row["id"])
        conn.execute("UPDATE groups SET created_by = ? WHERE id = ?", (admin_user_id, group_id))
    else:
        group_id = _insert_and_get_id(
            conn,
            "INSERT INTO groups (name, group_type, created_by, created_at) VALUES (?, ?, ?, ?)",
            (GENERAL_GROUP_NAME, GENERAL_GROUP_TYPE, admin_user_id, now),
        )

    membership = conn.execute(
        "SELECT role, status FROM group_memberships WHERE group_id = ? AND user_id = ?",
        (group_id, admin_user_id),
    ).fetchone()
    if membership:
        conn.execute(
            """
            UPDATE group_memberships
            SET role = 'admin', status = 'approved', requested_by = ?, approved_at = ?
            WHERE group_id = ? AND user_id = ?
            """,
            (admin_user_id, now, group_id, admin_user_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO group_memberships (group_id, user_id, role, status, requested_by, created_at, approved_at)
            VALUES (?, ?, 'admin', 'approved', ?, ?, ?)
            """,
            (group_id, admin_user_id, admin_user_id, now, now),
        )
    return group_id


def _ensure_general_group_memberships(conn: Any, group_id: int, admin_user_id: int) -> None:
    now = now_utc().isoformat()
    rows = conn.execute("SELECT id FROM users").fetchall()
    for row in rows:
        user_id = int(row["id"])
        membership = conn.execute(
            "SELECT status FROM group_memberships WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        ).fetchone()
        if membership:
            continue
        role = "admin" if user_id == admin_user_id else "member"
        conn.execute(
            """
            INSERT INTO group_memberships (group_id, user_id, role, status, requested_by, created_at, approved_at)
            VALUES (?, ?, ?, 'approved', ?, ?, ?)
            """,
            (group_id, user_id, role, admin_user_id, now, now),
        )


def _ensure_default_shared_kbs(conn: Any, admin_user_id: int, group_id: int) -> None:
    now = now_utc().isoformat()
    for item in DEFAULT_SHARED_KBS:
        existing = conn.execute(
            """
            SELECT id, owner_id, visibility, share_group_id
            FROM brand_kb_versions
            WHERE kb_key = ?
            ORDER BY version ASC
            LIMIT 1
            """,
            (item["kb_key"],),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE brand_kb_versions
                SET owner_id = ?, visibility = 'company', share_group_id = ?
                WHERE id = ?
                """,
                (admin_user_id, group_id, existing["id"]),
            )
            continue

        conn.execute(
            """
            INSERT INTO brand_kb_versions (
                kb_key, kb_name, version, owner_id, visibility, share_group_id, brand_voice,
                positioning_json, glossary_json, forbidden_words_json, required_terms_json,
                claims_policy_json, examples_json, notes, created_at
            )
            VALUES (?, ?, 1, ?, 'company', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["kb_key"],
                item["kb_name"],
                admin_user_id,
                group_id,
                item["brand_voice"],
                json.dumps(item["positioning"], ensure_ascii=False),
                json.dumps(item["glossary"], ensure_ascii=False),
                json.dumps(item["forbidden_words"], ensure_ascii=False),
                json.dumps(item["required_terms"], ensure_ascii=False),
                json.dumps(item["claims_policy"], ensure_ascii=False),
                json.dumps(item["examples"], ensure_ascii=False),
                item["notes"],
                now,
            ),
        )


def _ensure_default_shared_conversations(
    conn: Any,
    admin_user_id: int,
    group_id: int,
    *,
    default_model_id: str,
    default_thinking_depth: str,
) -> None:
    for item in DEFAULT_SHARED_CONVERSATIONS:
        existing = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE user_id = ? AND title = ? AND share_group_id = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (admin_user_id, item["title"], group_id),
        ).fetchone()
        if existing:
            continue

        created_at = now_utc().isoformat()
        conversation_id = _insert_and_get_id(
            conn,
            """
            INSERT INTO conversations (
                user_id, title, model_id, task_mode, thinking_depth, visibility, share_group_id,
                kb_key, kb_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'company', ?, ?, ?, ?, ?)
            """,
            (
                admin_user_id,
                item["title"],
                default_model_id,
                item["task_mode"],
                item.get("thinking_depth") or default_thinking_depth,
                group_id,
                item.get("kb_key"),
                item.get("kb_version"),
                created_at,
                created_at,
            ),
        )
        for role, content in item["messages"]:
            message_time = now_utc().isoformat()
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, message_time),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (message_time, conversation_id),
            )


def _create_common_indexes(conn: Any) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_conversation_id ON documents(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks_conversation_id ON document_chunks(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_username_time ON login_attempts(username, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_time ON login_attempts(ip_address, created_at)")


def _init_db_sqlite(conn: Any, *, default_model_id: str, default_thinking_depth: str) -> None:
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
            model_id TEXT NOT NULL DEFAULT 'us.anthropic.claude-sonnet-4-6',
            task_mode TEXT NOT NULL DEFAULT 'chat',
            thinking_depth TEXT NOT NULL DEFAULT 'low',
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

        """
    )

    conversation_cols = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    if "model_id" not in conversation_cols:
        conn.execute(f"ALTER TABLE conversations ADD COLUMN model_id TEXT NOT NULL DEFAULT '{default_model_id}'")
    if "kb_key" not in conversation_cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN kb_key TEXT")
    if "kb_version" not in conversation_cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN kb_version INTEGER")
    if "task_mode" not in conversation_cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN task_mode TEXT NOT NULL DEFAULT 'chat'")
    if "thinking_depth" not in conversation_cols:
        conn.execute(
            f"ALTER TABLE conversations ADD COLUMN thinking_depth TEXT NOT NULL DEFAULT '{default_thinking_depth}'"
        )
    if "visibility" not in conversation_cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'")
    if "share_group_id" not in conversation_cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN share_group_id INTEGER")

    user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "must_change_password" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")

    session_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "csrf_token" not in session_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN csrf_token TEXT")

    kb_cols = {row["name"] for row in conn.execute("PRAGMA table_info(brand_kb_versions)").fetchall()}
    if "owner_id" not in kb_cols:
        conn.execute("ALTER TABLE brand_kb_versions ADD COLUMN owner_id INTEGER")
        conn.execute("UPDATE brand_kb_versions SET owner_id = 1 WHERE owner_id IS NULL")
    if "visibility" not in kb_cols:
        conn.execute("ALTER TABLE brand_kb_versions ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'")
    if "share_group_id" not in kb_cols:
        conn.execute("ALTER TABLE brand_kb_versions ADD COLUMN share_group_id INTEGER")

    _create_common_indexes(conn)


def _init_db_postgres(conn: Any, *, default_model_id: str, default_thinking_depth: str) -> None:
    schema_statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            token TEXT UNIQUE NOT NULL,
            csrf_token TEXT,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,
            model_id TEXT NOT NULL DEFAULT 'us.anthropic.claude-sonnet-4-6',
            task_mode TEXT NOT NULL DEFAULT 'chat',
            thinking_depth TEXT NOT NULL DEFAULT 'low',
            visibility TEXT NOT NULL DEFAULT 'private',
            share_group_id BIGINT,
            kb_key TEXT,
            kb_version INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS messages (
            id BIGSERIAL PRIMARY KEY,
            conversation_id BIGINT NOT NULL REFERENCES conversations(id),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS documents (
            id BIGSERIAL PRIMARY KEY,
            conversation_id BIGINT NOT NULL REFERENCES conversations(id),
            filename TEXT NOT NULL,
            content_type TEXT,
            file_path TEXT NOT NULL,
            text_content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS document_chunks (
            id BIGSERIAL PRIMARY KEY,
            document_id BIGINT NOT NULL REFERENCES documents(id),
            conversation_id BIGINT NOT NULL REFERENCES conversations(id),
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS brand_kb_versions (
            id BIGSERIAL PRIMARY KEY,
            kb_key TEXT NOT NULL,
            kb_name TEXT NOT NULL,
            version INTEGER NOT NULL,
            owner_id BIGINT,
            visibility TEXT NOT NULL DEFAULT 'private',
            share_group_id BIGINT,
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
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS groups (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            group_type TEXT NOT NULL,
            created_by BIGINT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE(name, group_type)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS group_memberships (
            group_id BIGINT NOT NULL REFERENCES groups(id),
            user_id BIGINT NOT NULL REFERENCES users(id),
            role TEXT NOT NULL DEFAULT 'member',
            status TEXT NOT NULL DEFAULT 'pending',
            requested_by BIGINT REFERENCES users(id),
            created_at TEXT NOT NULL,
            approved_at TEXT,
            PRIMARY KEY(group_id, user_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS conversation_memories (
            conversation_id BIGINT PRIMARY KEY REFERENCES conversations(id),
            summary TEXT NOT NULL,
            source_message_id BIGINT,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS orchestrator_runs (
            id BIGSERIAL PRIMARY KEY,
            conversation_id BIGINT NOT NULL REFERENCES conversations(id),
            request_message_id BIGINT,
            response_message_id BIGINT,
            model_id TEXT NOT NULL,
            brief_json TEXT,
            plan_json TEXT,
            evaluation_json TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS login_attempts (
            id BIGSERIAL PRIMARY KEY,
            username TEXT,
            ip_address TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
    ]
    for stmt in schema_statements:
        conn.execute(stmt)

    escaped_model = _escape_sql_literal(default_model_id)
    escaped_depth = _escape_sql_literal(default_thinking_depth)
    conn.execute(f"ALTER TABLE conversations ADD COLUMN IF NOT EXISTS model_id TEXT NOT NULL DEFAULT '{escaped_model}'")
    conn.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kb_key TEXT")
    conn.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kb_version INTEGER")
    conn.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS task_mode TEXT NOT NULL DEFAULT 'chat'")
    conn.execute(
        f"ALTER TABLE conversations ADD COLUMN IF NOT EXISTS thinking_depth TEXT NOT NULL DEFAULT '{escaped_depth}'"
    )
    conn.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'")
    conn.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS share_group_id BIGINT")
    conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS csrf_token TEXT")
    conn.execute("ALTER TABLE brand_kb_versions ADD COLUMN IF NOT EXISTS owner_id BIGINT")
    conn.execute("ALTER TABLE brand_kb_versions ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'")
    conn.execute("ALTER TABLE brand_kb_versions ADD COLUMN IF NOT EXISTS share_group_id BIGINT")
    conn.execute("UPDATE brand_kb_versions SET owner_id = 1 WHERE owner_id IS NULL")

    _create_common_indexes(conn)


def init_db(
    *,
    default_model_id: str,
    default_thinking_depth: str,
    default_admin_user: str,
    default_admin_password: str,
    enforce_default_admin_password_change: bool,
) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if DB_BACKEND == "sqlite":
        _pull_db_from_s3(force=True)
    with db_conn() as conn:
        if DB_BACKEND == "postgres":
            _init_db_postgres(
                conn,
                default_model_id=default_model_id,
                default_thinking_depth=default_thinking_depth,
            )
        else:
            _init_db_sqlite(
                conn,
                default_model_id=default_model_id,
                default_thinking_depth=default_thinking_depth,
            )
        _seed_admin_user(
            conn,
            default_admin_user=default_admin_user,
            default_admin_password=default_admin_password,
            enforce_default_admin_password_change=enforce_default_admin_password_change,
        )
        admin_user_id = _lookup_user_id(conn, default_admin_user)
        general_group_id = _ensure_general_group(conn, admin_user_id)
        _ensure_general_group_memberships(conn, general_group_id, admin_user_id)
        _ensure_default_shared_kbs(conn, admin_user_id, general_group_id)
        _ensure_default_shared_conversations(
            conn,
            admin_user_id,
            general_group_id,
            default_model_id=default_model_id,
            default_thinking_depth=default_thinking_depth,
        )
