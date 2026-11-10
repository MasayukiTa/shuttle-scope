#!/usr/bin/env python3
"""Verify that every vitest test file listed in scripts/ci_test_manifest.txt
is actually collected by CI.

Why this exists (\u65b9\u91ddC):
  CI runs the frontend suite via `npx vitest run --config vitest.config.ts`,
  which collects test files by the `test.include` glob in vitest.config.ts
  (src/**/__tests__/**/*.test.{ts,tsx}). A new test that does NOT match that
  glob would silently never run while CI stays green. This script fails CI if
  any manifest entry (a) does not exist on disk, or (b) does not match the
  vitest include glob \u2014 i.e. would not be collected.

Exit code:
  0 \u2014 every manifest entry exists and is collected by the vitest include glob
  1 \u2014 a manifest entry is missing on disk or not covered by the glob
  2 \u2014 internal error (config/manifest unreadable)

Run from repo root:
    python shuttlescope/scripts/check_ci_test_manifest.py
or with shuttlescope/ as cwd (as CI does):
    python scripts/check_ci_test_manifest.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent  # shuttlescope/
MANIFEST = ROOT / "scripts" / "ci_test_manifest.txt"
# Drop-in directory: each new test registers itself as one *.txt file here so
# that parallel PRs no longer collide on the single ci_test_manifest.txt tail.
MANIFEST_DIR = ROOT / "scripts" / "ci_test_manifest.d"
VITEST_CONFIG = ROOT / "vitest.config.ts"


def _read_include_globs() -> list[str]:
    """Extract the test.include glob array from vitest.config.ts.

    Parsed literally (not executed). Looks for `include: [ ... ]` and pulls the
    quoted string entries. Keeps this dependency-free and deterministic.
    """
    text = VITEST_CONFIG.read_text(encoding="utf-8")
    m = re.search(r"include\s*:\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Translate a vitest/minimatch-style glob to a regex.

    Supports the constructs used by this repo's include globs:
      **    -> any chars incl. '/'
      *     -> any chars except '/'
      {a,b} -> alternation (a|b)
    """
    i = 0
    out = ["^"]
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "{":
            j = glob.index("}", i)
            alts = glob[i + 1 : j].split(",")
            out.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
            i = j + 1
        elif c == ".":
            out.append(r"\.")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def _read_manifest_file(path: Path) -> list[str]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _read_manifest() -> list[str]:
    """Collect manifest entries from the legacy single file AND the drop-in
    directory scripts/ci_test_manifest.d/*.txt.

    Both sources are read; duplicate entries are collapsed to one while
    preserving first-seen order (legacy file first, then *.d files sorted by
    name). The *.d layout lets each new test register itself in its own file
    so concurrent PRs do not conflict on a shared tail line.
    """
    sources: list[Path] = []
    if MANIFEST.is_file():
        sources.append(MANIFEST)
    if MANIFEST_DIR.is_dir():
        sources.extend(sorted(MANIFEST_DIR.glob("*.txt")))

    seen: set[str] = set()
    entries: list[str] = []
    for src in sources:
        for line in _read_manifest_file(src):
            if line in seen:
                continue
            seen.add(line)
            entries.append(line)
    return entries


def main() -> int:
    if not MANIFEST.exists():
        print(f"[FAIL] manifest not found: {MANIFEST}")
        return 2
    if not VITEST_CONFIG.exists():
        print(f"[FAIL] vitest.config.ts not found: {VITEST_CONFIG}")
        return 2

    globs = _read_include_globs()
    if not globs:
        print("[FAIL] could not parse test.include globs from vitest.config.ts")
        return 2
    patterns = [_glob_to_regex(g) for g in globs]

    entries = _read_manifest()
    print(f"[*] manifest entries: {len(entries)}")
    print(f"    include globs: {globs}")
    print()

    problems = []
    for rel in entries:
        abs_path = ROOT / rel
        if not abs_path.is_file():
            problems.append(f"missing on disk: {rel}")
            continue
        if not any(p.match(rel) for p in patterns):
            problems.append(f"not covered by vitest include glob (would NOT run): {rel}")

    for rel in entries:
        covered = (ROOT / rel).is_file() and any(p.match(rel) for p in patterns)
        print(f"  [{'OK' if covered else 'FAIL'}] {rel}")
    print()

    if problems:
        print(f"[FAIL] {len(problems)} manifest problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("[OK] all manifest tests exist and are collected by the vitest include glob")
    return 0


if __name__ == "__main__":
    sys.exit(main())
