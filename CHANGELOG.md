# Changelog

This changelog records ShuttleScope's evolution from repository creation onward.
It is intentionally more detailed than a typical release changelog because this project is still being shaped rapidly, and the history itself is useful context and motivation.

Read it together with:

- `README.md` for the current product scope and what is realistically usable now
- `shuttlescope/docs/validation/` for narrower validation notes and issue-by-issue verification

## How To Read This File

- Dates are grouped by development day.
- Entries are written at a product / workflow level, but they stay close to what was actually implemented.
- This is not a literal dump of `git log`, but it aims to preserve the meaningful shape of the work.

## 2026-04-12

### Product and UX
- Expanded the top-level product documentation so the repository now explains ShuttleScope in a more grounded, current-state way.
- Added a proper root `CHANGELOG.md` so progress is visible from the repository top level.
- Polished dashboard selectors and theme controls, including better mobile-safe selectors, same-page navigation, and overview/advanced page usability.
- Improved responsive behavior across dashboard surfaces and heatmap-related views.

### Annotation and Match Workflow
- Improved match edit validation feedback and safer save behavior.
- Fixed server-state handling during rally confirmation so saved annotation state is less likely to drift from UI state.
- Improved LAN same-device access flow so sharing links behave more reliably when the same machine is both operator and consumer.

### Heatmaps and Responsive UI
- Added heatmap composite support and corresponding backend/frontend integration.
- Tightened responsive UI behavior across overview, advanced, settings, top navigation, section navigation, and several analysis cards.
- Added dedicated backend heatmap composite tests and updated UI behaviors so complex analysis views survive narrower layouts better.

### Security and Hardening
- Responded to a dedicated security review pass with concrete backend hardening.
- Restricted `localfile://` handling more aggressively.
- Added upload/body-size limits and safer request handling around file-oriented endpoints.
- Hardened sync import/copy paths against oversized input and path traversal.
- Added active-session and participant validation in camera WebSocket signaling.
- Added operator-token protection for sensitive remote session management flows.
- Switched session code generation from non-cryptographic random generation to a CSPRNG-based approach.

### Validation and Test Health
- Updated websocket signaling tests so they reflect the newer active-session requirements instead of silently depending on older assumptions.
- Kept the full test suite green while expanding responsive/security coverage.

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
- Improved YOLO diagnostics and artifact-status visibility so missing setup/problems are easier to diagnose.
- Added CV-assisted annotation candidates, candidate badges, and review queue groundwork.
- Started moving from "CV exists" to "CV suggests actual annotation actions" by introducing candidate application flows and review handling.

### Remote and CV Failure Handling
- Recorded and responded to critical remote/CV failures as validation findings rather than hiding them behind optimistic assumptions.
- Fixed remote share rebasing problems and made CV errors much more visible.
- Improved tunnel/ngrok hardening so remote sharing state is more explicit.

### Bootstrap and No-Video Work
- Used the no-video window productively by strengthening CV assist UX, review queue flow, and environment/bootstrap tooling.
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
- Added the dashboard research spine and metadata/evidence groundwork.
- Added research cards and meta integration so state-value, counterfactual, hazard/fatigue, and related work has a stable home.
- Added promotion workflow and advanced-meta rollout so research outputs can be tracked as candidates for broader adoption.
- Completed promotion gaps and extended the color/theming system across more dashboard surfaces.
- Added audit log and theme fixes around promotion overrides.
- Hardened opponent policy refresh and error-state handling.

### Dashboard and Analysis UX
- Added date slider v2 and zone-map modal workflows.
- Fixed heatmap filtering and crash handling issues.
- Applied theme/card rules consistently across advanced and research surfaces.

### Remote Camera and Live Collaboration
- Added remote tunnel providers and initial WebRTC/TURN settings support.
- Hardened remote diagnostics and stale camera cleanup behavior.
- Added TURN diagnostics and reconnect hardening.
- Added a remote viewer page and improved sender reconnect behavior.
- Polished remote handoff flow and grouped viewer UX.
- Added tunnel-provider visibility to the annotator remote health banner.

### Documentation and Positioning
- Rewrote the README around the practical PoC/current product scope rather than over-claiming future work.

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
- Unified analysis foundations and player context so the later advanced/research stack had a cleaner base.
- Split analysis routers into stable, advanced, and research layers.
- Added stage 2 engines, then stage 3 research engines for counterfactual and EPV-oriented work.
- Added searchable selects and date range filtering across important UI paths.

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
- Added searchable selects and date range filters.
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
- Improved end-state handling and match setup ergonomics.

### Analytics and Research
- Implemented research roadmap analytics modules.
- Added warmup observations and related analytics context.
- Closed major remaining gaps with tests, seed data, and CI.
- Added heatmap modal and warmup analytics fixes.

### Prediction
- Added the first prediction tab and pair simulation foundation.
- Refined the prediction tab toward coach/analyst workflows.
- Added analyst-depth and human-benchmark oriented prediction features.

### Sharing and Access
- Added LAN and tunnel web access support.

### Documentation
- Refreshed the README multiple times to keep it closer to reality as scope expanded.

### Detailed Progress
- Refined annotation keymap and rally end flow.
- Refreshed the top-level README.
- Polished annotation flow end-state handling.
- Implemented research roadmap analytics modules.
- Added warmup observations and detail analytics context.
- Closed remaining gaps with tests, seed data, and CI.
- Added heatmap modal and warmup analytics fixes.
- Added prediction tab and pair simulation foundation.
- Refined prediction tab for coach and analyst workflows.
- Added doubles annotation hitter flow.
- Added LAN and tunnel web access support.
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
- Added a match-day workflow and set summary behavior.
- Improved desktop startup and quick-start flows.
- Improved annotation flow and interval handling.
- Completed a broad annotation/desktop workflow phase.
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
- Ignored local player/match database artifacts so local work would not pollute version control.

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
