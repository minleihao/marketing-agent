# Marketing Copilot: Comprehensive Improvement Plan

## 0) Goals and Constraints
- Keep all existing core features stable:
- user registration/login/user management
- chat + multi-conversation
- KB management + sharing permissions
- bilingual UI
- Add orchestration, memory/RAG, security hardening, and growth-system scaffolding incrementally.
- Prioritize production safety: backward-compatible DB migrations and no breaking API contract for existing front-end flows.

## 1) Architecture Evolution Plan
### Phase A (P0, implemented in this iteration)
- `src/main.py` upgraded to staged orchestration:
- BriefNormalizer -> Planner -> Generator -> Evaluator
- Structured JSON normalization and fallback guards at each stage
- Optional structured trace payload (`include_trace`) for persistence
- Conversation memory context:
- recent N turns context + rolling summary memory
- RAG-lite retrieval:
- document chunk indexing + relevant chunk retrieval (query overlap scoring)
- Security baseline:
- CSRF token per session + middleware enforcement for mutating `/api/*`
- login rate limiting (username/IP failure window)
- default admin forced password-rotation support (`must_change_password`)
- secure cookie toggle (`NOVARED_COOKIE_SECURE`)
- Data persistence:
- orchestrator stage artifacts persisted per conversation response
- new experiment-center schema + base APIs

### Phase B (P1, next)
- Split monolith `src/webapp.py` into:
- `routers/` (auth, chat, kb, groups, experiments, admin)
- `services/` (permissions, memory, orchestration persistence, security)
- `repositories/` (SQL access)
- `templates/static` for UI assets
- Add approval workflow for high-risk outputs:
- evaluator score threshold + human approval state
- Extend experiment center:
- hypothesis lifecycle, variant traffic split, result ingestion endpoint, auto retrospective

### Phase C (P2, next)
- Connector layer (read-first):
- GA4, HubSpot, Meta Ads, Google Ads
- Async worker queue for heavy tasks:
- generation, scoring, connector sync, nightly summaries
- Event-driven workflow:
- brief -> plan -> generate -> evaluate -> approve -> publish draft
- Metrics cockpit service:
- CTR/CVR/CPL/CAC ingestion and recommendation loop

## 2) Prompt/Orchestration Detailed Spec
### BriefNormalizer
- Input: raw prompt + structured fields from UI
- Output: strict JSON only
- Responsibilities:
- infer task type and channels
- produce missing-info and executable assumptions
- define success metrics and initial hypotheses

### Planner
- Input: normalized brief JSON
- Output: strategy JSON only (no final copy)
- Responsibilities:
- positioning angle, message pillars, funnel stage, offer strategy
- channel execution map
- experiment matrix and risk mitigations

### Generator
- Input: normalized brief + planner output
- Output: production-ready markdown assets
- Responsibilities:
- multi-channel variants
- reusable variable placeholders
- CTA options and launch checklist

### Evaluator
- Input: normalized brief + planner output + generated content
- Output: score JSON only
- Dimensions:
- brand consistency
- clarity
- conversion potential
- compliance risk
- Includes score reasons/evidence and required revisions.

## 3) Security Hardening Detailed Spec
### CSRF
- Session stores `csrf_token`.
- Middleware enforces `X-CSRF-Token` on mutating `/api/*` requests.
- New endpoint: `GET /api/csrf`.
- Front-end API wrappers now attach CSRF token automatically.

### Password Safety
- `users.must_change_password` introduced.
- Default admin auto-flagged for password change if still default credential signature.
- Enforcement is now configurable by `NOVARED_ENFORCE_DEFAULT_ADMIN_PASSWORD_CHANGE` (default `0` for testing).
- New endpoint: `POST /api/account/password`.
- Front-end enforces password change flow on login when required.

### Login Rate Limiting
- New `login_attempts` table.
- Failure counting by username and IP over rolling window.
- Login endpoint returns `429` on threshold exceed.

## 4) Memory and RAG Detailed Spec
### Conversation Memory
- Recent-turn context:
- last `MAX_MEMORY_TURNS` turns injected into generation context
- Rolling summary:
- persisted in `conversation_memories`
- updated after each assistant response

### Document RAG-lite
- Uploaded docs are chunked and indexed in `document_chunks`.
- Retrieval uses query/chunk token overlap scoring.
- Context includes top relevant chunks with filename + chunk index references.
- Backfill mode: legacy docs auto-indexed on first retrieval.

## 5) Data Model Additions (Implemented)
- `users.must_change_password`
- `sessions.csrf_token`
- `document_chunks`
- `conversation_memories`
- `orchestrator_runs`
- `login_attempts`
- `experiments`
- `experiment_variants`

## 6) New/Updated APIs (Implemented)
- `GET /api/csrf`
- `POST /api/account/password`
- `GET /api/conversations/{id}/orchestrator-runs`
- Experiment scaffold:
- `GET /api/experiments`
- `POST /api/experiments`
- `GET /api/experiments/{id}`
- `POST /api/experiments/{id}/variants`
- `PATCH /api/experiments/{id}/status`

## 7) Frontend Updates (Implemented)
- App/KB/Groups/Admin pages:
- unified CSRF bootstrap + header injection for write operations
- App page:
- password change action button
- forced password-change flow support

## 8) Validation and Regression Plan
### Automated
- `python -m py_compile src/main.py src/prompts.py src/webapp.py`
- `uv run pytest -q`

### Scenario-level Smoke
- multi-user group approval and content sharing isolation
- KB bind permission check (private KB cannot be attached by non-owner)
- CSRF enforcement on mutating APIs
- experiment API lifecycle smoke

## 9) Remaining Work Items (Prioritized)
### Immediate
- Add dedicated pytest suites for:
- permission matrix
- CSRF enforcement
- orchestration trace persistence
- Introduce brand-governance policy checks in evaluator gating

### Near-term
- Extract front-end from embedded HTML to TS component app
- Add queue-backed async jobs and status polling
- Connector read pipelines and normalized metric model

### Mid-term
- PostgreSQL migration path (with migration tooling)
- full approval workflow and audit trails
- recommendation loop with budget allocation simulation
