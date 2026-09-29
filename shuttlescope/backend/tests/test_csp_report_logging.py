"""CSP レポートのログが読めるものであること。

旧実装は `str(data)[:500]` を WARNING に流していた。中身の大半は
`original-policy` ＝ **こちらが送ったポリシーそのもの**で、毎回同じ文字列が
ログを埋める。しかも 500 文字で切るので、知りたい `blocked-uri` や
`script-sample` は切り落とされる。

本番の実測 (182 件) はすべて `document-uri` / `referrer` /
`violated-directive` / `effective-directive` / `original-policy` のみで、
`blocked-uri` すら入っていなかった。Safari のレポート形式で、閲覧者の
拡張機能が差し込んだスクリプトでも上がる。こちらのページの欠陥かどうかを
判定できる材料が無い。

情報の無いレポートを WARNING で積むと、**本物の違反がその中に埋もれる**。
追える情報があるものだけ WARNING に出す。

変換自体は `backend/utils/csp_report.py` に置いてあるので、
`backend.main` を import せずに検証できる (Python 3.10 でも走る)。
"""
from __future__ import annotations

from backend.utils.csp_report import _csp_report_summary

#: 本番のログにあったのと同じ形（Safari）。
_SAFARI_SHAPED = {
    "csp-report": {
        "document-uri": "https://shuttle-scope.com/",
        "referrer": "https://www.google.com/",
        "violated-directive": "script-src-elem",
        "effective-directive": "script-src-elem",
        "original-policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; " * 4,
    }
}

_CHROME_SHAPED = {
    "csp-report": {
        "document-uri": "https://app.shuttle-scope.com/",
        "violated-directive": "script-src-elem",
        "effective-directive": "script-src-elem",
        "blocked-uri": "https://evil.example/x.js",
        "source-file": "https://app.shuttle-scope.com/assets/index-abc.js",
        "line-number": 42,
        "original-policy": "default-src 'self'; " * 10,
    }
}


def test_a_report_with_no_detail_is_not_raised_as_a_warning():
    summary, actionable = _csp_report_summary(_SAFARI_SHAPED)
    assert actionable is False, summary
    assert "detail=none" in summary
    assert "directive=script-src-elem" in summary
    assert "document=https://shuttle-scope.com/" in summary


def test_a_report_that_names_what_was_blocked_is_actionable():
    summary, actionable = _csp_report_summary(_CHROME_SHAPED)
    assert actionable is True
    assert "blocked=https://evil.example/x.js" in summary
    assert "source=https://app.shuttle-scope.com/assets/index-abc.js:42" in summary


def test_the_policy_we_sent_is_not_echoed_back_into_the_log():
    """`original-policy` は自分が送ったもの。ログに置いても情報量がゼロで、
    本当に読みたいフィールドを押し出す。"""
    for payload in (_SAFARI_SHAPED, _CHROME_SHAPED):
        summary, _ = _csp_report_summary(payload)
        assert "default-src" not in summary, summary
        assert len(summary) <= 400


def test_the_reporting_api_shape_is_understood_too():
    """Reporting API は `body` の下に camelCase で入れてくる。"""
    summary, actionable = _csp_report_summary({
        "type": "csp-violation",
        "url": "https://app.shuttle-scope.com/",
        "body": {
            "documentURL": "https://app.shuttle-scope.com/",
            "effectiveDirective": "connect-src",
            "blockedURL": "wss://evil.example/",
        },
    })
    assert actionable is True
    assert "directive=connect-src" in summary
    assert "blocked=wss://evil.example/" in summary


def test_an_empty_report_does_not_blow_up():
    summary, actionable = _csp_report_summary({})
    assert actionable is False
    assert "directive=?" in summary
