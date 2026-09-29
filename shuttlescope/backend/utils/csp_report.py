"""CSP 違反レポートを「読めるログ 1 行」に畳む。

`backend/main.py` に置いていたが、main を import すると
FastAPI アプリ全体が立ち上がるのでテストから触りにくい。
純粋な変換なので分離する。
"""
from __future__ import annotations


#: 詳細の無い CSP レポートの累計。ログを埋めない代わりに件数は残す。
_CSP_UNINFORMATIVE: dict = {"n": 0}


def _csp_report_summary(data: dict) -> tuple[str, bool]:
    """CSP レポートを 1 行に畳み、**追える情報があるか**を返す。

    旧実装は `str(data)[:500]` を WARNING に流していた。中身の大半は
    `original-policy`、つまり**こちらが送ったポリシーそのもの**で、
    毎回同じ文字列がログを埋めるだけだった。しかも 500 文字で切るので、
    知りたい `blocked-uri` や `script-sample` は切り落とされていた。

    実測 (本番 182 件): すべて `document-uri` / `referrer` /
    `violated-directive` / `effective-directive` / `original-policy` のみで、
    `blocked-uri` すら入っていない。Safari のレポート形式で、
    閲覧者の拡張機能が差し込んだスクリプトでも上がる。
    こちらのページの欠陥かどうかを判定できる材料が無い。

    Returns: (1行要約, actionable)
    """
    report = data
    if isinstance(data.get("csp-report"), dict):
        report = data["csp-report"]
    elif isinstance(data.get("body"), dict):
        report = data["body"]

    def _g(*names: str) -> str:
        for n in names:
            v = report.get(n)
            if isinstance(v, (str, int)) and str(v).strip():
                return str(v).strip()
        return ""

    directive = _g("effective-directive", "effectiveDirective",
                   "violated-directive", "violatedDirective")
    blocked = _g("blocked-uri", "blockedURL", "blockedURI")
    document = _g("document-uri", "documentURL")
    source = _g("source-file", "sourceFile")
    line = _g("line-number", "lineNumber")
    sample = _g("script-sample", "sample")

    actionable = bool(blocked or source or sample)
    parts = [f"directive={directive or '?'}", f"document={document or '?'}"]
    if blocked:
        parts.append(f"blocked={blocked}")
    if source:
        parts.append(f"source={source}:{line or '?'}")
    if sample:
        parts.append(f"sample={sample[:120]}")
    if not actionable:
        parts.append("detail=none")
    # ポリシー本文は載せない (こちらが送ったものなので情報量ゼロ)。
    return " ".join(parts)[:400], actionable
