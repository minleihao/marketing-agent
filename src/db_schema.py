from __future__ import annotations

from typing import Any

from db_backend import (
    DATA_DIR,
    DB_BACKEND,
    UPLOAD_DIR,
    _pull_db_from_s3,
    db_conn,
    hash_password,
    now_utc,
    verify_password,
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
        """
        CREATE TABLE IF NOT EXISTS experiments (
            id BIGSERIAL PRIMARY KEY,
            owner_user_id BIGINT NOT NULL REFERENCES users(id),
            conversation_id BIGINT REFERENCES conversations(id),
            title TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            traffic_allocation_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS experiment_variants (
            id BIGSERIAL PRIMARY KEY,
            experiment_id BIGINT NOT NULL REFERENCES experiments(id),
            variant_key TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(experiment_id, variant_key)
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

