from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
if os.getenv("AWS_LAMBDA_FUNCTION_NAME") and not os.getenv("NOVARED_DATA_DIR"):
    DATA_DIR = Path("/tmp/novaRed")
else:
    DATA_DIR = Path(os.getenv("NOVARED_DATA_DIR", str(DEFAULT_DATA_DIR)))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "webapp.db"
DATABASE_URL = os.getenv("NOVARED_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://") :]
DB_BACKEND = "postgres" if DATABASE_URL.startswith("postgresql://") else "sqlite"
DB_S3_URI = os.getenv("NOVARED_DB_S3_URI", "").strip()
DB_S3_PULL_INTERVAL_SECONDS = max(0.0, float(os.getenv("NOVARED_DB_S3_PULL_INTERVAL_SECONDS", "1.5")))

_PSYCOPG_CONNECT: Any | None = None
_PSYCOPG_DICT_ROW: Any | None = None
DB_INTEGRITY_ERRORS: tuple[type[BaseException], ...] = (sqlite3.IntegrityError,)

if DB_BACKEND == "postgres":
    try:
        import psycopg
        from psycopg.errors import UniqueViolation
        from psycopg.rows import dict_row
    except Exception as exc:
        raise RuntimeError(
            "PostgreSQL backend requested but psycopg is not installed. "
            "Install it with `uv add psycopg[binary]`."
        ) from exc
    _PSYCOPG_CONNECT = psycopg.connect
    _PSYCOPG_DICT_ROW = dict_row
    DB_INTEGRITY_ERRORS = (sqlite3.IntegrityError, UniqueViolation)


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    text = (uri or "").strip()
    if not text:
        return "", ""
    if not text.startswith("s3://"):
        raise RuntimeError("NOVARED_DB_S3_URI must start with s3://")
    without_scheme = text[5:]
    parts = without_scheme.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RuntimeError("NOVARED_DB_S3_URI must be in format s3://bucket/key")
    return parts[0], parts[1]


DB_S3_BUCKET, DB_S3_KEY = _parse_s3_uri(DB_S3_URI)
_DB_S3_CLIENT: Any | None = None
_DB_S3_LOCK = threading.Lock()
_DB_LAST_ETAG: str | None = None
_DB_LAST_PULL_AT = 0.0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _db_s3_enabled() -> bool:
    return DB_BACKEND == "sqlite" and bool(DB_S3_BUCKET and DB_S3_KEY)


def _s3_client() -> Any:
    global _DB_S3_CLIENT
    if _DB_S3_CLIENT is None:
        import boto3

        _DB_S3_CLIENT = boto3.client("s3")
    return _DB_S3_CLIENT


def _pull_db_from_s3(*, force: bool = False) -> None:
    if not _db_s3_enabled():
        return
    global _DB_LAST_ETAG, _DB_LAST_PULL_AT
    now_ts = time.time()
    if not force and DB_PATH.exists() and now_ts - _DB_LAST_PULL_AT < DB_S3_PULL_INTERVAL_SECONDS:
        return
    with _DB_S3_LOCK:
        now_ts = time.time()
        if not force and DB_PATH.exists() and now_ts - _DB_LAST_PULL_AT < DB_S3_PULL_INTERVAL_SECONDS:
            return
        try:
            head = _s3_client().head_object(Bucket=DB_S3_BUCKET, Key=DB_S3_KEY)
        except Exception as exc:  # pragma: no cover - network/env dependent
            code = (
                getattr(exc, "response", {}).get("Error", {}).get("Code")
                if hasattr(exc, "response")
                else None
            )
            if code not in {"404", "NoSuchKey", "NotFound"}:
                print(f"[db-sync] failed to head s3 object: {exc}")
            _DB_LAST_PULL_AT = now_ts
            return
        remote_etag = str(head.get("ETag", "")).strip('"')
        if DB_PATH.exists() and remote_etag and remote_etag == _DB_LAST_ETAG:
            _DB_LAST_PULL_AT = now_ts
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = DB_PATH.with_suffix(".download")
        try:
            _s3_client().download_file(DB_S3_BUCKET, DB_S3_KEY, str(tmp_path))
            os.replace(tmp_path, DB_PATH)
            _DB_LAST_ETAG = remote_etag or _DB_LAST_ETAG
            _DB_LAST_PULL_AT = now_ts
        except Exception as exc:  # pragma: no cover - network/env dependent
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            print(f"[db-sync] failed to download s3 database: {exc}")


def _push_db_to_s3() -> None:
    if not _db_s3_enabled() or not DB_PATH.exists():
        return
    global _DB_LAST_ETAG, _DB_LAST_PULL_AT
    with _DB_S3_LOCK:
        try:
            with DB_PATH.open("rb") as f:
                response = _s3_client().put_object(Bucket=DB_S3_BUCKET, Key=DB_S3_KEY, Body=f)
            etag = str(response.get("ETag", "")).strip('"')
            if etag:
                _DB_LAST_ETAG = etag
            _DB_LAST_PULL_AT = time.time()
        except Exception as exc:  # pragma: no cover - network/env dependent
            print(f"[db-sync] failed to upload s3 database: {exc}")


def _translate_qmark_to_postgres(sql: str) -> str:
    if "?" not in sql:
        return sql
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double:
            out.append(ch)
            if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            i += 1
            continue
        if ch == "?" and not in_single and not in_double:
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


_WRITE_SQL_PREFIXES = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP", "TRUNCATE", "REPLACE")


def _is_write_statement(sql: str) -> bool:
    stripped = sql.lstrip()
    if not stripped:
        return False
    first = stripped.split(None, 1)[0].upper()
    return first in _WRITE_SQL_PREFIXES


class PostgresConnectionAdapter:
    def __init__(self, conn: Any):
        self._conn = conn
        self.total_changes = 0

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | None = None) -> Any:
        pg_sql = _translate_qmark_to_postgres(sql)
        bound = tuple(params) if params is not None else ()
        cur = self._conn.execute(pg_sql, bound)
        if _is_write_statement(pg_sql):
            self.total_changes += max(0, int(getattr(cur, "rowcount", 0) or 0))
        return cur

    def executemany(self, sql: str, seq_of_params: Any) -> Any:
        pg_sql = _translate_qmark_to_postgres(sql)
        rows = list(seq_of_params)
        if not rows:
            return None
        cur = self._conn.executemany(pg_sql, rows)
        if _is_write_statement(pg_sql):
            self.total_changes += len(rows)
        return cur

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _insert_and_get_id(conn: Any, sql: str, params: tuple[Any, ...] | list[Any] | None = None) -> int:
    bound = tuple(params) if params is not None else ()
    if DB_BACKEND == "postgres":
        clean_sql = sql.strip().rstrip(";")
        row = conn.execute(f"{clean_sql} RETURNING id", bound).fetchone()
        if not row:
            raise RuntimeError("Failed to fetch inserted id from PostgreSQL")
        return int(row["id"])
    cur = conn.execute(sql, bound)
    return int(cur.lastrowid)


@contextmanager
def db_conn() -> Iterator[Any]:
    if DB_BACKEND == "postgres":
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is required when DB_BACKEND=postgres")
        if _PSYCOPG_CONNECT is None or _PSYCOPG_DICT_ROW is None:
            raise RuntimeError("psycopg driver is not initialized")
        raw_conn = _PSYCOPG_CONNECT(DATABASE_URL, row_factory=_PSYCOPG_DICT_ROW)
        conn: Any = PostgresConnectionAdapter(raw_conn)
    else:
        _pull_db_from_s3()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        has_writes = conn.total_changes > 0
        conn.close()
        if has_writes and DB_BACKEND == "sqlite":
            _push_db_to_s3()


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, password_hash: str) -> bool:
    _salt, candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, password_hash)

