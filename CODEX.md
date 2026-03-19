# Codex Engineering Notes: Marketing Copilot

## Product Understanding
Marketing Copilot is a multi-user marketing assistant platform with two primary work modes:
- `chat`: general collaborative dialogue
- `marketing`: structured campaign generation with orchestrated stages

The product includes:
- account registration/login
- conversation lifecycle (create, rename, delete, export)
- group collaboration (`task` and `company` groups)
- visibility model (`private`, `task`, `company`)
- shared Knowledge Base with versioning
- protected `General Group` shared by all registered users
- admin-owned default shared Knowledge Base entries and sample shared conversations
- English-only UI

## Runtime Map
- Main web backend entry: `/Users/minleihao/marketing-agent/novaRed/src/webapp.py`
- Agent invocation: `/Users/minleihao/marketing-agent/novaRed/src/main.py`
- DB backend abstraction: `/Users/minleihao/marketing-agent/novaRed/src/db_backend.py`
- DB schema init and migration-safe setup: `/Users/minleihao/marketing-agent/novaRed/src/db_schema.py`
- API payload schemas: `/Users/minleihao/marketing-agent/novaRed/src/webapp_schemas.py`
- UI template constants: `/Users/minleihao/marketing-agent/novaRed/src/webapp_templates.py`
- SQLite -> PostgreSQL migration tool: `/Users/minleihao/marketing-agent/novaRed/scripts/migrate_sqlite_to_postgres.py`

## Data Backends
- Default: SQLite (`data/webapp.db` under `NOVARED_DATA_DIR`)
- Optional: PostgreSQL via `NOVARED_DATABASE_URL` (or `DATABASE_URL`)

When PostgreSQL is enabled, SQL placeholder translation and insert-id handling are routed through `db_backend.py`.

## Security and Permission Invariants
Do not bypass these checks:
- Viewer check for shared reads: `conversation_visible_or_404(...)`
- Owner-only mutations: `conversation_owner_or_404(...)`
- Visibility/group consistency: `_validate_share_group_for_user(...)`

Rules that must remain true:
- `task` visibility must reference an approved `task` group membership
- `company` visibility must reference an approved `company` group membership
- KB binding to conversation must verify current user can access that KB version
- `General Group` must remain protected, admin-owned, and auto-joined for new users

## Collaboration Semantics
- Shared records and owner records must stay distinguishable in API payloads and UI labels.
- Group lifecycle includes request, approve/reject, invite accept/reject, leave, and admin transfer.
- Group admins and system admin can remove approved members; removing a `General Group` member must not auto-rejoin them until they explicitly join again.
- Group deletion authorization:
  - group admin can delete own group
  - system admin can delete any group
  - non-admin users can leave but cannot delete the group

## Known Sensitive Areas for Refactors
- `src/webapp.py` still contains many routes and domain helpers; refactor incrementally by feature slice.
- Keep backward-compatible schema migrations for existing deployments.
- Preserve SSE streaming behavior and fallback handling in message endpoints.
- Keep seeded defaults idempotent so restarts do not duplicate General Group resources.

## Recommended Dev Workflow
1. Make focused refactors with behavior-preserving tests first.
2. Run compile checks after every structural extraction:
   - `python -m py_compile src/webapp.py src/db_backend.py src/db_schema.py`
3. Run targeted regressions:
   - `uv run pytest -q test/test_main.py test/test_webapp.py`
4. For permission changes, validate cross-user visibility and forbidden access paths.

## Next Refactor Targets
- Split `webapp.py` route domains into routers (`auth`, `groups`, `kb`, `conversations`, `admin`).
- Extract shared permission/service logic to dedicated modules.
- Continue reducing cross-cutting global helpers in favor of explicit service boundaries.
