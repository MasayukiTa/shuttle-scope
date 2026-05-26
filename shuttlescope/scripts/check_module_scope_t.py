#!/usr/bin/env python3
"""Detect module-scope `t(` from useTranslation() in TSX/TS files.

Bug class: writing

    const FOO = [{ label: t('key') }]

at module scope crashes the minified production bundle with
`ReferenceError: t is not defined`, because `t` only exists inside the
component body after `const { t } = useTranslation()`.

This script greps `src/**/*.tsx` for top-level `const|let|var` declarations
whose initializer references a bare `t(` (not `i18n.t(` or `something.t(`).
Allowed: anything inside a function/class/arrow body (any indent), and
calls qualified with a dot like `i18n.t(`.

Exit code:
  0 — clean
  1 — bug pattern found (prints offending file:line)
  2 — internal error (no files scanned)

Run from repo root:
    python shuttlescope/scripts/check_module_scope_t.py
or via npm:
    npm run check:i18n
"""
from __future__ import annotations
import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]   # shuttlescope/
SRC = ROOT / "src"

# Matches a TOP-LEVEL declaration: const|let|var at column 0 (no leading
# whitespace), followed by an identifier.
TOP_LEVEL = re.compile(r"^(?:const|let|var)\s+\w+")

# Matches bare `t(` — NOT preceded by `.` (so `i18n.t(` / `obj.t(` exempt)
# and NOT inside a string literal (heuristic: skip lines that look like JS
# comments). Word boundary on the left ensures we don't catch `cat(` etc.
BARE_T_CALL = re.compile(r"(?<![\.\w])t\s*\(")


def is_inside_string_or_comment(line: str, pos: int) -> bool:
    """Quick heuristic: is the position pos inside `'...'`, `"..."`, `\`...\``,
    or after `//` on this line. Doesn't handle multi-line strings/comments —
    those are rare in this idiom and false positives are caught by visual
    review of the offending file.
    """
    quote = None
    i = 0
    while i < pos and i < len(line):
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        else:
            if c in ("'", '"', "`"):
                quote = c
            elif c == "/" and i + 1 < len(line) and line[i + 1] == "/":
                # line comment from here
                return True
        i += 1
    return quote is not None


FUNCTION_KEYWORD = re.compile(r"\b(?:function\b|=>|class\b)")


def find_bare_t_in_block(lines: list[str], start: int) -> int | None:
    """Scan from top-level `const|let|var` until the initializer expression
    closes (brace/bracket/paren balance returns to zero). Bug class:
      - the block contains a bare `t(` outside strings/comments AND
      - the block does NOT contain a `function`/`=>`/`class` keyword
        BEFORE that `t(` (which would introduce a new lexical scope where
        `t` may be locally bound via useTranslation()).

    If a function/arrow is opened before the t() call, we assume it's safe
    (component body / nested function). False negatives are possible but
    rare; the goal is zero false positives on a healthy codebase.
    """
    depth = 0
    started = False
    func_seen = False
    for offset, line in enumerate(lines[start:], start=start):
        # update function-scope flag for this line
        if FUNCTION_KEYWORD.search(line):
            func_seen = True
        for ch in line:
            if ch in "({[":
                depth += 1
                started = True
            elif ch in ")}]":
                depth -= 1
        # only flag if no function/arrow has been introduced yet
        if not func_seen:
            for m in BARE_T_CALL.finditer(line):
                if not is_inside_string_or_comment(line, m.start()):
                    return offset
        if started and depth <= 0:
            return None
    return None


# 2026-05-26: module-scope `function NAME(...) { ... }` helper も検出する。
# 例えば `function EPVCard(...) { ...t(...)... }` が parent component の
# useTranslation() の `t` を参照してしまうケース (MarkovEPV bug class)。
# 検出条件:
#   1. 行頭 (indent 0) で `function NAME(` で始まる
#   2. その関数 body 内で `useTranslation()` を呼んでいない
#   3. body 内に bare `t(` がある (string/comment 除く)
TOP_LEVEL_FN = re.compile(r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+\w+\s*\(")
USE_TRANSLATION_CALL = re.compile(r"\buseTranslation\s*\(")
# シグネチャ部分 (関数開始 `(` 〜 `)` まで) に `t` パラメータがある関数は
# 引数経由で t を受け取っているので flag しない。
#   match: `t:` `t,` `t)` `t =` `t}` (パラメータ宣言、destructure 終端含む)
PARAM_T = re.compile(r"\bt\s*[}:,=)]")


def find_bare_t_in_function(lines: list[str], start: int) -> int | None:
    """module-scope `function NAME(...) { ... }` の body をスキャンし、
    body 内に useTranslation() が無く bare t( がある場合に行番号を返す。

    シグネチャ (function 〜 最初の `{` まで) に `t` パラメータがあれば
    そもそも引数経由で受けているので flag しない。"""
    depth = 0
    in_body = False
    has_use_translation = False
    candidate: int | None = None
    # ── まずシグネチャ部分 (関数の `(` 〜 対応する `)` まで) を取り出す ──
    # destructuring 引数 `function Foo({a, t, b}: ...)` の `{` を body 開始と
    # 誤認しないよう、まず `(` 〜 `)` をバランス取って読む。
    sig_buf: list[str] = []
    paren_depth = 0
    sig_started = False
    sig_complete = False
    for ln in lines[start:]:
        for ch in ln:
            if ch == "(":
                paren_depth += 1
                sig_started = True
            elif ch == ")":
                paren_depth -= 1
                if sig_started and paren_depth == 0:
                    sig_complete = True
                    break
        sig_buf.append(ln)
        if sig_complete:
            break
    sig_text = " ".join(sig_buf)
    if PARAM_T.search(sig_text):
        return None  # t は引数で受けている → 安全

    for offset, line in enumerate(lines[start:], start=start):
        for ch in line:
            if ch == "{":
                depth += 1
                in_body = True
            elif ch == "}":
                depth -= 1
        if not in_body:
            continue
        if USE_TRANSLATION_CALL.search(line):
            has_use_translation = True
        # bare t( を見つけたら候補として保存 (確定は body 終了時)
        if candidate is None:
            for m in BARE_T_CALL.finditer(line):
                if not is_inside_string_or_comment(line, m.start()):
                    candidate = offset
                    break
        if in_body and depth <= 0:
            # body 抜けた
            if candidate is not None and not has_use_translation:
                return candidate
            return None
    return None


def scan(path: pathlib.Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    hits: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        if TOP_LEVEL.match(ln):
            bad_line = find_bare_t_in_block(lines, i)
            if bad_line is not None:
                hits.append((bad_line + 1, lines[bad_line].strip()[:100]))
        elif TOP_LEVEL_FN.match(ln):
            bad_line = find_bare_t_in_function(lines, i)
            if bad_line is not None:
                hits.append((bad_line + 1, lines[bad_line].strip()[:100]))
    return hits


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: {SRC} not found", file=sys.stderr)
        return 2
    files = list(SRC.rglob("*.tsx")) + list(SRC.rglob("*.ts"))
    if not files:
        print(f"ERROR: no .tsx/.ts files under {SRC}", file=sys.stderr)
        return 2
    total_hits = []
    for f in files:
        # skip test files (they may use mock t() at top level legitimately)
        if "__tests__" in f.parts or f.name.endswith(".test.ts") or f.name.endswith(".test.tsx"):
            continue
        for line_no, snippet in scan(f):
            total_hits.append((f.relative_to(ROOT), line_no, snippet))
    if total_hits:
        print("MODULE-SCOPE BARE t() CALLS FOUND (will crash minified bundle "
              "with ReferenceError):\n")
        for rel, ln, snip in total_hits:
            print(f"  {rel}:{ln}: {snip}")
        print(f"\nTotal: {len(total_hits)}")
        print(
            "\nFix: move the const into the component body and wrap it with\n"
            "useMemo(() => (...), [t]). The bare top-level `t` reference\n"
            "crashes minified production builds (`ReferenceError: t is not\n"
            "defined`). See commit 4b9eef5 for a worked example."
        )
        return 1
    print(f"OK: scanned {len(files)} file(s), no module-scope bare t() calls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
