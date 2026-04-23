# Security Policy

## Supported Versions

ShuttleScope is currently in prototype/POC stage. Security fixes are applied to the `main` branch only.

| Version | Supported |
|---------|-----------|
| `main`  | ✅        |
| older   | ❌        |

## Reporting a Vulnerability

If you discover a security vulnerability in ShuttleScope, please **do not** open a public GitHub issue.

Instead, report it privately via one of:

1. **GitHub Security Advisory** — preferred. Submit via https://github.com/MasayukiTa/shuttle-scope/security/advisories/new (or click "Report a vulnerability" on the repository's Security tab).
2. **Email** — send details to the maintainer contact listed on the GitHub profile: https://github.com/MasayukiTa

Please include:

- Affected component (backend API, Electron shell, renderer, GitHub Actions workflow, etc.)
- Reproduction steps or proof-of-concept
- Impact assessment (confidentiality / integrity / availability)
- Any suggested mitigation

You should receive an initial acknowledgement within 7 days. We aim to triage and propose a fix or mitigation plan within 30 days for confirmed vulnerabilities.

## Scope

In-scope:

- FastAPI backend (`shuttlescope/backend/`)
- Electron main / preload (`shuttlescope/electron/`)
- React renderer (`shuttlescope/src/`)
- Build and CI workflows (`.github/workflows/`)

Out-of-scope (not prototype concerns at this stage):

- Local role switching via `useAuth` (POC-only; not production auth)
- Reports on issues already tracked in the public Code Scanning / Dependabot tabs

## Hardening Notes

Ongoing hardening work is tracked in `shuttlescope/docs/validation/`. Known accepted risks are documented there with justification.
