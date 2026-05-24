"""shuttle-scope: detect non-MIcon icon usage in src/**/*.tsx,ts.

Exits non-zero if any of the following is found:
  - emoji literals in .tsx files (excluding comments)
  - imports from lucide-react / react-icons / @heroicons / @radix-ui/react-icons / @fortawesome/*

Allowed: <MIcon name="..." /> from '@/components/common/MIcon'.

Run: python scripts/check_no_emoji_in_jsx.py
Wired via: npm run check:icons
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows (cp932 default) so unicode messages print.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# Unicode ranges that are emoji-like (pictographs, symbols, dingbats, arrows).
# Exclude plain ASCII; allow common typographic punctuation by being narrow.
EMOJI_RE = re.compile(
    "["  # noqa: E501
    "\U0001F300-\U0001F9FF"  # misc symbols & pictographs / emoticons / transport / supplemental
    "\U0001FA00-\U0001FAFF"  # symbols & pictographs extended-A
    "☀-➿"           # misc symbols, dingbats (covers ☀ ☂ ★ ✓ ✗ ❌ ⚠ etc.)
    "⌀-⏿"           # misc technical (⏰ ⏸ ⏹ ⌚ etc.)
    "⬀-⯿"           # arrows etc.
    "\U0001F100-\U0001F1FF"  # enclosed alphanumeric supplement (regional indicators etc.)
    "]"
)

BANNED_IMPORTS = re.compile(
    r"""from\s+['"](lucide-react|react-icons(?:/[^'"]*)?|@heroicons/[^'"]*|@radix-ui/react-icons|@fortawesome/[^'"]*)['"]"""
)

# Allow specific code-points that are commonly used as plain text punctuation:
ALLOWED_CODEPOINTS = {
    "…",  # … horizontal ellipsis
    "—",  # — em dash
    "–",  # – en dash
    "→",  # → rightwards arrow (still loud — disallow if you want strict, but used in copy)
}


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (lineno, kind, snippet)."""
    out: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return out
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        is_line_comment = stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*")
        # banned imports
        if BANNED_IMPORTS.search(line):
            m = BANNED_IMPORTS.search(line)
            out.append((idx, f"banned-import:{m.group(1)}", line.strip()))
        # emoji in .tsx (skip pure-comment lines)
        if path.suffix == ".tsx" and not is_line_comment:
            for ch in line:
                if EMOJI_RE.match(ch) and ch not in ALLOWED_CODEPOINTS:
                    out.append((idx, f"emoji:U+{ord(ch):04X}", line.strip()))
                    break
    return out


def main() -> int:
    violations: list[tuple[Path, int, str, str]] = []
    for ext in ("*.tsx", "*.ts"):
        for p in SRC.rglob(ext):
            # skip generated/types
            if "__tests__" in p.parts:
                continue
            for v in scan_file(p):
                violations.append((p, *v))
    if violations:
        print(f"[check:icons] FAIL — {len(violations)} violation(s):")
        for p, ln, kind, snip in violations:
            rel = p.relative_to(ROOT)
            print(f"  {rel}:{ln}  [{kind}]  {snip[:160]}")
        print()
        print("Rule: shuttle-scope のアイコンは Material Symbols (MIcon) 限定。")
        print("  Allowed: <MIcon name=\"...\" /> from '@/components/common/MIcon'")
        print("  Banned : lucide-react / react-icons / @heroicons / @radix-ui/react-icons / @fortawesome / emoji literals")
        return 1
    print("[check:icons] OK — no violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
