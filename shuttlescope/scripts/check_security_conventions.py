"""フロント側のセキュリティ規約違反を grep で検出する CI 用スクリプト。

検出対象:
  V1: localfile:/// の直接埋め込み (テンプレートリテラル経由含む)
  V2: match.video_local_path の読み取り (型定義以外)
  V3: apiDelete( で X-Idempotency-Key なし
  V4: console.log で video_token / video_local_path 出力

使い方:
  python scripts/check_security_conventions.py        # 通常モード (失敗時 exit 1)
  python scripts/check_security_conventions.py --warn # 警告のみ (常に exit 0)

CI への組み込み例 (.github/workflows/ci.yml):
  - run: python shuttlescope/scripts/check_security_conventions.py
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

# Windows CI (cp1252) で日本語 print が UnicodeEncodeError を起こすため強制 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent / "src"

EXEMPT_FILES = {
    # 規約自身を実装するファイルは除外
    "videoSrc.ts",
    "client.ts",
    "index.ts",  # types/index.ts (型定義)
}

EXEMPT_PATTERNS = [
    re.compile(r"//\s*ALLOW:\s*"),   # 個別許可コメント
    re.compile(r"#\s*ALLOW:\s*"),
]


def _is_exempt_line(line: str) -> bool:
    return any(p.search(line) for p in EXEMPT_PATTERNS)


def _scan_files() -> list[Path]:
    return [
        p for p in ROOT.rglob("*.tsx")
    ] + [
        p for p in ROOT.rglob("*.ts")
        if not p.name.endswith(".d.ts")
    ]


def _check_v1_localfile_direct(files: list[Path]) -> list[str]:
    """V1: localfile:/// の直接構築を検出 (video src への代入のみ)。

    apiPut/apiPost の body プロパティとして video_local_path に渡すのは書き込みなので OK。
    検出するのは <video src=...> や setState で localfile:/// を構築するパターン。
    """
    pattern = re.compile(r"src\s*[:=]\s*[`'\"]localfile://|setForm.*video_local_path:.*`localfile")
    violations = []
    for f in files:
        if f.name in EXEMPT_FILES:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if _is_exempt_line(line):
                    continue
                # apiPut / apiPost の body 内の書き込みは除外
                if "apiPut" in line or "apiPost" in line:
                    continue
                if pattern.search(line):
                    violations.append(f"{f.relative_to(ROOT.parent)}:{i}: {line.strip()[:120]}")
        except Exception:
            continue
    return violations


def _check_v2_video_local_path_read(files: list[Path]) -> list[str]:
    """V2: match.video_local_path / m.video_local_path の読み取り検出"""
    # 書き込み (apiPut の body) は OK、読み取り (.video_local_path にドットアクセス) のみ
    pattern = re.compile(r"\b(match|m|matchData\?\.data)\?\.video_local_path\b")
    violations = []
    for f in files:
        if f.name in EXEMPT_FILES:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if _is_exempt_line(line):
                    continue
                if pattern.search(line):
                    # 書き込み body 内かチェック (apiPut の引数として登場するなら除外)
                    if "apiPut" in line or "apiPost" in line and ":" in line:
                        # body オブジェクト内の書き込みは許可
                        continue
                    violations.append(f"{f.relative_to(ROOT.parent)}:{i}: {line.strip()[:120]}")
        except Exception:
            continue
    return violations


def _check_v3_apidelete_without_idem(files: list[Path]) -> list[str]:
    """V3: apiDelete( に X-Idempotency-Key を付けていない呼び出しを検出"""
    violations = []
    for f in files:
        if f.name in EXEMPT_FILES:
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue
        # apiDelete( の各出現位置から最大 3 行先まで X-Idempotency-Key があるか
        for m in re.finditer(r"apiDelete\s*\(", content):
            start = m.start()
            snippet = content[start:start + 300]
            line_no = content[:start].count("\n") + 1
            if "X-Idempotency-Key" not in snippet:
                line_text = content.splitlines()[line_no - 1] if line_no <= len(content.splitlines()) else ""
                if _is_exempt_line(line_text):
                    continue
                violations.append(
                    f"{f.relative_to(ROOT.parent)}:{line_no}: {line_text.strip()[:120]}"
                )
    return violations


def _check_v4_console_log_secrets(files: list[Path]) -> list[str]:
    """V4: console.log に video_token / video_local_path / 鍵を出力していないか"""
    pattern = re.compile(
        r"console\.(log|warn|error|info|debug)\s*\([^)]*\b"
        r"(video_token|video_local_path|SECRET_KEY|access_token|refresh_token|password)\b"
    )
    violations = []
    for f in files:
        if f.name in EXEMPT_FILES:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if _is_exempt_line(line):
                    continue
                if pattern.search(line):
                    violations.append(f"{f.relative_to(ROOT.parent)}:{i}: {line.strip()[:120]}")
        except Exception:
            continue
    return violations


CHECKS = [
    ("V1", "localfile:/// 直接構築", _check_v1_localfile_direct),
    ("V2", "video_local_path 読み取り", _check_v2_video_local_path_read),
    ("V3", "apiDelete に X-Idempotency-Key なし", _check_v3_apidelete_without_idem),
    ("V4", "console.log に機密情報", _check_v4_console_log_secrets),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warn", action="store_true",
                        help="違反を警告のみで返す (exit 0)")
    args = parser.parse_args()

    files = _scan_files()
    print(f"[*] スキャン対象: {len(files)} ファイル")
    print(f"    src: {ROOT}")
    print()

    total = 0
    for vid, desc, check_fn in CHECKS:
        violations = check_fn(files)
        status = "OK" if not violations else f"VIOLATION ({len(violations)})"
        print(f"[{vid}] {desc}: {status}")
        for v in violations[:20]:  # 最大 20 件まで表示
            print(f"  {v}")
        if len(violations) > 20:
            print(f"  ... and {len(violations) - 20} more")
        total += len(violations)

    print()
    if total == 0:
        print(f"[OK] 違反なし")
        return 0
    print(f"[FAIL] 違反 {total} 件")
    return 0 if args.warn else 1


if __name__ == "__main__":
    sys.exit(main())
