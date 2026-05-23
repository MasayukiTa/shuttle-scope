"""Slot extractor unit tests."""
from __future__ import annotations

from datetime import datetime

from backend.analysis.chat.slot_extractors import (
    extract_period,
    extract_shot_type,
    extract_zone,
    extract_all,
)


_NOW = datetime(2026, 5, 23, 12, 0, 0)


# ─── period ──────────────────────────────────────────────────────
def test_period_last_month_ja():
    r = extract_period("先月の伸びしろは?", _NOW)
    assert r is not None
    assert r["date_from"] == "2026-04-01"
    assert r["date_to"] == "2026-04-30"


def test_period_last_month_en():
    r = extract_period("How was last month?", _NOW)
    assert r is not None
    assert r["date_from"] == "2026-04-01"
    assert r["date_to"] == "2026-04-30"


def test_period_recent_3_months():
    r = extract_period("直近3ヶ月のスマッシュ", _NOW)
    assert r is not None
    assert r["date_to"] == "2026-05-23"


def test_period_past_7_days():
    r = extract_period("past 7 days summary", _NOW)
    assert r is not None
    assert r["date_to"] == "2026-05-23"
    assert r["date_from"] == "2026-05-17"


def test_period_today():
    r = extract_period("今日の調子は", _NOW)
    assert r is not None
    assert r["date_from"] == "2026-05-23"
    assert r["date_to"] == "2026-05-23"


def test_period_absolute_range():
    r = extract_period("2026/03/01〜2026/03/31の結果", _NOW)
    assert r is not None
    assert r["date_from"] == "2026-03-01"
    assert r["date_to"] == "2026-03-31"


def test_period_none():
    assert extract_period("ただの質問", _NOW) is None


# ─── shot_type ───────────────────────────────────────────────────
def test_shot_smash_ja():
    r = extract_shot_type("スマッシュの精度は?")
    assert r is not None
    assert r["code"] == "smash"


def test_shot_smash_en():
    r = extract_shot_type("How is my smash today?")
    assert r is not None
    assert r["code"] == "smash"


def test_shot_negation_ja():
    """スマッシュ以外 → smash を positive match しない"""
    assert extract_shot_type("スマッシュ以外のショットは?") is None


def test_shot_negation_en():
    assert extract_shot_type("not smash, the others") is None


def test_shot_net_hairpin():
    r = extract_shot_type("ヘアピンの精度")
    assert r is not None
    assert r["code"] == "net"


def test_shot_none():
    assert extract_shot_type("試合の結果") is None


# ─── zone ────────────────────────────────────────────────────────
def test_zone_back_left():
    r = extract_zone("バック奥の打点は?")
    assert r is not None
    assert r["code"] == "BR"


def test_zone_fore_front():
    r = extract_zone("フォア前の処理")
    assert r is not None
    assert r["code"] == "FL"


def test_zone_generic_back():
    r = extract_zone("コート奥のショット")
    assert r is not None
    assert r["code"] == "BACK"


def test_zone_none():
    assert extract_zone("普通の質問") is None


# ─── extract_all ─────────────────────────────────────────────────
def test_extract_all_combined():
    r = extract_all("先月のスマッシュ、バック奥は?", _NOW)
    assert r["period"] is not None
    assert r["shot_type"]["code"] == "smash"
    assert r["zone"]["code"] == "BR"


def test_extract_all_empty():
    r = extract_all("", _NOW)
    assert r == {"period": None, "shot_type": None, "zone": None}
