#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

try:
    import psycopg
    from psycopg import sql
except Exception as exc:  # pragma: no cover - environment dependent
    raise SystemExit("psycopg is required. Install with: uv add psycopg[binary]") from exc


TABLE_ORDER = [
    "users",
    "sessions",
    "groups",
    "group_memberships",
    "conversations",
    "messages",
    "documents",
    "document_chunks",
    "brand_kb_versions",
    "conversation_memories",
    "orchestrator_runs",
    "login_attempts",
]

TABLES_WITH_ID_SEQUENCE = [
    "users",
    "sessions",
    "conversations",
    "messages",
    "documents",
    "document_chunks",
    "brand_kb_versions",
    "groups",
    "orchestrator_runs",
    "login_attempts",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate novaRed data from SQLite to PostgreSQL.")
    parser.add_argument(
        "--sqlite-path",
        default="data/webapp.db",
        help="Path to source SQLite file (default: data/webapp.db)",
    )
    parser.add_argument(
        "--postgres-url",
        default=os.getenv("NOVARED_DATABASE_URL", os.getenv("DATABASE_URL", "")),
        help="Target PostgreSQL URL (defaults to NOVARED_DATABASE_URL / DATABASE_URL)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for copying rows (default: 1000)",
    )
    parser.add_argument(
        "--skip-init-schema",
        action="store_true",
        help="Skip calling webapp.init_db() before migration",
    )
    return parser.parse_args()


def _load_webapp_for_schema_init(postgres_url: str) -> None:
    root = Path(__file__).resolve().parents[1]
    src_dir = root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    os.environ["NOVARED_DATABASE_URL"] = postgres_url
    import webapp  # noqa: WPS433

    webapp.init_db()


def _sqlite_table_exists(sqlite_conn: sqlite3.Connection, table_name: str) -> bool:
    row = sqlite_conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def _sqlite_table_columns(sqlite_conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = sqlite_conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return [str(r["name"]) for r in rows]


def _truncate_target_tables(pg_conn: psycopg.Connection) -> None:
    table_identifiers = sql.SQL(", ").join(sql.Identifier(name) for name in reversed(TABLE_ORDER))
    stmt = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(table_identifiers)
    with pg_conn.cursor() as cur:
        cur.execute(stmt)


def _copy_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: psycopg.Connection,
    table_name: str,
    *,
    batch_size: int,
) -> int:
    if not _sqlite_table_exists(sqlite_conn, table_name):
        return 0
    columns = _sqlite_table_columns(sqlite_conn, table_name)
    if not columns:
        return 0

    column_clause = ", ".join(f'"{c}"' for c in columns)
    sqlite_query = f'SELECT {column_clause} FROM "{table_name}"'
    sqlite_cur = sqlite_conn.execute(sqlite_query)

    insert_stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table_name),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )

    copied = 0
    with pg_conn.cursor() as pg_cur:
        while True:
            batch = sqlite_cur.fetchmany(batch_size)
            if not batch:
                break
            rows = [tuple(row[c] for c in columns) for row in batch]
            pg_cur.executemany(insert_stmt, rows)
            copied += len(rows)
    return copied


def _sync_sequences(pg_conn: psycopg.Connection) -> None:
    with pg_conn.cursor() as cur:
        for table_name in TABLES_WITH_ID_SEQUENCE:
            stmt = sql.SQL(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                "COALESCE((SELECT MAX(id) FROM {table}), 1), "
                "(SELECT MAX(id) IS NOT NULL FROM {table}))"
            ).format(table=sql.Identifier(table_name))
            cur.execute(stmt, (table_name,))


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    postgres_url = (args.postgres_url or "").strip()

    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")
    if not postgres_url:
        raise SystemExit("PostgreSQL URL is required. Pass --postgres-url or set NOVARED_DATABASE_URL.")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")

    if not args.skip_init_schema:
        print("[1/4] Initializing PostgreSQL schema via webapp.init_db() ...")
        _load_webapp_for_schema_init(postgres_url)

    print(f"[2/4] Reading source SQLite: {sqlite_path}")
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    print("[3/4] Copying data into PostgreSQL ...")
    with psycopg.connect(postgres_url) as pg_conn:
        try:
            _truncate_target_tables(pg_conn)
            for table_name in TABLE_ORDER:
                copied = _copy_table(sqlite_conn, pg_conn, table_name, batch_size=args.batch_size)
                print(f"  - {table_name}: {copied} rows")
            _sync_sequences(pg_conn)
            pg_conn.commit()
        except Exception:
            pg_conn.rollback()
            raise
        finally:
            sqlite_conn.close()

    print("[4/4] Migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
