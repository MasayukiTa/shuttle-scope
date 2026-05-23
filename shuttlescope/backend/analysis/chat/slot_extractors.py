"""Slot extractors (rule-based, no LLM) for conversational scope system.

抽出対象スロット:
  - period   : 日付範囲 (parsePeriod.ts と仕様一致)
  - shot_type: smash / clear / drop / net / drive / push / lob / serve
  - zone     : FL / FR / BL / BR (フォア前 / バック前 / フォア奥 / バック奥) など

設計方針:
  - ピュア関数: now を引数化、テスト容易
  - 否定文脈 ("スマッシュ以外") では positive match を返さない
  - 出力は {"code": str, "label": str, "matched_text": str}
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Optional


# ─── 日付ユーティリティ ───────────────────────────────────────────
def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _start_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def _end_of_month(d: date) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last)


def _add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    y, m = divmod(total, 12)
    day = min(d.day, calendar.monthrange(y, m + 1)[1])
    return date(y, m + 1, day)


def _add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


def _add_years(d: date, n: int) -> date:
    try:
        return date(d.year + n, d.month, d.day)
    except ValueError:
        return date(d.year + n, d.month, 28)


def _start_of_week_mon(d: date) -> date:
    # 月曜始まり
    return d - timedelta(days=d.weekday())


def _start_of_year(d: date) -> date:
    return date(d.year, 1, 1)


def _end_of_year(d: date) -> date:
    return date(d.year, 12, 31)


# ─── period extractor ────────────────────────────────────────────
def _expand_yy(yy: int, now: date) -> int:
    if yy >= 100:
        return yy
    cur_yy = now.year % 100
    return 2000 + yy if yy <= cur_yy + 1 else 1900 + yy


def extract_period(text: str, now: Optional[datetime] = None) -> Optional[dict]:
    """日付範囲を抽出する。マッチしなければ None。

    返値: {"date_from": "YYYY-MM-DD"|None, "date_to": "YYYY-MM-DD"|None,
           "label": str, "matched_text": str}
    """
    if not text or not text.strip():
        return None
    today = (now or datetime.now()).date()
    s = text

    # 1. 絶対範囲 YYYY-MM-DD 〜 YYYY-MM-DD / YYYY/M/D 〜 YYYY/M/D
    m = re.search(
        r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?\s*(?:〜|~|から|to|–|—|-)\s*"
        r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?",
        s,
    )
    if m:
        try:
            f = date(int(m[1]), int(m[2]), int(m[3]))
            t = date(int(m[4]), int(m[5]), int(m[6]))
            return {
                "date_from": _fmt(f),
                "date_to": _fmt(t),
                "label": f"{_fmt(f)} 〜 {_fmt(t)}",
                "matched_text": m.group(0),
            }
        except ValueError:
            pass

    # 2. YYYY/M/D から 今まで
    m = re.search(
        r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?\s*から\s*(?:今|現在)まで",
        s,
    )
    if m:
        try:
            f = date(int(m[1]), int(m[2]), int(m[3]))
            return {
                "date_from": _fmt(f),
                "date_to": _fmt(today),
                "label": f"{_fmt(f)} 〜 今日",
                "matched_text": m.group(0),
            }
        except ValueError:
            pass

    # 3. since YYYY-MM(-DD)?
    m = re.search(r"since\s+(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?", s, re.IGNORECASE)
    if m:
        try:
            d_day = int(m[3]) if m[3] else 1
            f = date(int(m[1]), int(m[2]), d_day)
            return {
                "date_from": _fmt(f),
                "date_to": _fmt(today),
                "label": f"since {_fmt(f)}",
                "matched_text": m.group(0),
            }
        except ValueError:
            pass

    # 4. 相対 duration: 直近/過去/この/ここ N (日/週/ヶ月/年)
    m = re.search(r"(直近|過去|この|ここ)\s*(\d{1,3})\s*(日|週間?|ヶ月|か月|カ月|月|年)", s)
    if m:
        n = int(m[2])
        unit = m[3]
        if unit == "日":
            f = _add_days(today, -(n - 1))
            unit_ja = "日"
        elif unit.startswith("週"):
            f = _add_days(today, -(n * 7 - 1))
            unit_ja = "週"
        elif unit == "年":
            f = _add_days(_add_years(today, -n), 1)
            unit_ja = "年"
        else:
            f = _add_days(_add_months(today, -n), 1)
            unit_ja = "ヶ月"
        return {
            "date_from": _fmt(f),
            "date_to": _fmt(today),
            "label": f"直近{n}{unit_ja}",
            "matched_text": m.group(0),
        }

    # 5. past/last N days/weeks/months/years
    m = re.search(r"(past|last)\s+(\d{1,3})\s+(day|week|month|year)s?", s, re.IGNORECASE)
    if m:
        n = int(m[2])
        unit = m[3].lower()
        if unit == "day":
            f = _add_days(today, -(n - 1))
        elif unit == "week":
            f = _add_days(today, -(n * 7 - 1))
        elif unit == "year":
            f = _add_days(_add_years(today, -n), 1)
        else:
            f = _add_days(_add_months(today, -n), 1)
        return {
            "date_from": _fmt(f),
            "date_to": _fmt(today),
            "label": f"past {n} {unit}{'' if n == 1 else 's'}",
            "matched_text": m.group(0),
        }

    # 6. relative keywords
    kw_table = [
        (r"今日|本日|today", lambda: (today, today, "今日")),
        (r"昨日|yesterday", lambda: (_add_days(today, -1), _add_days(today, -1), "昨日")),
        (
            r"今週|this\s+week",
            lambda: (_start_of_week_mon(today), _add_days(_start_of_week_mon(today), 6), "今週"),
        ),
        (
            r"先週|last\s+week",
            lambda: (
                _add_days(_start_of_week_mon(today), -7),
                _add_days(_start_of_week_mon(today), -1),
                "先週",
            ),
        ),
        (r"今月|this\s+month", lambda: (_start_of_month(today), _end_of_month(today), "今月")),
        (
            r"先月|last\s+month",
            lambda: (
                _start_of_month(_add_months(today, -1)),
                _end_of_month(_add_months(today, -1)),
                "先月",
            ),
        ),
        (r"今年|this\s+year", lambda: (_start_of_year(today), _end_of_year(today), "今年")),
        (
            r"去年|昨年|last\s+year",
            lambda: (
                _start_of_year(_add_years(today, -1)),
                _end_of_year(_add_years(today, -1)),
                "去年",
            ),
        ),
    ]
    for pat, fn in kw_table:
        mm = re.search(pat, s, re.IGNORECASE)
        if mm:
            f, t, lab = fn()
            return {
                "date_from": _fmt(f),
                "date_to": _fmt(t),
                "label": lab,
                "matched_text": mm.group(0),
            }

    # 7. YYYY年M月 (単一月)
    m = re.search(r"(\d{4})年(\d{1,2})月(?!\d)(?!日)", s)
    if m:
        try:
            d_ = date(int(m[1]), int(m[2]), 1)
            return {
                "date_from": _fmt(_start_of_month(d_)),
                "date_to": _fmt(_end_of_month(d_)),
                "label": f"{int(m[1])}年{int(m[2])}月",
                "matched_text": m.group(0),
            }
        except ValueError:
            pass

    return None


# ─── shot_type extractor ─────────────────────────────────────────
_SHOT_SYNONYMS: list[tuple[str, list[str]]] = [
    ("smash", ["スマッシュ", "smash"]),
    ("clear", ["クリア", "clear"]),
    ("drop", ["ドロップ", "drop"]),
    ("net", ["ネット", "ヘアピン", "net shot", "net"]),
    ("drive", ["ドライブ", "drive"]),
    ("push", ["プッシュ", "push"]),
    ("lob", ["ロブ", "ロビング", "lob"]),
    ("serve", ["サーブ", "serve"]),
]

# 否定パターン: 「<word>以外」「<word>じゃない」「not <word>」「except <word>」
_NEGATION_TEMPLATES_JA = ["{}以外", "{}じゃない", "{}ではない", "{}を除く"]
_NEGATION_TEMPLATES_EN = ["not {}", "except {}", "no {}"]


def _has_negation_around(text: str, word: str) -> bool:
    lower = text.lower()
    w_low = word.lower()
    for tmpl in _NEGATION_TEMPLATES_JA:
        if tmpl.format(word) in text:
            return True
    for tmpl in _NEGATION_TEMPLATES_EN:
        if tmpl.format(w_low) in lower:
            return True
    return False


def extract_shot_type(text: str) -> Optional[dict]:
    if not text:
        return None
    lower = text.lower()
    for code, words in _SHOT_SYNONYMS:
        for w in words:
            wl = w.lower()
            # word-ish match: 日本語はそのまま、英語は word boundary 風に
            if w in text or re.search(r"\b" + re.escape(wl) + r"\b", lower):
                if _has_negation_around(text, w):
                    continue
                return {"code": code, "label": w, "matched_text": w}
    return None


# ─── zone extractor ──────────────────────────────────────────────
# FL=フォア前, FR=バック前 ではない — 本プロジェクトのコート慣習に従い
# F=Front (前), B=Back (奥), L=Left, R=Right の組合せ。
# 「フォア奥」「バック奥」のような日本語は左右情報を伴わないため、
# 直接そのコード (フォア奥 / バック奥) として扱い、便宜上 BR/BL に寄せる
# (右利き選手前提: フォア=右手側=R, バック=左手側=L)。
_ZONE_SYNONYMS: list[tuple[str, list[str], str]] = [
    # (code, synonyms, label_default)
    ("FL", ["FL", "フォア前", "前衛フォア"], "フォア前"),
    ("FR", ["FR", "バック前", "前衛バック"], "バック前"),
    ("BL", ["BL", "フォア奥", "後衛フォア", "フォアサイド奥"], "フォア奥"),
    ("BR", ["BR", "バック奥", "後衛バック", "バックサイド奥"], "バック奥"),
    # 汎用 (奥/前) — ピンポイントの方向が無いので generic フィールドにマップ
    ("FRONT", ["前衛", "ネット前", "前方"], "前"),
    ("BACK", ["後衛", "コート奥", "後方"], "奥"),
    ("SIDE", ["サイドライン際", "サイドライン", "サイド際"], "サイド"),
]


def extract_zone(text: str) -> Optional[dict]:
    if not text:
        return None
    for code, words, label in _ZONE_SYNONYMS:
        for w in words:
            if w in text and not _has_negation_around(text, w):
                return {"code": code, "label": label, "matched_text": w}
    return None


# ─── all-in-one ──────────────────────────────────────────────────
def extract_all(text: str, now: Optional[datetime] = None) -> dict:
    return {
        "period": extract_period(text, now),
        "shot_type": extract_shot_type(text),
        "zone": extract_zone(text),
    }
