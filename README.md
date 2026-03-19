# Marketing Copilot

Marketing Copilot is a FastAPI web application for multi-user marketing collaboration with:
- authenticated chat and marketing task conversations
- conversation history and per-conversation model settings
- shared, versioned Knowledge Base management
- group-based access control (`private`, `task`, `company`)
- document upload and retrieval context support
- default shared system resources for the `General Group`
- English-only UI

## Tech Stack
- Backend: FastAPI
- Runtime orchestration: `src/main.py` (`invoke`, `invoke_stream`)
- Database: SQLite (default) or PostgreSQL
- Frontend delivery: HTML/CSS/JS templates served by FastAPI

## Current Structure
- `src/webapp.py`: main API runtime and route handlers
- `src/db_backend.py`: database backend selection, connection helpers, password helpers, SQL compatibility helpers
- `src/db_schema.py`: schema initialization and migration-safe bootstrapping
- `src/webapp_schemas.py`: request/response Pydantic payload models
- `src/webapp_templates.py`: embedded HTML templates used by page routes
- `scripts/migrate_sqlite_to_postgres.py`: one-time data migration script

## Run Locally
```bash
uv sync
uv run python main.py
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## User Guide

For a non-technical end-user guide for the marketing team, see [MARKETING_TEAM_USER_GUIDE.md](MARKETING_TEAM_USER_GUIDE.md).

## Environment Variables
- `NOVARED_DATABASE_URL` or `DATABASE_URL`: PostgreSQL DSN (enables PostgreSQL backend)
- `NOVARED_DATA_DIR`: local data directory (default: `data/`)
- `NOVARED_ALLOWED_MODELS`: comma-separated model whitelist override
- `NOVARED_ADMIN_USER`: bootstrap admin username (default: `admin`)
- `NOVARED_ADMIN_PASSWORD`: bootstrap admin password (default: `admin123456`)
- `NOVARED_COOKIE_SECURE`: set `1` in HTTPS deployment

## Database Backends
Default backend is SQLite.

To switch to PostgreSQL:
```bash
export NOVARED_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/marketing_copilot"
uv run python main.py
```

## Migrate SQLite Data to PostgreSQL
```bash
export NOVARED_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/marketing_copilot"
uv run python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-path data/webapp.db \
  --postgres-url "$NOVARED_DATABASE_URL"
```

Then restart the app with PostgreSQL enabled.

## Test
```bash
uv run pytest -q test/test_main.py test/test_webapp.py
```

## Notes
- Group and visibility permissions are enforced server-side for conversations and Knowledge Base entries.
- Shared content is separated from user-owned content in UI and API responses.
- Every registered user is auto-added to `General Group`.
- `admin` owns the protected `General Group`, two default shared Knowledge Base entries, and seeded sample shared conversations.
- Keep schema changes backward compatible; existing instances may already have production data.
