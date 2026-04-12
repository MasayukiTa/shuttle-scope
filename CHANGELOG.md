# Changelog

This changelog tracks notable product-level changes in ShuttleScope.
It is intentionally higher-level than commit history and should be read together with the README:

- `README.md` explains what ShuttleScope is and what is currently usable.
- `CHANGELOG.md` summarizes how the product has evolved over time.

ShuttleScope is still an internal, fast-moving project, so entries focus on meaningful workflow changes rather than every small fix.

## Unreleased

### Added
- Player team history support and migration groundwork.
- Match editing flow after creation.
- Court calibration persistence and backend-first restore behavior.
- Video import and second-screen `Video Only` foundation.
- CV-assisted annotation candidates, review queue, and overlay groundwork.
- YOLO player-position and TrackNet shuttle-track artifact pipeline.
- Device bootstrap helpers and setup doctor improvements.

### Changed
- Match and player management flows are safer around referenced entities.
- README now reflects current practical scope more honestly.
- Remote and browser-camera features are described as experimental rather than core.
- CV readiness checks and benchmark reporting are more explicit.

### Fixed
- Match edit payload handling for optional fields.
- Better error visibility during match edit save failures.
- Static MIME mapping for Windows environments where module scripts were not served correctly.
- TrackNet artifact consistency around video import and downstream consumers.

## 2026-04-11

### Added
- `team_history` support for players, including Alembic migration and Settings UI rendering.
- Match create/edit improvements, including team-aware setup and safer payload handling.
- Court calibration automated tests and benchmark acceptance criteria.
- Additional non-human validation scaffolding for setup, calibration, and CV artifact handling.

### Changed
- Player deletion now blocks when the player is still referenced by matches.
- Settings can redirect to filtered match list views when deletion is blocked by references.
- Match form and annotator-related setup became more resilient for internal operator workflows.

### Fixed
- Bootstrap tests updated to current migration head.
- Match edit validation error display improved.
- Backend MIME behavior on Windows now explicitly handles `.js`, `.mjs`, and `.css`.

## 2026-04-10

### Added
- CV-assisted annotation first implementation.
- Review queue and candidate badge flows.
- Device bootstrap scripts and setup doctor foundation.

### Changed
- Remote sharing and tunnel handling became more explicit and diagnosable.
- Internal bootstrap flow for new devices became much easier to reason about.

### Fixed
- Remote share rebasing and CV error visibility issues.
- Better diagnostics around TrackNet / YOLO environment readiness.

## 2026-04-09

### Added
- Dashboard rearchitecture into overview / live / review / growth / advanced / research sections.
- Research cards and metadata/evidence groundwork.
- Promotion workflow and color/theme rollout across dashboard surfaces.

### Changed
- Dashboard moved from a single dense page to a more structured navigation model.
- Research areas became more explicit, while stable/advanced views became easier to scan.

### Fixed
- Heatmap filter and dashboard crash issues.
- Several UX and color consistency problems across dashboard pages.

## 2026-04-08

### Added
- LAN session auth and device control groundwork.
- Camera sender, viewer, and remote session/device management foundations.
- Searchable selects, date filtering, and multiple dashboard/analysis UI improvements.
- Sync architecture phase 1 and follow-up DB hardening.
- Alembic migration foundation for safer DB evolution.

### Changed
- Annotation flow accelerated with clearer modes and review-later support.
- Analysis router split into stable / advanced / research layers.
- Mobile and LAN workflows became more intentional.

### Fixed
- Multiple LAN/session/share issues.
- Database sync metadata gaps and schema edge cases.
- UI/UX issues found during validation passes.

## 2026-04-07

### Added
- Prediction rebuild foundations with broader analyst depth.
- Human forecast comparison groundwork.
- Lineup and evidence-oriented prediction features.

### Changed
- Prediction moved closer to a research-oriented, badminton-specific analysis layer.

## Notes

- Validation details are tracked separately under `shuttlescope/docs/validation/`.
- Local private planning and internal notes remain under `private_docs/` and are not committed.
