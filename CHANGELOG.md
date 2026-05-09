# Changelog

This changelog records ShuttleScope's evolution from repository creation onward.
It is intentionally more detailed than a typical release changelog because the project is still moving quickly, and the history itself is useful context and motivation.

Read it together with:

- `README.md` for the current product scope and what is realistically usable now
- `shuttlescope/docs/validation/` for narrower validation notes and issue-by-issue verification

## How To Read This File

- Dates are grouped by development day.
- Entries are written at a product / workflow level, but they stay close to what was actually implemented.
- This is not a literal dump of `git log`, but it aims to preserve the meaningful shape of the work.

## 2026-05-09

### Cross-Team Page-Access Scope Check (Round 237-257 Deeper Sweep)

A 21-round deep-dive sweep across already-covered areas surfaced one
cross-team data integrity gap that needed fixing.

- `GET /api/auth/users/{target_id}/page-access`, `PUT` of the same path,
  `GET /api/auth/teams/{team_name}/page-access`, and the `PUT` for
  team-level page access only enforced `_require_manager`
  (admin / analyst / coach) and did not verify that the actor's team
  matched the target. An analyst from team A could:
  - GET another team's player's page-access list (information leak).
  - PUT `{page_keys: []}` to another team's player → wipe their grants.
  - The same shape applied to the team-level endpoints.

  `GRANTABLE_PAGES` is allowlisted (`{"prediction", "expert_labeler"}`),
  so the attack could not grant *new* privileges, but the
  DELETE-then-INSERT pattern still allowed wiping existing grants —
  a cross-team data integrity violation.

  Fix: `ctx.team_id == user.team_id` (and `ctx.team_name == team_name`
  for the team-level endpoints) is now required for non-admin actors,
  with 404 returned on mismatch to avoid leaking existence of the
  cross-team target.

### Sweep Coverage (no findings, recorded for completeness)

The remaining 20 rounds confirmed defenses across:

- Open-redirect / Location-header — only `/jp` → `/` is hardcoded; no user-influenced redirect.
- Command-injection probe — `subprocess.run(shell=True)` is not used anywhere; yt-dlp / ffmpeg invocations go through `_validate_url_for_subprocess` and use list-style args plus the `--` separator.
- Insecure deserialization — only `yaml.safe_load` / `yaml.safe_dump` are used; no `pickle` / `marshal`.
- ORDER BY / column injection — every `order_by(...)` uses ORM column references; no `text()` with f-string interpolation.
- CORS — invalid `Origin` headers do not receive `Access-Control-Allow-Origin`; preflight from `null` / evil origins returns 400.
- Stored XSS — bookmark.note / comment.text strip script / img / svg / iframe / style / meta tags; React renders all `note` / `text` fields as text, no `dangerouslySetInnerHTML` anywhere.
- Concurrent state — 5-parallel rally / set / condition POSTs and match.result PUTs produce zero 500s. Lack of unique constraint on (set_id, rally_num), (match_id, set_num), (player_id, measured_at) is a data-quality observation rather than a security issue.
- Rate-limit IP spoofing — `X-Forwarded-For` / `X-Real-IP` spoofing has no effect; `CF-Connecting-IP` from clients is rejected by Cloudflare itself with 403.
- HTTP smuggling — `Content-Length` + `Transfer-Encoding` conflict and bad chunk sizes are rejected at the Cloudflare front line with 400.
- Method-override — `X-HTTP-Method-Override` / `X-HTTP-Method` / `_method` headers are ignored. WebDAV verbs are not implemented.
- Path traversal — `..%2F` / null-byte / file:// / Windows reserved names against video / clip / upload / training_data endpoints all return 404 / 422.
- MFA / password reset / email verify — wrong TOTP repeated 8× yields 422 each time; arbitrary password-reset / email-verify tokens produce 400 / 405.
- Search SQL — `pg_sleep` / `' UNION SELECT` / null-byte / `%%` payloads against `/api/players?q=` all complete in < 0.25s with 200; ORM parameterization is intact.
- Public abuse — `/api/public/contact` rate-limits at the third inquiry per address; BIDI / huge-name / over-length payloads are 422 in the validator.
- Host header injection — Cloudflare returns 403 for any unauthorized Host.
- WebSocket — `/api/ws/live` / `/ws/live` / `/api/realtime/yolo` (with or without a valid session_code) require auth; 403 without it.
- Refresh token rotation — old refresh token reuse is detected on the second use and the entire family is invalidated.
- Cross-team match owner spoof — analyst-supplied `owner_team_id` and `is_public_pool` are silently overridden by `ctx.team_id` / `False` server-side.

### P6-P10 Thin-Areas Sweep (Round 232-236)

One additional backend fix and a cross-cutting operational review.

- `POST /api/auth/login` with a `username` or `identifier` containing a NUL byte (or any other C0 control character) returned `500` instead of `422`. PostgreSQL's text column rejects NUL bytes via `psycopg.ValueError`, which surfaced as the generic 500 "internal error" response. `LoginRequest` now applies a `@field_validator(mode="after")` that rejects any character in `0x00-0x1F + 0x7F` with 422 before the value reaches the SQL query.

### Operational observations recorded for separate handling

These items came out of the Round 232-236 sweep across Windows ops, audit log integrity, ML model supply chain, backup/restore, and browser cache. They are not deployed code changes — they require migration coordination, infrastructure setup, or product-policy decisions, and are tracked in `private_docs/2026-05-09_user_must_verify_checklist.md`.

- Audit-log HMAC chain integrity is broken at the first row whose `user_id` was nulled by a previous user deletion. `GET /api/auth/audit-logs/verify` reports `ok: false`. Two fix paths exist: (a) Alembic migration to drop the FK on `access_logs.user_id` so the chain canonical bytes are never modified, or (b) make `verify_chain` anonymize-aware. Either is migration-coordinated.
- Production backup gap: `POST /api/sync/backup` returns 501 because the existing implementation is SQLite-only, and there is no Windows scheduled task or filesystem evidence of an external `pg_dump` / WAL archive. PostgreSQL data is not currently protected against volume failure.
- File ACL on `shuttlescope/.env.development` and `cloudflare-shuttle-scope/config.yml` includes the local `MiniTakeuchi\CodexSandboxUsers` group (members: `CodexSandboxOnline`, `CodexSandboxOffline`). If those accounts are reachable over the network, `SECRET_KEY` / `SS_OPERATOR_TOKEN` / `DATABASE_URL` are exposed to them.
- The `Cloudflared` service runs as `LocalSystem` but its binary lives in `C:\Users\kiyus\AppData\Local\Microsoft\WinGet\...\cloudflared.exe`, a path writable by the `kiyus` account. Compromising `kiyus` would allow a binary swap that the next service start runs with SYSTEM privileges.
- `ssh.shuttle-scope.com` routes to `localhost:22` over Cloudflare Tunnel. Cloudflare Access policy on that hostname is not verifiable from inside the box; needs a dashboard check.
- `backend_daemon.ps1` exits with the Python child's exit code; the scheduled task does not auto-restart on failure (RestartCount: 0). Single Python crashes leave the backend down until the next boot/login trigger.
- `backend/models/` (`*.onnx`, `*.engine`) has no integrity manifest. Local model swap by an attacker with `kiyus` privileges is undetected.
- `yt-dlp` is two months behind release; several Python deps (sqlalchemy, alembic, httpx, requests, uvicorn) are also slightly behind. `pip-audit` integration recommended.
- `localStorage` keys for match-specific UI state (`court-calib-{matchId}`, `yolo-last-roi-{matchId}`, `shuttlescope.viewpoint.{matchId}`) are not user-scoped; on a shared PC, the previous user's state survives a logout. SaaS / per-browser deployment is unaffected.

### Cascade & FK Cleanup (Round 227-231 Local Boundary / Artifact Lifecycle)

Three additional backend fixes shipped after the Round 200-226 batch.

- `DELETE /api/matches/{id}` now cascades comments and event_bookmarks via Core SQL `DELETE` before `db.delete(match)`. Previously, matches with attached comments or bookmarks failed at commit with `psycopg.errors.ForeignKeyViolation` and surfaced the raw SQL detail (table + constraint name) in the 500 response. The 500 detail is now sanitized; full diagnostics go to server log.
- `DELETE /api/auth/users/{id}` repaired. The previous cleanup statement list contained typos (`access_log` vs the actual `access_logs`; `user_invitations.created_by_user_id` and `shared_sessions.created_by_user_id` did not exist) and missing FK paths (`matches.annotator_id`, `shot_annotations.annotator_user_id`, `billing_orders.user_id`, `billing_entitlements.user_id` / `granted_by_user_id`, `revoked_tokens.user_id`, `user_consents.user_id`, `player_page_access.user_id`, `user_invitations.consumed_by_user_id`). Each cleanup statement also called `db.rollback()` on exception, which reverted ALL prior successful cleanups. Each cleanup is now wrapped in `db.begin_nested()` (SAVEPOINT) so a failure on one statement no longer poisons the others, and the 409 response detail is now generic.

### Validation

- Round 229 post-deploy verification: 11/11 ✅. Match deletion with attached comments / bookmarks succeeds; bookmarks and comments are removed; subsequent GET / list / export return 404 / 422. User deletion (with the cleanup) succeeds for freshly-created users; the access token, refresh token, and login-after-delete all return 401. Player record survives user deletion (player_id was nulled on the user side via existing FK behaviour).
- Round 230 (admin blast radius): admin rapid-create 30 users / 30 teams produces no 500 / no rate-limit hits — by design but worth flagging for guardrail review. Audit log spot-check confirmed 26 unique action types (login / login_failed / logout / token_refresh / user_created / user_updated / user_updated_high_risk / user_deleted / team_created / team_updated / match_updated / match_deleted / consents_submitted / consent_withdrawn / training_data_record_created / content_report_received / content_report_triaged / export_package_created / password_reset_by_admin / admin_reset_user_limits / account_locked / account_unlocked / access_denied / access_denied_write / access_denied_coach_scope / access_denied_research) over a 500-row sample.
- Round 231 (legal / ops workflow drill): consent withdrawal correctly rejects contractual-basis types (`service_delivery`, `beta_agreement`) with 403 and accepts optional types (`ai_training`, `research_participation`) with 200, satisfying GDPR Article 7(3). Training-data records remain immutable (PUT / DELETE → 405). Self-delete is blocked (400). The Subject Access Request (SAR) and counter-notice routes are 404 / 405 / 401 — confirmed as known operational gaps tracked separately for Wave B / `SAR_PROCEDURE.md`.

### Static Review (Round 227, no code change)

The Electron `main.ts` (1615 lines) and `preload.ts` (92 lines) were re-read end to end. Defenses confirmed in place: `localfile://` and `app://video/{token}` schemes use URL parsing with strict path-jail and 32-hex token regex; the main BrowserWindow runs with `contextIsolation: true` / `nodeIntegration: false` / `webSecurity: true`; `will-attach-webview` strips unknown webPreferences keys and forces `sandbox: true`; `relaunch-app` is gated by sender-WC, top-frame, 5s user-gesture, and 30s rate limit; `mirror-broadcast` enforces a four-type allowlist and 32 KB cap; `save-recorded-video` validates ArrayBuffer + magic byte (webm / mp4 ftyp) + extension + dialog-only path + 4 GB cap; the Python backend is spawned with an absolute path and explicit env (no PATH lookup); packaged builds block DevTools at the input-event layer. Two minor observations (not vulnerabilities): `SS_LIVE_ARCHIVE_ROOT` not set leaves drive isolation off (warned at startup but not enforced); `_userSelectedPaths` is session-scoped and persists across the session for any file selected via dialog.

### Notes

- Player-facing UI policy leak (Round 228 finding) — the `Sidebar` `/dashboard` link, `DashboardTopNav` six routes, and `DashboardReviewPage` i18n labels (`analysis.review.section_maps` = "STEP 1 — 弱点・配球マップ", `guide_step1` = "① 受け側の弱点・有効配球を確認", `vulnerability_map` = "被打球弱点マップ") are reachable from the `player` role. Backend `/api/analysis/received_vulnerability` already returns 403 to player so the data is empty, but the literal labels render. This violates the CLAUDE.md non-negotiable rule "Never show players direct 'weakness' framing". Tracked as a UX-decision item (route gating / hasPageAccess('dashboard') / role-based label substitution) and intentionally not fixed in this batch.
- Team delete API gap — `/api/auth/teams/{id}` has no DELETE handler. The model has `deleted_at` but no soft-delete endpoint. Operational gap, not a vulnerability.
- Audit-log HMAC chain integrity vs FK enforcement — `delete_user` updates `access_logs.user_id = NULL`, but the original `row_hash` was computed with the original `user_id` and `verify_chain` re-derives canonical bytes from current row state, so the hash chain breaks after a user is deleted. Architectural tension (FK vs append-only); migration to remove the FK or switch to `ON DELETE SET NULL` is the long-term fix.

### Input-Validation Defense-in-Depth (Round 200-226 Continuous Attack)

Twenty-one attack-driven backend fixes shipped in two deploy batches.

- Aligned Pydantic `max_length` with the underlying SQLAlchemy column lengths (`Player.name` / `name_en` / `nationality` 100/100/50; `User.display_name` / `username` / `team_name` 100; `Team.name` 100, `short_name` 50, `display_id` 64). Rejection that previously slipped past the validator and tripped a 500 at INSERT time is now a 422.
- Replaced the local control-character-only filter on `Player` and team text fields with `text_sanitize.reject_ctrl_and_bidi`, so RTLO / LRO / ZWSP / ZWNJ / BOM / CRLF / null bytes are rejected together with C0 control characters. The same rule was applied to `bookmark.note`, `comment.text`, public-inquiry fields, `condition_tag.label`, and upload filenames; the HTML-strip regex used by the comment/note/inquiry sanitizers now iterates to a fixed point and removes lingering bare `>` characters so obfuscation patterns like `<scr<!---->ipt>` no longer leave residue.
- Added a per-element validator for `Player.aliases`: each item must be a string passing `reject_ctrl_and_bidi(max_len=120)`, and the list is capped at 50 items.
- Replaced `Player.dominant_hand` free-string acceptance with an enum guard (`R` / `L` / `unknown`).
- `POST /api/auth/users` and `POST /api/auth/teams` now catch SQLAlchemy `IntegrityError` from concurrent unique-constraint races and return `409 user already exists` / `409 team already exists` instead of leaking `500` with stack-trace shape.
- `Point2D` (court calibration) and `RoiRectModel` (TrackNet batch) now bound coordinates to `[0,1]` with `allow_inf_nan=False`. `CourtCalibrationRequest` enforces exactly 6 points at the schema layer and bounds `container_width` / `container_height` to `1..8192`. `FrameDetectRequest.timestamp_sec` is bounded to `0..86400`. Out-of-range / NaN / Infinity inputs that previously reached `numpy.linalg.svd` and surfaced as `500 SVD did not converge` are now rejected with `422` at the Pydantic layer.
- Added `model_config = {"extra": "forbid"}` to LabelPayload, ShotAnnotationPayload, AuxiliaryInput, QuestionnaireSubmit, RegisterRequest, PasswordResetRequest, PasswordResetConfirm, InvitationCreateRequest, InvitationAcceptRequest, PendingApprovalRequest, RallyCreate, RallyUpdate, StrokeData, RallyData, SetRoleBody, QuickStartBody, HumanForecastCreate, CreateOrderRequest, CreateProductRequest, GrantEntitlementRequest, DownloadRequest, Point2D, CourtCalibrationRequest, RoiRectModel, BatchRequest, FrameDetectRequest. Field-level `max_length` / `ge` / `le` constraints were added on the same models so payload size is bounded at the schema layer.
- `sync.backup_now` no longer returns raw exception text in the error detail; the path-related information is moved to server log via `logger.warning` / `logger.exception`, and the response uses generic status-tied messages. `label` query parameter is capped at 100 characters.

### Validation

- Round 212 post-deploy verification confirmed all 13 directly-found issues resolved (display_name boundary, player.name BIDI / ZWSP / CRLF / control, bookmark.note BIDI, comment.text BIDI, comment.text obfuscated HTML strip clean, aliases item BIDI / control / over-length / over-count, team-name BIDI / 101-char / short_name 51-char, parallel user-create race, dominant_hand enum).
- Round 211 race-suite re-run showed parallel team creation now produces `1×201 + 4×409` (previously `1×201 + 4×500`); user-creation race already converted in batch 1 produces the same shape.
- Round 225 post-deploy verification of the second batch (court / cv float bounds) returned `422` for Point2D out-of-range, NaN/Inf, points-array length ≠ 6, container_width/height out-of-range, FrameDetectRequest.timestamp_sec out-of-range, and tracknet RoiRectModel out-of-range — 13/13 ✅.
- Sweep rounds 213-218 (data_package signature, NFKC search, role matrix, GDPR consent lifecycle, JWT corner cases, cross-team isolation, expert-label boundaries, condition / condition_tag color, DoS / rapid-write / concurrent / 413, admin training_data / audit / cluster, security headers / CORS / timing) returned 0 critical findings.

### Documentation

- `private_docs/2026-05-08_continuous_attack_findings.md` now lists the 13 critical findings, their commits, and the post-deploy verification results.
- `private_docs/2026-05-08_secret_scanning_candidates.md` was extended with five additional candidate rules surfaced by Round 207-210: HTML-strip fixed-point loop, validator `max_length` vs DB column AST check, `list[str]` per-element validator coverage, `IntegrityError → 409` pattern enforcement, filename BIDI smoke.
- Per-batch validation memos under `shuttlescope/docs/validation/2026-05-09_*.md` (validator alignment batch, text-field BIDI / HTML strip, aliases validator, user-create race, static-review Pydantic field bounds).

## 2026-05-08

### GDPR / APPI Compliance Hardening

- Promoted Privacy Notice to Version 1.1 with a new Article V-bis ("AI Model Training Data Practices") covering training-data sources, exclusions, model memorization mitigations, the right to object to training use, and transparency disclosures. Added Section 2.6 covering cookie categorization on `shuttle-scope.com`. The existing Articles VI through X retain their numbering — V-bis is inserted between V and VI without disturbing downstream references.
- Promoted Terms of Service to Version 1.1 with a new Section 15 ("EU/EEA Operations") describing operational constraints (court ROI required; legitimate-interests basis for non-consenting third parties; bounded cross-border transmission), third-party athlete data handling under GDPR Article 21, and coordination obligations with Contributing Parties.
- Added `contracts/DPA_TEMPLATE.md` (public) — a template Data Processing Agreement compliant with GDPR Article 28(3), with annexes covering processing details, technical and organizational measures, sub-processors, and Standard Contractual Clauses placement.
- Added internal records (kept under `private_docs/internal/`, not committed): `RoPA.md` (Records of Processing Activities per GDPR Article 30, eight processing activities documented), `DPIA.md` (Data Protection Impact Assessment per Article 35), `SAR_PROCEDURE.md` (Subject Access Request operational procedure), `BREACH_RESPONSE.md` (Personal Data breach response plan with a 72-hour notification track and authority / data subject notification templates).
- Added a public-facing β-period agreement at `private_docs/contracts/RBC_BETA_AGREEMENT.md` (kept private; intended for distribution to in-scope athletes outside the repository) — derived from the prior internal docx, with personal names and parent-company references removed.

### Onboarding Consent Flow

- Backend: introduced the `user_consents` table (Alembic migration `0024_user_consents.py`) and `users.consent_required` flag. Added `UserConsent` ORM model. Exposed `GET / POST /api/auth/consents` and `DELETE /api/auth/consents/{type}` for retrieving consent state, submitting initial / updated consent, and withdrawing optional consents (required types refuse withdrawal — those require account deletion). `/api/auth/me` now returns `consent_required` so the frontend can route to the onboarding flow.
- Consent records capture privacy-policy version, terms version, given-at timestamp, IP address, and a SHA-256 hash of the User-Agent string (raw UA is not retained). Existing users are migrated with `consent_required=False` so the launch does not lock them out; new accounts default to `True` and must complete the consent flow before reaching the main UI.
- Frontend: added `OnboardingConsentPage.tsx` covering two required consents (`service_delivery`, `beta_agreement`) and three optional consents (`ai_training`, `research_participation`, `cross_border_transfer`). Each consent is an independent checkbox per GDPR Article 7(2). Links to the public Privacy Notice / Terms of Service / Data Contribution Terms are surfaced inline. `ProtectedMainRoute` in `App.tsx` gates the application behind the onboarding page until the required consents are submitted.

### Privacy-by-Design Hardening (CV Pipeline)

- `CourtBoundedFilter` (`backend/cv/detection_hardening.py`) now defaults to `strict_mode=True`, which forces `court_margin=0` and excludes any detection outside the calibrated court polygon. Spectator and umpire zones remain excluded by their dedicated checks. Strict mode is configured in code only; the settings UI does not expose it.
- The pipeline-run endpoint (`/v1/pipeline/run`, `backend/routers/pipeline.py`) refuses to enqueue analysis with HTTP 403 when the target match has no court calibration (`MatchCVArtifact` of type `court_calibration`). The rejection message references GDPR Article 25 / Privacy by Design so the operational reason is explicit.

### Repository Hygiene

- `private_docs/contracts/` and `private_docs/internal/` are kept under the existing `private_docs/` ignore rule. The new public-facing `contracts/DPA_TEMPLATE.md` (root-level) is committed.
- Added `private_docs/2026-05-08_gdpr_compliance_implementation_plan.md` recording the strict task plan that drove the work above; it is internal-only and is referenced in the DPIA's "Integration of outcomes" section.

### Consent UI Refinement (Contractual Basis vs Consent)

- Following an internal legal analysis, the Onboarding consent flow now distinguishes contractual confirmation from optional consent more strictly. The two required items (`service_delivery`, `beta_agreement`) carry the GDPR Article 6(1)(b) / APPI Article 18 contract-performance basis. Their UI labels read "...の内容を確認しました" rather than "...に同意します", their description texts cite the legal basis explicitly, and the section header notes that withdrawal of these items is equivalent to ending use of the service. The required badge reads "契約履行（必須）" rather than "必須" alone.
- The optional `cross_border_transfer` item was removed from the UI. EU→Japan transfers operate under the EU-Japan adequacy decision (effective January 2019), so a separate user consent for cross-border transfer is not the appropriate legal basis; surfacing such a checkbox risks misleading users into thinking transfers depend on their personal opt-in. APPI Article 28 cross-border safeguards remain in place via the safeguards described in `PRIVACY.md` Section 6.2 and the SCC placement of `contracts/DPA_TEMPLATE.md` Annex 4. Other future non-adequate destinations (e.g., the United States) will be handled through SCCs / equivalent measures rather than a UI checkbox.
- Optional consent items now state their withdrawal channel inline (in-application contact form, public contact form, or email to `contact@shuttle-scope.com`).
- `PRIVACY.md` Section 8.5 ("Withdrawal Mechanism (Interim)") added. It records the interim withdrawal channels, acknowledges the GDPR Article 7(3) "as easy to withdraw as to give" standard, and commits to delivering an in-application withdrawal interface no later than 31 December 2026. Required confirmations under the contractual basis are explicitly excluded from the withdrawal flow.

### Public-Facing β Agreement

- Added `contracts/BETA_DATA_HANDLING_AGREEMENT.md` as the repository's public template version of the β-period data handling agreement. Personal names and parent-organization references are stripped relative to the internal in-person `private_docs/ShuttleScope_同意書.docx`; the contact channel on the public version is `contact@shuttle-scope.com` plus the public contact form. The internal docx remains under `private_docs/` as the in-person signing instrument.

### Host Liability Posture Hardening

- Added `CONTENT_POLICY.md` as a public-facing description of how ShuttleScope treats user-submitted content, the channels through which a rights-holder, regulator, or data subject may file a content report, the format of such reports, and the response timeline. The Policy is written to align with the safe-harbour expectations of 17 U.S.C. § 512 (DMCA), Article 14 of Directive 2000/31/EC (EU e-Commerce Directive) as carried forward by Regulation (EU) 2022/2065 (DSA), and Articles 30 / 47-bis / 47-5 / 30-4 of the Japanese Copyright Act. The hosting posture is passive — content lawfully accessible to a User through paid streaming subscriptions, broadcast licensing, or other lawful means may be processed in the same manner as content the User has personally recorded; the developer responds after a verified report rather than by pre-screening submissions.
- Promoted `TERMS_OF_SERVICE.md` to Version 1.2. Section 4 ("Acceptable Use") is rewritten to reflect the passive hosting posture and to make the User's responsibility for the legal basis of submissions explicit. New Section 16 ("User Content and Hosting Posture") and Section 17 ("Developer Conduct Guarantees") record the developer's role separation between operator and user, the developer-side undertaking on training-data sourcing, the no-inducement statement, and a beta-period note. A future U.S. Designated Agent under 17 U.S.C. § 512(c)(2) is anticipated in Section 16.7.
- Promoted `PRIVACY.md` to Version 1.2 with a small addition (Article IX Section 9.3 "Beta Period Interim Measures") recording that the technical and organisational measures described in Article IX are operated under interim arrangements during the beta period and that material changes affecting personal-data protection will be reflected in subsequent updates to the Notice. No new processing purposes or recipients are introduced; existing consent records remain valid.
- `SECURITY.md` now points content reports (non-vulnerability) to `CONTENT_POLICY.md`, separating that channel from the vulnerability reporting channel.

### Internal Operational Documents (Host Liability)

- Added `private_docs/internal/NOTICE_AND_TAKEDOWN_PROCEDURE.md` recording the operational notice-handling flow that backs the public commitments in `CONTENT_POLICY.md`, with templates for receipt acknowledgement, action notification (user side), and action notification (complainant side).
- Added `private_docs/internal/DEVELOPER_CODE_OF_CONDUCT.md` codifying the developer's operator-role and user-role conduct rules, the no-inducement rule, the training-data sourcing discipline, and the annual self-audit cadence.
- Added `private_docs/internal/LEARNING_DATA_PROVENANCE.md` defining the provenance schema, license categories (granted / public_domain / appi_47_4 / appi_47_5 / beta_legacy_assumed_legal / other), the beta-vs-production phase boundary, and the recording discipline. A database-backed implementation of this register is planned in the second wave of the Host Liability work; the document at present operates as the schema-of-record.
- Added `private_docs/2026-05-08_host_liability_implementation_plan.md` recording the strict task plan for the host-liability hardening, the wave structure (A: documents now / B: code enforcement / C: future commercial work), and the legal mapping driving the work.

### Host Liability Code Enforcement (Wave B)

- Added Alembic migration `0025_content_reports_and_provenance.py` introducing two new tables. `content_reports` persists notice-and-takedown reports with the elements expected by 17 U.S.C. § 512(c)(3) and the corresponding national equivalents; the schema captures complainant identification (where provided — anonymous reports are accepted), the subject of the report, the legal basis invoked, an audit trail of the developer's triage and action, and any counter-notice received. `training_dataset_records` persists the schema described in `private_docs/internal/LEARNING_DATA_PROVENANCE.md` so that the provenance register is kept in the database rather than only as documentation; the source URL is stored as a SHA-256 hash rather than in plaintext.
- Added `ContentReport` and `TrainingDatasetRecord` ORM models to mirror the schema.
- Added the public reporting endpoint `POST /api/public/content_report` (anonymous accepted, rate-limited via the existing contact-form rate limiter, honeypot field for bot rejection, statement length 20–5000 characters, optional `legal_basis` from a closed enum). The response carries the report id, the receipt timestamp, and an acknowledgement message that points back to `CONTENT_POLICY.md` Section 7 for the SLA.
- Added admin-only triage endpoints `GET /api/admin/content_reports`, `GET /api/admin/content_reports/{id}`, and `PATCH /api/admin/content_reports/{id}` so the developer can record triage status (pending / upheld / rejected / awaiting_info / on_hold), action taken (no_action / content_removed / access_restricted / account_suspended / pending_legal), counter-notice receipt, and restoration. Each transition is logged through the existing `audit_log` channel.
- Added admin-only training-data provenance endpoints under `routers/admin_training_data.py`: `POST /api/admin/training_data/records`, `GET /api/admin/training_data/records` (filterable by license_type / beta_legacy_flag / dataset_id), and `GET /api/admin/training_data/records/{id}`. Source URLs are not retained; the endpoint hashes the URL with SHA-256 before persistence.
- Registered the new audit-log event names (`content_report_received`, `content_report_triaged`, `training_data_record_created`) in the audit-coverage allowlist.

### Wave B — Deferred to a Later Round

- Mandatory `reason` parameter on admin video-access endpoints. Admin video access in the current architecture flows through team-scoped match endpoints (rather than a single dedicated admin path) and is already audited under the standard auth audit. Adding a `reason` requirement is worthwhile but requires endpoint-by-endpoint analysis and was scoped out of this round to keep the change set focused.

## 2026-05-07

### Streaming-Capture Recording for Member-Only Live Sites

- Generalised the desktop screen-recording feature beyond the original YouTube-only path so the analyst can capture badminton broadcasts on any streaming site they are licensed to view. Recording is OS-level pixel capture (the OBS-equivalent path) only; no DRM or HDCP bypass is implemented anywhere in the project. Quality presets (low / med / high), a recording state machine, and a post-processing warning when the captured frames are mostly black (i.e. the platform actively blocked the capture) were added at the same time.
- Added a video-password field to the streaming download panel for sites like Vimeo Showcase. Browser cookies (`cookies.txt`) and that password are passed to the downloader and discarded immediately after the job runs; neither is logged.
- Documented the three available recording paths (yt-dlp, in-app WebView + screen capture, and the optional castLabs Electron build) in `docs/electron-drm.md`, including why castLabs is left as a user-managed opt-in.

### Annotator Audit Sweep — UX, Keyboard, Errors, Mobile

- Three coordinated review passes against the annotator workflow (28 items total). Highlights: improved contrast on the active stroke-type tile so it stays WCAG AA, expanded keyboard coverage (number-row binds for hit/land zones, Tab to swap player, an opt-in always-on key-hint toggle), a 4-state step indicator with focus ring and screen-reader hints, replaced every native `alert()` / `confirm()` with accessible toast and modal components, and migrated ~150 remaining hardcoded Japanese strings into the translation tree.
- Mobile pass: walked the dashboard / settings / condition / review surfaces at iPhone widths and fixed every place tabs and tables spilled outside their container. `useBreakpoint` was extended to the full 6-stage Tailwind ladder, and a phone-sized players sheet and iPad sidebar layout were rebuilt on top of that hook.
- Consolidated the annotator's various menu surfaces into a single top-bar menu plus a flattened settings panel, and surfaced the existing `Ctrl+K` command palette as a visible button so it is discoverable.

### Operator: Production Scheduled-Task Recovery

- Caught a regression where the production task supervisor had been reverted from a system-level run mode to an interactive one and would die on logoff. Re-registered it with the correct system-level principal, restart count, and start trigger. Operator notes for safe deploy and restart steps were updated.

## 2026-05-04

### Annotator UX Redesign

- Full redesign sprint over the annotator workflow: top-bar split into a primary score display plus a kebab menu, mode tabs for Input / Review / Analysis / Settings driving a right panel that only shows what the current mode needs, a bottom history strip with click-to-seek, floating video-overlay toggles, and a `Ctrl+K` command palette. A mobile variant with a bottom sheet was added in the same sprint, and remaining hardcoded strings were migrated to the translation tree.
- Annotator craftsmanship: hit-zone manual override, offline rally stash, semantic colour system on the stroke-type panel, haptics, and a semi-auto flip path that fixes a player-selection regression during quick rally entry.

### CV Foundation — Tracks A through E

- Person-tracking, pose estimation, swing detection, and hitter attribution rolled in over multiple tracks with a fallback chain documented for future tuning.

### Mobile-Responsive Pass

- Walked the condition / team / settings / camera / expert-labeler surfaces at iPhone widths and applied the same overflow / clipping / mobile-card recipe that the dashboard had been using.

### Video Pipeline Fixes

- Resolved a bundle of bugs that together had been blocking browser-side playback of server-stored matches and CV pipeline reads of the same.
- Added an automated archive step that moves downloaded videos off the working drive after a configurable interval, with a path safety jail and DB-side path tracking.

### Internal Reviews and CI

- Closed two coordinated review sweeps (general code review and an analytics-focused ultra-review) and brought the TrackNet smoke workflow back to green after dependency drift in the runtime stack.

### Data-Loss Incident and Recovery

- An automated review tool was invoked on an orphan branch and wiped a gitignored area holding validation notes, helper scripts, and downloaded video archives. Validation docs were recoverable from the production machine; the unsynced video archive was lost. Going forward, the tool is treated as destructive on this repo and a backup of the gitignored areas is taken before invoking it.

## 2026-04-30

### CI Restoration on Windows and Linux

- Cleaned up CI infrastructure issues so backend tests, frontend tests, build, and the security-conventions check pass on both `ubuntu-latest` and `windows-latest` runners.

### Security Hardening

- Closed the Critical and High findings from the static analysis sweep through additional input validation and path-safety guards. Specific finding details and the corresponding mitigations are tracked in the project's internal security log rather than this public changelog.
- Tightened HTTP response headers (Content-Security-Policy on HTML responses, Permissions-Policy, COOP / CORP) and adjusted CORS for the public deployment posture.
- Hardened authentication-related timing characteristics so failed login responses do not leak whether a username exists.
- Restored the emergency token-revocation path after a regression. Operational runbook for incident response is maintained internally.
- Added admin tooling (per-user limit visibility and category-scoped reset) to make abnormal usage visible from the admin UI rather than only in process memory.

### Streaming Upload Path

- Introduced a streaming-upload flag for MediaRecorder-style chunk uploads where the final file size is not known until finalize. Strict ordering on chunk receipt and an upper bound on total bytes are enforced server-side. Frontend updated to use the matching content type.

### Unattended Operation

- Stood up the production backend supervisor and the tunnel as proper Windows services with restart policies, so a connect-holiday absence does not lose service on crash or logoff.

### Internal Verification Rounds

- A multi-week sequence of attack rounds was run against the live deployment. The findings, mitigations, and per-round verifications are tracked internally; the changelog only records that the sweep happened.

## 2026-04-29

### Sender-Side Server Recording

- Reworked the camera sender path so recordings are uploaded to the server (rather than only existing as a P2P WebRTC stream that disappears at session end). Each completed upload is registered for downstream worker / archive processing.

### LAN-First Endpoint Resolution

- Added preferred-endpoint resolution that races configured candidate hosts on session join, so a sender on the same Wi-Fi as the operator PC takes the LAN path directly instead of round-tripping through the public tunnel.

### Cloudflare Named Tunnel Support

- Routed coach / camera-sender / WebSocket URLs through the named tunnel host when active, with a fallback for tunnel configurations that are managed from the Cloudflare dashboard.

### Phase Pay-1 Billing Foundation

- Wired up multi-provider checkout behind a feature flag (off by default). Receipts are generated as PDFs and legal metadata is sourced from environment variables. All billing endpoints are excluded from the public OpenAPI schema.

### Phase M-A Email Authentication Foundation

- Implemented register / verify / password-reset / invitation flows around a mail-backend abstraction. Self-registered users land in a pending state and require admin approval before becoming active. Public registration is opt-in via configuration.

### Data Protection

- Added field-level encryption, encrypted backup output, signed export packages with replay defence, and operator runbooks for incident response.

## 2026-04-28

### Live Recording Workflow

- Added a live-stream recording flow that supports cookie-based authentication for paywalled sources, with a job model and an off-volume archive step that respects the configured allowed-paths policy.

### Path Safety

- Centralised path validation through a single helper that accepts only the configured roots, with canonicalisation that prevents traversal and symlink games.

### Video Token Privacy

- Replaced the previous raw filesystem-path exposure in API responses with an opaque token plus a team-scope-gated lookup, so reading a video requires both the token and an authorised match relationship.

## 2026-04-27

### Shot Annotation and Centre-of-Gravity Detection

- Added shot type annotation support via the expert labeler workflow, including a new `shot_labels` endpoint, `ShotAnnotation` model, and Alembic migration 0015.
- Added two ML pipeline stubs — a CLIP-based and an LSTM-based shot classifier — ready to connect to the expert annotation flow.
- Integrated CoG (centre-of-gravity) detection as a first-class panel in the expert labeling UI, linking motion analysis directly into the labeling session rather than keeping it as a separate standalone page.

### YOLO ByteTrack and TrackNet Profiling

- Added ByteTrack multi-object tracking configuration (`backend/yolo/bytetrack.yaml`) to support persistent player ID continuity across frames.
- Extended YOLO inference to integrate ByteTrack so player tracking is more stable over long video segments.
- Improved TrackNet frame-profiling instrumentation and zone-mapper zone-boundary precision so inference timing data is more actionable for performance tuning.
- Added a Pareto-sweep benchmark script for systematic throughput / accuracy trade-off exploration.

### Condition and Prediction Report Exports

- Added PDF export endpoints for condition reports and prediction reports under `/api/reports/condition` and `/api/reports/prediction`.
- Extended the frontend ConditionPage, PredictionPage, and UserManagementPage with export buttons and download flows.
- Updated DashboardShell to route the new report download actions through absolute `API_BASE_URL` to avoid Electron fetch failures.
- Added i18n strings for the new export UI elements in both English and Japanese localization files.

### Beta Terms and Public Site Updates

- Updated `TERMS_OF_SERVICE.md` with beta-specific usage terms.
- Added a beta notice banner to the public landing site with corrected spacing to avoid overlap with the fixed navigation bar.

### Input Validation and Sanitization

- Tightened input validation and text-field sanitization across the authenticated API surface and adjusted static-analysis suppressions where appropriate.

### Infrastructure and Test Stabilization

- Fixed an Alembic configuration ordering issue that affected CI test isolation, and updated bootstrap tests to cover the latest migration.

### Internal Adversarial Validation

- Ran an internal adversarial-validation pass across input handling, authentication, public-facing endpoints, and labeler scope enforcement. Findings and verifications are tracked internally.
- Converted findings into source-level fixes and database cleanup. 

## 2026-04-26

### Team Scoping / PostgreSQL Migration Rollout

- Added first-class team ownership for users, players, matches, comments, bookmarks, forecasts, warm-up notes, and related analysis data.
- Introduced the `teams` table and the Phase B migration chain (`0009` through `0014`) for moving from name/string-based team handling toward ID-based PostgreSQL-backed scoping.
- Made `matches.owner_team_id` part of the match ownership model and restored the NOT NULL migration as an explicit rollout step after earlier opt-in staging.
- Dropped the legacy player team string column after backfilling player `team_id`, keeping team lookup on the normalized team table instead of free-form text.
- Tightened auth context and JWT payloads so coach / analyst / player requests carry `team_id` and are scoped against owned or permitted team data.

### Team Management UI and Access Control

- Added `TeamManagementPage` and frontend API helpers for listing, creating, and updating teams.
- Extended user management so admin workflows can assign users to teams by ID, while non-admin views remain scoped to their own team boundary.
- Updated match creation and match list flows to carry owner team information and preserve team-aware filtering.
- Improved the audit log UI with richer filtering / presentation for team-scoped security events.
- Added team-scoping regression tests covering match access boundaries, user creation rules, and database bootstrap behavior.

### Validation Notes

- Added Phase B validation documents under `docs/validation/` for the team-scoping rollout, frontend follow-up, and remaining production hardening notes.
- Verified the focused backend auth/team test set and frontend Vitest suite during the rollout. Full backend pytest remains heavier than the normal local loop and was handled with targeted verification.

### Attack-Driven Hardening

- Ran several days of adversarial validation against authentication, team boundaries, player access, condition records, sharing endpoints, and warm-up observation flows.
- Converted the findings into source-level hardening and high-level validation notes rather than publishing replayable cases.
- Kept public notes intentionally high-level: the changelog records the security posture improvement and tested areas, while exploit mechanics, payload details, and replayable attack paths are omitted.

## 2026-04-25

### Live Adversarial Validation and Auth Hardening

- Spent the day validating authentication, MFA, refresh, local-login, operator-only, and lockout behavior under hostile conditions.
- Hardened auth and match input checks, tightened lockout enforcement across token refresh and MFA paths, and blocked role/scope confusion in local and development-only flows.
- Required stronger operator or admin proof for sensitive select, seed, and legacy paths so local-only endpoints do not rely on network placement as their main defense.

### Scope and Boundary Enforcement

- Enforced team, player, condition, annotation, sharing, and match scope more consistently across read and write paths.
- Tightened coach, analyst, player, and admin boundaries so cross-team access fails closed instead of depending on caller-provided identifiers.
- Added guardrails against invalid identifiers, oversized values, integer edge cases, unsafe package/import behavior, and sync/upload/export misuse.

### Regression and Merge Follow-Through

- Converted validated issue classes into defensive source changes and focused regression coverage while keeping replayable mechanics out of the public changelog.
- Merged and reconciled the hardening branches into `main`, accounting for places where the same underlying risk had been fixed by more than one implementation path.
- Updated repository guidance so future work stays aligned with PostgreSQL-backed production assumptions rather than local SQLite shortcuts.

## 2026-04-24

### Production Access and Code Scanning Hardening

- Reworked public and production gates around documentation, stack traces, cluster/control-plane routes, DB maintenance, network diagnostics, settings, tunnel, and admin-only operations.
- Addressed high-priority code scanning findings in SSH/remote task handling, temporary file creation, upload path handling, and URL/path validation.
- Added stronger access checks around sensitive local and control-plane paths while preserving the local development workflow.

### Input Validation and Data Integrity

- Tightened request schemas across auth, matches, players, comments/bookmarks, conditions, pipeline jobs, settings updates, sync/import/export, and sharing endpoints.
- Added stricter URL/path normalization, UTF-8 package filename support, safer browser/video download path handling, and clearer rejection of malformed payloads.
- Centralized ORM update safety so unknown or null writes cannot silently overwrite protected fields.
- Added audit logging and bounded request behavior for condition, webhook, pipeline, and public inquiry flows.

### Cluster, Upload, and Benchmark Readiness

- Added browser chunked video upload support.
- Added admin cluster controls, deployment scripts, benchmark resilience improvements, and i18n script updates.
- Cleaned up cluster configuration comments and kept the deployment/benchmark notes closer to the current architecture.

## 2026-04-23

### Phase B Authentication and Auth UI

- Token rotation with reuse detection, idle auto-logout, self-service password change, admin-driven reset, and an admin audit-log surface in the frontend.

### Router Unit Test Coverage

- Added unit tests for the maintenance-side routers (~20 cases) using TestClient against the same dependency-injected paths the running app uses.

### Test Stabilisation

- Fixed several import-order and singleton-capture issues that were causing test pollution under in-memory DB mode. Result: full backend pytest run is green on both CI runners.

### Dependency Upgrades

- Bumped Python dependencies to clear known advisories. Two Ray-side advisories that have no fixed release are scoped to trusted-network operation and tracked in the project's internal security log.

### i18n Migration

- Migrated remaining hardcoded Japanese strings across several major pages into the translation tree.

### Code Scanning Triage and Supply-Chain Hardening

- Triaged the static-analysis backlog with explicit rationale for each disposition, pinned every workflow `uses:` reference to a commit SHA across all eleven CI workflows, and reduced workflow token permissions to the minimum required.

## 2026-04-22

### Code Scanning Response

- Closed the Critical and High alerts surfaced by the static analysis sweep through additional input validation and path-safety checks across the API and the desktop renderer. Specific vulnerability classes and the corresponding remediations are tracked in the project's internal security log.

### CI Recovery

- Resolved the conflict between two overlapping code-scanning configurations and tightened workflow token permissions across the security-scanning workflows.

## 2026-04-21

### Public Landing Site v7

- Replaced the shuttle-scope.com top page with a full v7 design.
  New layout includes a fixed navigation bar with hamburger menu (mobile), a dark-navy hero section with an app mock panel, a three-column feature card row, a 2×2 analysis capabilities grid, a data policy section, a footer CTA, and a mobile sticky bottom bar.
- Added light / dark theme toggle via CSS custom properties persisted in localStorage.
- Added scroll-reveal animations using IntersectionObserver.
- Fixed all login / "アプリへ進む" link targets to `https://app.shuttle-scope.com/login`.
  Previously these pointed to the app root; they now go directly to the login screen.
- Preview route `/public-preview` continues to use link rewriting so internal development previews stay self-contained without affecting real login flow.

### Permission Scope Enforcement

- Role-scoped user management surfaces (admin / analyst / coach / player each see only what they should), match-result inversion so practice-match wins / losses are shown from the viewer's own perspective, and authentication added to the data export / import endpoints.

### Condition Analytics Role Restrictions Removed

- Removed the condition-analytics analyst-only gate that was blocking coach-role access to condition views.
  Coaches now receive the same condition analytics responses as analysts; player-facing restrictions remain in place.

### Admin Notification Inbox

- Added `NotificationInboxPage` so admin users can review inquiry submissions sent through the public contact form.
- Added backend coverage for the public-site test suite (`test_public_site`).

## 2026-04-20

### Admin Bootstrap Security

- Removed the previously checked-in default bootstrap-admin password and replaced it with environment-driven first-run provisioning. Added a bootstrap-status path so the login screen can indicate readiness without exposing any secret value.

### Auth Flow Hardening and Session Cleanup

- Removed the prototype-era client-side role switcher, moved auth-context persistence to session storage so a closed app returns to the login screen, added explicit logout actions, and added a startup revalidation step that re-syncs the displayed identity with the server.

### CI Stabilization and Benchmark Test Reliability

- Fixed CI installation failures by removing the assumption that `onnxruntime-gpu` is available in the base backend requirements on generic GitHub Actions runners.
- Reframed GPU ONNX Runtime as an environment-specific add-on, installed through machine setup scripts or targeted prep rather than forced into every CI or worker environment.
- Fixed benchmark test regressions so explicit mock mode is now respected during test execution instead of being silently disabled inside the runner.
- Aligned pipeline mock loading with the benchmark and smoke-test path, which removed false failures caused by real `ffmpeg` / runtime expectations in CI.

### Validation

- Verified the CI repair with a green GitHub Actions run on both `ubuntu-latest` and `windows-latest`.
- Re-ran local backend verification after the fixes:
  - backend tests: `624 passed, 4 skipped`
  - frontend tests: `84 passed`
  - production build: `npm run build` successful

### Detailed Progress

- Removed frontend `setRole`-based role mutation and the Settings role picker path.
- Moved token and auth-context persistence to session storage.
- Added explicit logout controls in the sidebar and account section.
- Added frontend auth revalidation using `/auth/me` before rendering protected routes.
- Returned `team_name` from backend auth login / me responses.
- Removed mandatory `onnxruntime-gpu` from generic backend dependency install flow.
- Updated benchmark runner behavior around tiny latency metrics and unavailable non-CPU devices.
- Preserved explicit `SS_CV_MOCK=1` behavior in benchmark execution.
- Updated video pipeline mock resolution so real mock implementations are used when available.

## 2026-04-19

### Cluster Routing and Remote Task Expansion

- Added Ray remote task support for distributed inference and analysis execution so GPU-heavy and CPU-heavy stages can now be routed more intentionally across machines.
- Expanded cluster bootstrap and topology handling so ShuttleScope can manage primary / worker behavior, remote task routing, and worker visibility with less manual editing.
- Strengthened the cluster settings surface so operators can inspect worker status, choose routing preferences, and tune load limits from the app rather than relying only on scripts.

### Benchmarking and Device Selection

- Expanded benchmark device detection across CPU, GPU, OpenVINO-capable paths, and Ray-aware environments.
- Added richer benchmark runner behavior including cancellation, backend overrides, YOLO as a benchmark target, and result handling better suited to mixed-device experiments.
- Raised the cluster inference concurrency limit and tuned benchmark / inference flow so experimentation on stronger local hardware is less artificially constrained.

### Worker Setup and Windows Operations

- Added `requirements_worker.txt` and `scripts/setup_k10_worker.ps1` so a second Windows machine can be prepared as a Ray worker with a narrower dependency surface than the full primary machine.
- Added and extended `scripts/fix_ray_firewall.ps1` to reduce the amount of manual Windows networking work needed to get distributed execution unstuck.
- Improved cluster worker setup details in `cluster.config.yaml`, backend bootstrap, and the Settings UI so practical worker onboarding is closer to a repeatable workflow.

### Model and Runtime Readiness

- Added a checked-in `backend/models/yolov8n.onnx` baseline asset so current YOLO-oriented flows have a default ONNX model available in-repo.
- Improved TrackNet inference fallback and backend selection behavior so OpenVINO / CPU / mock routes behave more predictably in mixed environments.

### Detailed Progress

- Added `backend/cluster/remote_tasks.py` and expanded cluster bootstrap / routing logic.
- Improved benchmark runner controls, target selection, backend override behavior, and cancellation support.
- Added YOLO benchmark target and corresponding frontend selector support.
- Added worker-specific requirements and a K10 worker setup script.
- Extended `ClusterSettingsPanel`, `SettingsPage`, and related i18n for cluster operations.
- Added `yolov8n.onnx` and refined TrackNet / benchmark integration behavior.

## 2026-04-18

### Role-Aware Local Authentication

- Added a proper local authentication surface instead of relying primarily on frontend role selection.
- Added backend auth routing for login, logout, current-user lookup, and role-specific login candidate lists.
- Added JWT utility handling and updated frontend auth state so the app now carries a signed backend-issued auth context rather than only local role headers.
- Added a dedicated `Login` page with role-specific flows for admin, analyst, coach, and player access.

### User and Access Management

- Added a `User Management` page so internal operators can manage role-bound local users instead of treating access as a purely implicit development concern.
- Extended the backend user model to support stronger role-linked account handling, including player-linked users and hashed credentials.
- Added access-log groundwork around auth actions so login and logout activity now has a backend audit trail.

### Protected Condition Views

- Tightened condition-data access so role-aware views expose different levels of detail instead of treating all readers as equivalent.
- Added field-sensitivity helpers and updated condition routing so coach / analyst access can be constrained to safer summaries while player self-view and privileged access remain distinct.
- Updated condition-related frontend screens and supporting hooks so the UI behaves correctly under the new protected-data responses rather than assuming unrestricted payloads.

### Prediction and Condition UX Alignment

- Updated prediction and condition pages, plus several analysis cards, so they degrade more safely when sensitive fields are unavailable under the current role.
- Refined frontend copy and i18n strings to match the new auth and protected-condition behavior.

### Validation

- Verified the auth and protected-condition update with:
  - backend tests: `624 passed, 4 skipped`
  - frontend tests: `84 passed`
  - production build: `npm run build` successful

### Detailed Progress

- Added backend auth router and JWT helpers.
- Added access-log and field-sensitivity utilities.
- Updated backend auth extraction and main app wiring.
- Tightened condition endpoint filtering.
- Added login and user-management pages.
- Updated frontend auth hook and API client to use backend-issued auth state.
- Refined prediction and condition views for role-aware payload differences.

## 2026-04-17

### Video Window Rendering Quality (Secondary Monitor)

- Fixed canvas overlay blur on high-DPI secondary monitors in the video extension window.
  `PlayerPositionOverlay` and `ShuttleTrackOverlay` were setting `canvas.width` / `canvas.height` to CSS logical pixels, causing the browser to upscale the canvas by `devicePixelRatio` and producing visibly blurred YOLO bounding boxes, shuttle trail dots, and label text.
  Both components now set canvas physical dimensions to `videoWidth ﾃ・dpr` / `videoHeight ﾃ・dpr`, apply `ctx.scale(dpr, dpr)` to keep drawing coordinates in logical pixels, and remove the `width` / `height` JSX attributes so sizing is managed entirely in the effect.
  On a 4K external monitor (`dpr = 2.0`), canvas resolution doubles from 1920 ﾃ・1080 to 3840 ﾃ・2160 physical pixels, utilizing the display's full native resolution while the main 1080p window remains unaffected.

### Multi-Monitor Selection UI

- Added monitor selection support for the secondary video window when three or more displays are connected.
  Previously `handleOpenVideoWindow` always picked the first non-primary display automatically, making it impossible to choose the target on a desktop with multiple external monitors.
  The fix adds a `selectedDisplayId` state (initialized from `getDisplays()` to the first non-primary monitor) and a `<select>` dropdown that appears only when two or more non-primary displays are detected.
  Single-monitor laptop setups (one external display) see no UI change; the dropdown only surfaces when a choice is meaningful.
  The `openVideoWindow` call now routes to the user-selected display ID, with a fallback to the first non-primary if the state is uninitialised.

### GPU Inference Backend 窶・Missing Pieces Completed (RTX 5060 Ti Preparation)

- Added `backend/cv/tracknet_openvino.py`: OpenVINO backend wrapper that adapts `tracknet/inference.py`'s `TrackNetInference` to the `TrackNetInferencer` Protocol.
  Implements chunked frame processing (300-frame chunks with a 2-frame overlap) so 30-minute match videos are not loaded entirely into RAM before inference starts.
  Frame indices are accumulated with a global offset to produce correct absolute timestamps across chunk boundaries.
- Extended `backend/cv/factory.py` with an OpenVINO intermediate tier.
  The new priority order is: Mock 竊・CUDA (torch + RTX) 竊・OpenVINO (iGPU / CPU, also works on K10) 竊・CPU (classical CV) 竊・Mock.
  Previously the OpenVINO inference path in `tracknet/inference.py` was entirely disconnected from the factory used by the pipeline.
- Added `backend/cv/tracknet_runner.py` and `backend/cv/mediapipe_runner.py`: thin runner modules that `cluster/tasks.py` was already referencing via `_safe_call` but which did not exist.
  Each module calls `factory.get_tracknet()` / `factory.get_pose()`, runs inference, and returns a status dict; the factory handles backend selection transparently so the same runner works on X1 AI (CUDA path) and K10 (CPU / OpenVINO path).
- Added `backend/pipeline/clips.py`: ffmpeg-based rally clip extractor.
  Detects `h264_nvenc` availability at first call and caches the result; uses NVENC when `SS_USE_GPU=1` and NVENC is present, falls back to `libx264` otherwise.
  K10 workers receive the CPU encode path automatically since `SS_USE_GPU=0` on that node.
- Added `backend/pipeline/statistics.py`, `backend/pipeline/cog.py`, and `backend/pipeline/shot_classifier.py`: lightweight K10-targeted entry points for statistics aggregation, centre-of-gravity calculation, and shot classification.
  Each delegates to the relevant `backend/cv/` implementation and returns `{"status": "skipped"}` gracefully when the underlying API is not yet implemented, preventing Ray task failures from aborting the full pipeline.
- Updated `backend/requirements.txt`: added `mediapipe>=0.10.14` and `pynvml>=11.4` as explicit entries so they are present in all environments rather than only after running the GPU setup script manually.
- Updated `scripts/setup_gpu.ps1` and `scripts/setup_gpu.sh`: both scripts now auto-download `pose_landmarker_lite.task` to `backend/cv/models/` after the pip installs, removing the manual download step that was previously required before `CudaPose` could initialise.
  The shell script uses `curl` with a `wget` fallback and prints a clear warning rather than failing hard if neither tool is available.

### Test Coverage Additions

- Added six test cases to `backend/tests/test_cv_factory.py` covering: `OpenVINOTrackNet` raising `ImportError` without openvino installed; the factory falling through to CPU / Mock when OpenVINO weights are absent; `tracknet_runner` / `mediapipe_runner` importability and callability; `pipeline/clips`, `statistics`, `cog`, `shot_classifier` importability; `extract_clips` returning `skipped` on `rally_bounds=None`; and `run_tracknet` not raising on a non-existent video path.
  All 11 active tests pass; 2 are correctly skipped when the relevant package (torch / openvino) is already installed.

### Detailed Progress

- Fixed Canvas DPI scaling in PlayerPositionOverlay and ShuttleTrackOverlay for high-DPI secondary monitors.
- Added multi-monitor selection dropdown to video extension UI (shown only with 2+ non-primary displays).
- Added tracknet_openvino.py with chunked frame processing and connected it to factory.py.
- Extended factory.py with CUDA 竊・OpenVINO 竊・CPU 竊・Mock priority chain.
- Added tracknet_runner.py and mediapipe_runner.py to complete the cluster/tasks.py call chain.
- Added pipeline/clips.py with automatic NVENC / libx264 selection.
- Added pipeline/statistics.py, cog.py, and shot_classifier.py as K10-targeted pipeline stubs.
- Updated requirements.txt with mediapipe and pynvml.
- Added MediaPipe model auto-download to setup_gpu.ps1 and setup_gpu.sh.
- Added six test cases to test_cv_factory.py covering new factory paths and module importability.

## 2026-04-16

### Analysis Bundles and Shared Data Flow
- Added analysis bundle foundations so review- and research-oriented screens can share a coordinated backend data layer instead of repeatedly pulling many small endpoints independently.
- Added response-cache groundwork, bundle parity verification scripts, and profiling scripts so performance work is now supported by explicit tooling rather than guesswork alone.
- Added shared review / research bundle contexts on the frontend so larger dashboard and review surfaces can be composed from a more stable data contract.
- Hardened Markov and research analytics persistence / interaction behavior while keeping the larger backend test suite green.

### Condition Tracking Platform
- Added a full condition tracking and analytics workflow, moving condition data from a side concept into a first-class product area.
- Added questionnaire handling, scoring, condition-specific analytics, and condition seeding utilities so the feature can be exercised on realistic internal data.
- Expanded the condition area with tagging, trend charts, volatility ranking, seasonality, PCA scatter, generic scatter, lag correlation, outlier week detection, tag comparison, post-match change views, and history detail flows.
- Added condition tag APIs and frontend tag-management views so condition analysis can now be organized and compared rather than treated as a flat list of entries.

### Expert Labeler and Secure Sync
- Added an expert labeler workflow with dedicated pages and backend routing so specialist labeling can sit alongside the main annotation workflow instead of living only in planning notes.
- Added clip-generation service groundwork to support the expert labeler flow.
- Strengthened package export / import and sync flows with more explicit auth-aware handling, moving cross-device package movement toward a safer internal workflow.

### Validation and Stability
- Continued the pattern of running build and full backend verification before large commits, keeping the codebase in a shippable internal state even while major features were landing.
- Preserved green backend coverage while introducing large new surfaces in conditions, expert labeling, bundles, and secure sync.
- Added benchmark-device and benchmark-runner test coverage so the new infrastructure-facing surfaces are not landing without backend guardrails.

### Device Benchmarking and DB Maintenance
- Added a benchmark execution foundation with device probing, synthetic benchmark targets, async job tracking, and a dedicated backend API for measuring available compute backends.
- Added a benchmark UI in Settings with device selection, target selection, progress polling, and result matrices so operator machines can be characterized inside ShuttleScope rather than only through ad hoc scripts.
- Added SQLite maintenance APIs and Settings controls for DB status, WAL / freelist visibility, incremental vacuum execution, and auto-vacuum mode changes.
- Moved the SQLite bootstrap path toward `auto_vacuum=INCREMENTAL` and added maintenance-aware database utilities, which addresses the real file-bloat pattern caused by repeated write/delete cycles.

### Analysis Reliability and Presentation
- Fixed condition growth insight payloads so growth-oriented cards now match the frontend contract more closely instead of relying on partially mismatched field names.
- Hardened bundled research-card rendering by guarding against non-array payload shapes in EPV and state-action views.
- Improved confidence-badge handling so missing or malformed sample counts degrade safely instead of producing misleading or broken UI states.
- Tightened cluster bootstrap test coverage so missing-Ray behavior and other bootstrap edge cases fail more explicitly during test runs.

### Fast Review and In-Game Coach Support
- Added RallyClipNavigator so analysts can jump directly to rally segments by video timestamp rather than scrubbing through raw footage.
  The navigator uses the `localfile://` protocol for desktop local video access and ties clip boundaries to annotated rally records, turning annotation data into a navigation layer over existing video.
- Added QuickSummaryCard with five rule-based coaching signals (momentum shift, serve pattern, unforced error rate, return pressure, fatigue indicator) targeted at between-set intervals.
  Cards are intentionally rule-based rather than model-driven so they surface reliably even when sample sizes are small enough to make statistical inference unreliable.
  Growth-oriented framing is preserved throughout 窶・no direct weakness labels appear in any card.

### Data Asset Packaging
- Added a JSON data package export / import workflow that bundles a match together with its linked players, sets, rallies, and strokes into a single portable file.
  The workflow is auth-aware and handles cross-device package movement through the existing secure sync infrastructure, making it practical to carry a finished match dataset from an annotation PC to an analysis machine without a shared DB.

### Multi-Camera Architecture (4-Camera Simultaneous)
- Extended the camera management model from a single-active constraint to a four-camera simultaneous limit.
  Removed the deactivate-all shortcut and replaced it with a handoff policy: when a fifth camera attempts to activate, the oldest active camera is handed off first, keeping at most four cameras live at any time.
  This matches real multi-court or multi-angle deployment scenarios without requiring operator coordination for every camera switch.
- Fixed a DeviceSelector text color regression where CPU usage text was rendering blue-on-blue (white text on white badge background), making CPU load invisible in the device panel.

### Distributed Tracking Foundation (Player Position Frames)
- Added the `PlayerPositionFrame` model (`player_position_frames` table) to the core schema.
  Stores per-frame positional data for all four court players (player_a, partner_a, player_b, partner_b) and the shuttle as float coordinates, keyed to match / set / rally and a frame counter.
  Indexed on (match_id, frame_num) for fast sequential playback reads and separately on rally_id for rally-scoped queries.
  This is the foundation for time-series player movement analysis, court pressure visualization, and future Ray-distributed tracking pipelines.
- Added Alembic migration `0007_player_position_frames` with an idempotent table-existence check, continuing the sequential migration chain at revision 0007.

### Cluster Infrastructure and Distributed Processing
- Designed and implemented a two-node cluster architecture targeting Minisforum X1 AI (primary) and GMKtec K10 (worker).
  Network topology: 2.5GbE direct Ethernet as the primary cluster link (192.168.100.0/24), USB-C RNDIS as a fallback link (192.168.101.0/24), WiFi for client access.
  USB-C is treated as fallback only 窶・the K10 does not have Thunderbolt, so USB networking tops out around 300窶・00 Mbps via RNDIS rather than full Thunderbolt speeds.
  Traffic budget analysis confirmed the 2.5GbE link is sufficient: ~50 Mbps for PostgreSQL WAL replication plus ~200 Mbps for four cameras at compressed JPEG frame rates leaves substantial headroom under the 2.5 Gbps physical limit.
- Added `cluster.config.yaml` as the user-facing cluster configuration file at the app root.
  Fields cover cluster mode (single / primary / worker), network interface assignment, Ray head address, PostgreSQL connection settings, camera inference limits, and per-node load thresholds.
  Designed to be understandable and editable by other users without code changes.
- Added `backend/cluster/topology.py`: cached YAML config loader with getters for mode, node identity, primary IP, workers list, Ray address, PG host, load limits, and inference config.
  Includes `list_interfaces()` (psutil-based network interface enumeration) and `ping_node()` (HTTP health check with latency measurement) so the UI can discover and verify cluster nodes.
- Added `backend/cluster/load_guard.py`: singleton `LoadGuard` with CPU (psutil), GPU (pynvml), and concurrent-task limits.
  Provides `can_accept()`, a `task_slot()` context manager for safe active-task counting, and `wait_until_available()` with configurable timeout.
  Limits are read from `cluster.config.yaml` so operators can tune thresholds without code changes.
- Added `backend/routers/cluster.py` with endpoints for cluster status, config read/write, interface listing, node ping, and live node status across all workers.
  Registered in `backend/main.py` under `/api`.
- Added `ClusterSettingsPanel` to the Settings UI: mode selector, node ID, network interface dropdowns (populated from `/api/cluster/interfaces`), worker list with per-worker ping test, load threshold sliders, live CPU/GPU gauge bars, Ray status badge, and a save button.
  Added the cluster tab to `SettingsPage` and wired all translation strings into `src/i18n/ja.json`.

### Windows Cluster Startup Scripts
- Added `scripts/cluster/start_primary.bat`: sequences PostgreSQL startup, Ray head node startup, a background health monitor, and the FastAPI server.
  Accepts `SS_CLUSTER_MODE`, `SS_RAY_PORT`, `SS_RAY_CPUS`, `SS_RAY_GPUS`, and `API_PORT` environment variables for flexible deployment.
- Added `scripts/cluster/start_worker.bat`: starts the PostgreSQL standby, connects the Ray worker to the head node at `SS_PRIMARY_IP`, and enters a 30-second reconnect loop to handle transient network interruptions during startup.
- Added `scripts/cluster/setup_routes.bat`: configures Windows routing tables for cluster and fallback subnets and sets interface metrics (cluster interface priority 10, fallback 100) so traffic naturally prefers the direct Ethernet link.
- Added `scripts/cluster/failover_promote.bat`: promotes the PostgreSQL standby to primary, starts a Ray head node on the worker machine, and updates `cluster.config.yaml` mode to `primary`, enabling the worker to operate as a fully autonomous primary if the original primary is lost.
- Added `scripts/cluster/pg_setup_primary.bat`: creates the `ss_user` database role, the `shuttlescope` database, and the `replicator` replication role, and configures PostgreSQL `wal_level`, `max_wal_senders`, `wal_keep_size`, and `listen_addresses` for streaming replication.
- Added `scripts/cluster/pg_setup_standby.bat`: runs `pg_basebackup` from the primary and starts the standby in hot-standby mode via `standby.signal`.

### SQLite 竊・PostgreSQL 18 Migration
- Migrated the operational database from SQLite to PostgreSQL 18.
  PostgreSQL 18 was installed via winget on the primary PC (`127.0.0.1:5432`, database `shuttlescope`, user `ss_user`).
  41,204 rows across 13 populated tables were migrated successfully (players 22, matches 62, sets 129, rallies 4,467, strokes 35,750, and supporting tables).
- Added `scripts/pg_migrate_sqlite.py` with dependency-ordered table migration, FK constraint bypass via `session_replication_role`, idempotent `ON CONFLICT DO NOTHING` inserts, post-migration sequence correction via `setval`, and Alembic head stamping.
  Key fix applied during migration: SQLite stores boolean columns as 0/1 integers, while PostgreSQL requires Python `True`/`False`.
  The script now pre-collects all boolean columns from the PostgreSQL schema via `pg_inspector` and converts values in each batch before insert, preventing the `DatatypeMismatch` error that would otherwise fail silently on partial rows.
- Updated `.env.development` to point `DATABASE_URL` at the PostgreSQL instance, with the previous SQLite URL commented out as a rollback reference.
- Updated `backend/requirements.txt` with organized sections covering core FastAPI / SQLAlchemy dependencies, PostgreSQL driver (`psycopg2-binary`), cluster utilities (`psutil`, `pyyaml`), and optional AI/reporting packages.

### CV Inference Architecture Foundation

- Added the CV inference factory (`backend/cv/factory.py`) as the single entry point for all CV backend selection.
  Priority chain: `SS_CV_MOCK=1` 竊・Mock, `SS_USE_GPU=1` 竊・CUDA, fallback 竊・CPU, final fallback 竊・Mock.
  All routers and pipeline code use only `get_tracknet()` / `get_pose()` so backend selection stays in one place.
- Added `CpuTrackNet` (`cv/tracknet_cpu.py`): classical CV shuttle detection using HSV color filter, MOG2 background subtraction, contour matching, and HoughCircles fallback.
  Missing frames are filled with linear interpolation so downstream consumers always receive a full-length sample list.
- Added `CudaTrackNet` (`cv/tracknet_cuda.py`): PyTorch / cv2.cuda structure ready for real TrackNet weights.
  Phase A delegates to `CpuTrackNet`; when actual `.pt` weights are placed and the TODO stub is completed, the GPU path activates automatically without touching the factory.
- Added `CudaPose` (`cv/pose_cuda.py`) and `CpuPose` (`cv/pose_cpu.py`): MediaPipe Pose inferencer pair.
  The CUDA variant uses MediaPipe Tasks GPU delegate; the CPU variant is the plain MediaPipe CPU path.
  Both satisfy the `PoseInferencer` Protocol so the factory can swap them without caller changes.
- Added `backend/tracknet/inference.py`: TrackNet inference wrapper with OpenVINO (GPU-preferred) 竊・ONNX Runtime CPU 竊・TensorFlow CPU priority chain.
  Loads real badminton-tuned TrackNet checkpoint weights and exposes `predict_frames(frames)` returning per-frame zone / coordinate / confidence dicts.
- Added `backend/yolo/inference.py`: YOLOv8 player detection wrapper with OpenVINO IR 竊・ultralytics PT 竊・custom ONNX CPU priority chain, per-frame court-side and depth-band assignment, and thread-safe locking for OpenVINO's stateful compiled model.
- Added Ray remote task structure (`backend/cluster/tasks.py`) with `_maybe_remote` decorator: GPU-intensive tasks (`run_tracknet`, `run_mediapipe`, `num_gpus=1`) target the X1 AI GPU node; CPU tasks (`extract_clips`, `run_statistics`, `calc_center_of_gravity`, `classify_shots`, `num_cpus=1`) target K10 worker nodes.
  Tasks degrade to synchronous execution when Ray is not initialized.
- Added `backend/cluster/pipeline.py`: orchestration layer that calls tasks in parallel stages (TrackNet + MediaPipe concurrently, then clips, then statistics / CoG / shots concurrently) using Ray when live or sequential fallback otherwise.
- Added `backend/pipeline/video_pipeline.py` and `backend/pipeline/jobs.py`: `run_pipeline()` and `execute_job()` coordinate full per-match analysis runs (TrackNet 竊・ShuttleTrack DB, Pose 竊・PoseFrame + CenterOfGravity DB, shot classification 竊・ShotInference DB), with `AnalysisJob` status tracking (running 竊・done / failed), error recording, and idempotent delete-before-insert.
- Added `backend/benchmark/devices.py`: compute device probe layer (`probe_all()`) covering CPU (psutil), NVIDIA GPU (pynvml), OpenVINO devices (iGPU / dGPU), ONNX Runtime CUDA EP, and Ray worker nodes.
  Results are cached for 60 seconds to avoid repeated probe overhead during dashboard polling.
- Added `scripts/setup_gpu.ps1` and `scripts/setup_gpu.sh`: GPU environment setup scripts that install PyTorch (CUDA 12.4 index), MediaPipe, and pynvml into the backend venv.

### Detailed Progress
- Refined research analytics interactions and Markov persistence.
- Added analysis bundles and response-cache foundation.
- Added condition tracking and analytics workflow.
- Expanded condition analysis and tagging workflows.
- Added expert labeler and secure package sync flow.
- Added CV inference factory, CpuTrackNet / CudaTrackNet, CpuPose / CudaPose, TrackNet inference wrapper, YOLO inference wrapper.
- Added Ray remote task definitions and cluster pipeline orchestrator.
- Added video pipeline, job tracking, and benchmark device probe layer.
- Added GPU setup scripts (Windows PowerShell and Linux shell).
- Added benchmark and DB maintenance workflows.
- Added RallyClipNavigator for timestamp-based video segment navigation.
- Added QuickSummaryCard with five rule-based between-set coaching signals.
- Added JSON match data package export and import workflow.
- Extended camera model to four simultaneous cameras with oldest-handoff policy.
- Fixed DeviceSelector CPU text color (blue-on-blue 竊・white).
- Added PlayerPositionFrame model and Alembic migration 0007.
- Designed two-node cluster topology (2.5GbE primary, USB-C fallback, WiFi clients).
- Added cluster.config.yaml, topology.py, load_guard.py, and cluster router.
- Added ClusterSettingsPanel to Settings UI with live gauges and config save.
- Added Windows cluster startup scripts (primary, worker, routes, failover, PG setup).
- Migrated 41,204 rows from SQLite to PostgreSQL 18 with boolean type fix.
- Updated .env.development and requirements.txt for PostgreSQL.

## 2026-04-15

### CV, Tracking, and Desktop Workflow
- Added realtime YOLO overlay groundwork so CV output can start surfacing during active desktop workflows rather than only after offline batch runs.
- Added ReID groundwork for player tracking, which begins to separate simple detection from actual player identity continuity.
- Improved player tracking overlays, movement-oriented analysis, CV result messaging, and fallback behavior around YOLO-driven flows.
- Added ROI-aware and desktop-oriented polish around capture / annotation workflows so CV work is more usable on real operator desktops.

### Auth and Settings
- Added local auth hardening and role-aware settings flow so local security and role behavior are less implicit.
- Added a role picker and auth-aware controls that connect settings behavior more clearly to the operator's current role.
- Refined auth-aware analysis panels and match/settings behavior so role differences start affecting more of the product in a visible way.

### Product Shape
- At this point ShuttleScope moved further toward a product with a real operator workflow: desktop capture, ROI setup, CV overlays, role-aware settings, and player-tracking foundations now connect more visibly.

### Detailed Progress
- Refined match linking and CV result messaging.
- Improved player tracking overlays and YOLO fallback flow.
- Added player movement analytics and ROI desktop polish.
- Hardened local auth and CV desktop workflows.
- Improved desktop capture overlays and YOLO controls.
- Polished CV job controls and YOLO annotator flow.
- Added ReID foundation for player tracking.
- Added role picker and auth-aware settings flow.
- Refined auth-aware analysis panels and match settings flow.

## 2026-04-14

### Prediction and Tactical Surfaces
- Improved prediction output so it reads more like an analyst-facing narrative and less like a raw probability panel.
- Added role-specific panels around prediction and pair-oriented analysis so the prediction area is easier to use for coach / analyst workflows.
- Expanded partner and lineup-related views to make pre-match and planning work more readable.

### CV Throughput and Analysis UX
- Extended CV analysis-rate options up to 60fps and added warnings around batch-processing cost so high-fidelity processing is possible without hiding the runtime tradeoff.
- Improved benchmark controls, resume behavior, ROI diff handling, and multiple dashboard / chart interaction details.
- Polished composite heatmaps, rally-detail modals, doubles display, and chart bugs that made detailed review surfaces harder to trust.

### Annotation and Match UX
- Improved inline confirmations, player-row consistency, silent-save handling, and match / player editing reliability.
- Continued reducing small-but-costly operator friction around lists, selectors, and save flows.

### Detailed Progress
- Fix chart bugs and add rally detail to score progression.
- Add CV analysis rate settings with benchmark UI, fix YOLO/TrackNet resume bug, add keyboard server select, and extend doubles support for warm-up notes and match list.
- Fix benchmark button text color for readability.
- Extend CV rate options to 60fps with batch processing time warning dialog.
- Improve composite heatmap interactivity, rally detail modal UX, and doubles annotation display.
- Polish UI with tooltips, sort, bulk select, and inline confirmations.
- Fix silent player update failure and apply `exclude_unset` to PUT handlers.
- Unify player row height and convert mobile delete behavior to inline confirmation.

## 2026-04-13

### Prematch, Resume, and ROI
- Added prematch prediction snapshots so prediction outputs can be stored in a more time-aware way instead of always behaving like a live recomputation.
- Added ROI-aware CV batch processing so selected regions actually flow through TrackNet / YOLO processing rather than staying as UI-only overlays.
- Added CV resume and ROI-diff workflows so interrupted or changed CV analysis runs can be resumed more intentionally.
- Improved court-grid / ROI editing and restoration behavior around annotator video workflows.

### Desktop Capture and Annotation Support
- Added ROI rectangle overlays and desktop-capture support that better match real operator use on Windows.
- Strengthened video-pane and annotator integration so video-region capture and CV analysis can sit inside the normal annotation flow more naturally.

### Test and CI Guardrails
- Fixed CI failures around websocket signaling by ensuring the test harness consistently creates the newer session-related tables and uses the patched test session factory.
- Added dedicated guardrail tests so similar signaling / SessionLocal regressions are more likely to fail fast in CI.

### Detailed Progress
- Add prematch snapshots and CV resume ROI workflows.
- Add player tracking overlay controls.
- Improve match edit validation feedback and static MIME mapping.
- Add ROI-aware CV batch processing.
- Improve prediction narrative and role-specific panels.
- Stabilize websocket signaling tests in CI.
- Add CI guardrails for websocket test harness.

## 2026-04-12

### Product and UX
- Expanded the top-level product documentation so the repository now explains ShuttleScope in a more grounded, current-state way.
- Added a proper root `CHANGELOG.md` so progress is visible from the repository top level.
- Polished dashboard selectors and theme controls, including better mobile-safe selectors, same-page navigation, and overview / advanced page usability.
- Improved responsive behavior across dashboard surfaces and heatmap-related views.

### Annotation and Match Workflow
- Improved match edit validation feedback and safer save behavior.
- Fixed server-state handling during rally confirmation so saved annotation state is less likely to drift from UI state.
- Improved LAN same-device access flow so sharing links behave more reliably when the same machine is both operator and consumer.

### Heatmaps and Responsive UI
- Added heatmap composite support and corresponding backend / frontend integration.
- Tightened responsive UI behavior across overview, advanced, settings, top navigation, section navigation, and several analysis cards.
- Added dedicated backend heatmap composite tests and updated UI behaviors so complex analysis views survive narrower layouts better.

### Security and Hardening
- Responded to a dedicated security review pass with concrete backend hardening.
- Restricted `localfile://` handling more aggressively.
- Added upload / body-size limits and safer request handling around file-oriented endpoints.
- Hardened sync import / copy paths against oversized input and path traversal.
- Added active-session and participant validation in camera WebSocket signaling.
- Added operator-token protection for sensitive remote session management flows.
- Switched session code generation from non-cryptographic random generation to a CSPRNG-based approach.

### Validation and Test Health
- Updated websocket signaling tests so they reflect the newer active-session requirements instead of silently depending on older assumptions.
- Kept the full test suite green while expanding responsive / security coverage.

### Detailed Progress
- Improved match edit validation feedback and static MIME mapping.
- Improved LAN same-device access and documented current product status more honestly.
- Improved responsive UI and heatmap composite views.
- Hardened remote session security and fixed annotation server state handling.
- Polished dashboard selectors and theme controls.

## 2026-04-11

### Post-Match Video and CV Pipeline
- Added a post-match local video import flow that moves ShuttleScope closer to a realistic "analyze after recording" workflow.
- Added `Video Only` / second-screen foundation so playback can continue while annotation happens elsewhere.
- Added court calibration foundation and then hardened it so backend persistence and restore behavior are more reliable.
- Improved CV ROI mapping and court-aware handling so downstream CV artifacts can use court geometry more safely.
- Added automation and validation scaffolding around court calibration and CV artifacts.

### Match and Player Management
- Added match editing after creation, including safer handling of referenced players.
- Prevented player deletion when matches still reference that player.
- Hardened match edit payload handling so empty optional values stop causing avoidable failures.
- Added player team history support and migration so roster changes can be tracked more realistically over time.

### Validation and Non-Human Checks
- Added more non-human validation coverage around calibration, artifacts, bootstrap behavior, and match edit safety.
- Tightened bootstrap and migration tests so DB evolution remains safer as the schema grows.

### Detailed Progress
- Added post-match video import and multi-monitor foundation.
- Refined court calibration persistence and CV ROI mapping.
- Closed calibration automation gaps and CV artifact hardening.
- Added match editing and referenced-player safeguards.
- Hardened match edit payload handling and save errors.
- Added player team history support and migration.
- Ignored local CV weights and kernel diagnostics so repository status stays clean.

## 2026-04-10

### YOLO / TrackNet / CV-Assisted Annotation
- Added YOLO player detection and CV alignment foundation.
- Added shuttle overlay and a dashboard CV position card so computer vision results start to surface in both annotation and dashboard flows.
- Polished YOLO-driven role signals and annotator-side CV controls.
- Improved YOLO diagnostics and artifact-status visibility so missing setup / problems are easier to diagnose.
- Added CV-assisted annotation candidates, candidate badges, and review queue groundwork.
- Started moving from "CV exists" to "CV suggests actual annotation actions" by introducing candidate application flows and review handling.

### Remote and CV Failure Handling
- Recorded and responded to critical remote / CV failures as validation findings rather than hiding them behind optimistic assumptions.
- Fixed remote share rebasing problems and made CV errors much more visible.
- Improved tunnel / ngrok hardening so remote sharing state is more explicit.

### Bootstrap and No-Video Work
- Used the no-video window productively by strengthening CV assist UX, review queue flow, and environment / bootstrap tooling.
- Added and improved bootstrap helpers and setup doctor output so the project is easier to bring up on additional devices without guesswork.

### Detailed Progress
- Added YOLO player detection and CV alignment foundation.
- Added shuttle overlay and dashboard CV position card.
- Polished YOLO role signal and annotator CV controls.
- Improved YOLO diagnostics and artifact status UX.
- Added foundation registry split and recorded critical remote CV failures.
- Fixed remote share rebasing and CV error diagnostics.
- Added CV-assisted annotation candidates and ngrok URL hardening.
- Polished no-video CV assist flow and device bootstrap.
- Improved device bootstrap guidance and doctor output.

## 2026-04-09

### Dashboard Rearchitecture
- Rebuilt the dashboard from a single large page into a structured shell with separate overview, live, review, growth, advanced, and research areas.
- Added top-level and section-level navigation patterns that make the dashboard feel more like a product surface than a page of stacked charts.
- Added evidence and research status presentation patterns so more experimental modules are visibly different from mature ones.

### Research Spine and Advanced Analysis
- Added the dashboard research spine and metadata / evidence groundwork.
- Added research cards and meta integration so state-value, counterfactual, hazard / fatigue, and related work has a stable home.
- Added promotion workflow and advanced-meta rollout so research outputs can be tracked as candidates for broader adoption.
- Completed promotion gaps and extended the color / theming system across more dashboard surfaces.
- Added audit log and theme fixes around promotion overrides.
- Hardened opponent policy refresh and error-state handling.

### Dashboard and Analysis UX
- Added date slider v2 and zone-map modal workflows.
- Fixed heatmap filtering and crash-handling issues.
- Applied theme / card rules consistently across advanced and research surfaces.

### Remote Camera and Live Collaboration
- Added remote tunnel providers and initial WebRTC / TURN settings support.
- Hardened remote diagnostics and stale camera cleanup behavior.
- Added TURN diagnostics and reconnect hardening.
- Added a remote viewer page and improved sender reconnect behavior.
- Polished remote handoff flow and grouped viewer UX.
- Added tunnel-provider visibility to the annotator remote health banner.

### Documentation and Positioning
- Rewrote the README around the practical PoC / current product scope rather than over-claiming future work.

### Detailed Progress
- Improved LAN access troubleshooting and sharing UX.
- Polished camera sender UX and live overlay behavior.
- Clarified README for current PoC scope.
- Fixed dashboard heatmap filters and crash handling.
- Rebuilt dashboard structure and routing.
- Added research spine and evidence metadata.
- Completed research cards and metadata integration.
- Added promotion workflow and advanced-meta rollout.
- Applied card theme rules to dashboard research and advanced views.
- Completed promotion gaps and color rollout.
- Added promotion audit log and live theme fixes.
- Hardened opponent policy card refresh and error states.
- Added date slider v2 and zone-map modal workflows.
- Added remote tunnel providers and WebRTC TURN settings.
- Hardened remote device diagnostics and stale camera cleanup.
- Added TURN diagnostics and receiver reconnect hardening.
- Added remote viewer page and sender visibility reconnect.
- Polished remote handoff flow and grouped viewer UX.
- Showed tunnel provider in annotator remote health banner.
- Added ngrok authtoken support and ignored local env files.

## 2026-04-08

### Analysis Architecture and Search UX
- Unified analysis foundations and player context so the later advanced / research stack had a cleaner base.
- Split analysis routers into stable, advanced, and research layers.
- Added stage 2 engines, then stage 3 research engines for counterfactual and EPV-oriented work.
- Added searchable selects and date-range filtering across important UI paths.

### Sync, DB, and Migration Foundation
- Added sync architecture phase 1 data-management support.
- Strengthened sync metadata and data-management flows after the first pass.
- Closed major DB sync gaps and added analytics indexes.
- Added Alembic migrations and the dominant-hand schema fix.
- Hardened DB bootstrap behavior and several DB-adjacent edge cases.

### Annotation and Review Acceleration
- Added annotation modes and a review-acceleration flow.
- Improved mobile UX and quick-start route behavior.

### LAN, Session, and Live Source Work
- Added LAN session auth and device-control flow.
- Added live source control and the first LAN inference foundation.
- Expanded single-PC validation coverage for the LAN live stack.
- Fixed LAN join flow and multiple device-manager UX issues.

### Detailed Progress
- Unified analysis foundations and player context.
- Split analysis routers and added stage 2 engines.
- Added stage 3 research engines for counterfactual and EPV.
- Polished mobile UX and fixed quick-start route issues.
- Added searchable selects and date-range filters.
- Added sync architecture phase 1 data management.
- Strengthened sync metadata and data management flows.
- Closed remaining DB sync gaps and added analytics indexes.
- Added Alembic migrations and dominant-hand schema fix.
- Hardened DB bootstrap and heatmap error handling.
- Added annotation modes and review acceleration flow.
- Added LAN session auth and device control flow.
- Added live source control and LAN inference foundation.
- Added single-PC validation coverage for the LAN live stack.
- Fixed LAN join flow and device-manager UX issues.

## 2026-04-07

### Annotation Workflow
- Refined the annotation keymap and rally-end flow so basic annotation became faster and less error-prone.
- Added a dedicated doubles hitter flow.
- Improved end-state handling and match-setup ergonomics.

### Analytics and Research
- Implemented research roadmap analytics modules.
- Added warm-up observations and related analytics context.
- Closed major remaining gaps with tests, seed data, and CI.
- Added heatmap modal and warm-up analytics fixes.

### Prediction
- Added the first prediction tab and pair-simulation foundation.
- Refined the prediction tab toward coach / analyst workflows.
- Added analyst-depth and human-benchmark oriented prediction features.

### Sharing and Access
- Added LAN and tunnel web-access support.

### Documentation
- Refreshed the README multiple times to keep it closer to reality as scope expanded.

### Detailed Progress
- Refined annotation keymap and rally-end flow.
- Refreshed the top-level README.
- Polished annotation flow end-state handling.
- Implemented research roadmap analytics modules.
- Added warm-up observations and detail analytics context.
- Closed remaining gaps with tests, seed data, and CI.
- Added heatmap modal and warm-up analytics fixes.
- Added prediction tab and pair-simulation foundation.
- Refined prediction tab for coach and analyst workflows.
- Added doubles annotation hitter flow.
- Added LAN and tunnel web-access support.
- Refreshed README for current product scope.
- Clarified README for PoC scope.
- Upgraded prediction with analyst depth and human benchmarks.

## 2026-04-06

### Streaming and Video Handling
- Added DRM-capable streaming playback and download tests.
- Improved ffmpeg fallback behavior and cookie-download guidance.
- Added a streaming download workflow and hardened the related UI.

### Annotation and Match-Day Flow
- Adapted the shot panel to rally context.
- Refined shot-key pause behavior.
- Added a match-day workflow and set-summary behavior.
- Improved desktop startup and quick-start flows.
- Improved annotation flow and interval handling.
- Completed a broad annotation / desktop workflow phase.
- Added TrackNet automation and settings sync.
- Implemented stage 1 sharing and live collaboration.

### Analytics
- Polished dashboard analytics access and labels.
- Implemented advanced analytics and reports.
- Enhanced EPV bootstrap and scouting reports.
- Refined analytics visuals and doubles dashboard.
- Added filter-aware analytics and related support.

### UX and Visual System
- Unified color-system rules and refreshed docs.
- Implemented the light-theme color spec.
- Polished analytics light theme and midgame review.

### Detailed Progress
- Added DRM-capable streaming playback and download tests.
- Improved ffmpeg fallback and cookie download guidance.
- Adapted shot panel to rally context.
- Refined shot key pause behavior.
- Polished dashboard analytics access and labels.
- Implemented advanced analytics and reports.
- Enhanced EPV bootstrap and scouting reports.
- Refined analytics visuals and doubles dashboard.
- Aligned private docs and validation layout.
- Unified color system and refreshed docs.
- Added filter-aware analytics and license documents.
- Polished light theme readability and match round labels.
- Implemented match day workflow and set summary.
- Improved desktop startup flow.
- Added quick start workflow and hardened desktop launch.
- Improved annotation flow and interval handling.
- Completed P1 / P2 / P4 annotation and desktop workflow.
- Added TrackNet automation and settings sync.
- Implemented stage 1 sharing and live collaboration.
- Implemented color spec v1 light theme rules.
- Polished analytics light theme and midgame review.
- Implemented analytics review phases 1 to 3.
- Improved annotator court flow and doubles sharing.
- Refined match setup and documented annotation flow.

## 2026-04-05

### Repository Setup
- Created the repository and initial ShuttleScope codebase.
- Added the repository-level Claude guidance file.
- Ignored local player / match database artifacts so local work would not pollute version control.

### First Substantial Feature Foundation
- Added an advanced analysis dashboard and support scripts very early in the repository lifetime, which set the tone for ShuttleScope as more than a minimal tagger.

### Detailed Progress
- Initial commit.
- Ignored local player and match databases.
- Added repository Claude guide.
- Added advanced analysis dashboard and support scripts.

## Notes

- This changelog is intentionally detailed because the project has been evolving quickly and the accumulated work matters.
- It is still higher-level than raw commit history; validation docs remain the best place for issue-specific detail.
- Local-only planning notes remain in `private_docs/` and are not committed.
