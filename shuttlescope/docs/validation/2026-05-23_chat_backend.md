# Growth Advisor Chat Backend (models + migration + router)

Date: 2026-05-23

## Scope (backend only — no frontend)
- DB models: `ChatSession`, `ChatMessage` in `backend/db/models.py`.
- Alembic migration: `backend/db/migrations/versions/0035_chat_sessions.py`.
- Router: `backend/routers/insights_chat.py` (registered in `backend/main.py`).
- Tests: `backend/tests/test_insights_chat.py` (12 tests).

## Endpoints (all under `/api`)
- `POST /insights/chat/sessions` — create session (coach/analyst/admin only).
- `GET /insights/chat/sessions/{sid}/messages` — list history (owner or admin).
- `POST /insights/chat/sessions/{sid}/messages` — send message + AI reply.
- `DELETE /insights/chat/sessions/{sid}` — soft-delete and anonymize content with `(reset)`.

## Safety
- Role gate: `coach / analyst / admin` only; player → 403; unauthenticated → 401.
- Rate-limit: 1 message / 2 seconds per user (in-memory dict).
- Sanitization: `sanitize_user_input` → `injection_attempt` flag triggers a
  canned safe message (no LLM call), persisted as `author=system` with
  `validation_reason='injection_attempt'` and `is_fallback=True`.
- Budget: `check_and_record_budget(user_id, ~200 tokens)` → 429 on exhaustion.
- Generator: `get_generator()` (default `template`; external LLMs auto-wrapped
  by `HarnessedGenerator`). AI messages carry `confidence`, `evidence_path`,
  `generator`, `is_fallback`, `validation_reason` for UI uncertainty surfacing.

## Future Work
- `_build_analytics_context` is a stub returning sample numbers. Future slice
  should populate from real `shot_win_loss` / `recent_form` / etc.
- Rate-limit and budget are in-memory (POC); promote to DB / Redis when
  multi-process deployment lands.

## Verification
- `pytest backend/tests/test_insights_chat.py` → 12 passed.
- Combined: `test_insights_chat.py + test_insight_harness.py + test_insights_frame.py` → 32 passed.
- Security regression: `test_security_role_restrictions.py + test_demo_role_access.py` → 73 passed.
- `Base.metadata.create_all(engine)` for `ChatSession`/`ChatMessage` → ok.
