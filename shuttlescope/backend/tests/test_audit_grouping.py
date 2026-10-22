"""audit_grouping の純粋関数のテスト (DB 不要)。"""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.utils.audit_grouping import (
    error_fingerprint,
    group_error_rows,
    group_security_rows,
    is_monitoring_self_read,
    summarize_error_message,
)

_SQL_ERROR = (
    '(psycopg2.errors.ForeignKeyViolation) insert or update on table "users" '
    'violates foreign key constraint "users_team_id_fkey"\n'
    "DETAIL:  Key (team_id)=(9) is not present in table \"teams\".\n\n"
    "[SQL: UPDATE users SET team_id=%(team_id)s WHERE users.id = %(users_id)s]\n"
    "[parameters: {'team_id': 9, 'users_id': 4}]\n"
    "(Background on this error at: https://sqlalche.me/e/20/gkpj)"
)


def test_monitoring_self_read_only_for_successful_get():
    path = "/api/auth/audit-logs/security"
    assert is_monitoring_self_read("GET", path, 200) is True
    # 失敗は監視 API を探った記録として残す
    assert is_monitoring_self_read("GET", path, 403) is False
    assert is_monitoring_self_read("GET", path, 401) is False
    # GET 以外・別 path は対象外
    assert is_monitoring_self_read("POST", path, 200) is False
    assert is_monitoring_self_read("GET", "/api/matches", 200) is False
    assert is_monitoring_self_read("GET", path, None) is False


def test_summary_drops_sql_parameters_and_links():
    s = summarize_error_message(_SQL_ERROR)
    assert s is not None
    assert "[SQL:" not in s
    assert "[parameters:" not in s
    assert "sqlalche.me" not in s
    assert "UPDATE users" not in s
    assert s.startswith("(psycopg2.errors.ForeignKeyViolation)")


def test_summary_of_plain_and_empty_messages():
    assert summarize_error_message("'Depends' object has no attribute 'get'") == (
        "'Depends' object has no attribute 'get'"
    )
    assert summarize_error_message("") is None
    assert summarize_error_message(None) is None
    assert summarize_error_message("\n\n") is None
    long = summarize_error_message("x" * 500, max_len=50)
    assert long is not None and len(long) == 50


def test_fingerprint_ignores_ids_and_numbers_but_not_type():
    a = error_fingerprint("ValueError", "GET", "/api/matches/12", "bad id 12")
    b = error_fingerprint("ValueError", "GET", "/api/matches/345", "bad id 345")
    assert a == b
    assert a != error_fingerprint("KeyError", "GET", "/api/matches/12", "bad id 12")
    assert a != error_fingerprint("ValueError", "GET", "/api/players/12", "bad id 12")


def test_group_error_rows_counts_and_first_last():
    base = datetime(2026, 10, 1, 12, 0, 0)
    msg = "'Depends' object has no attribute 'get'"
    rows = [  # 新しい順
        {"id": 3, "ts": base + timedelta(hours=2), "exc_type": "AttributeError", "method": "GET",
         "path": "/api/db/status", "message": msg, "request_id": "r3", "status": 500},
        {"id": 2, "ts": base + timedelta(hours=1), "exc_type": "ValueError", "method": "GET",
         "path": "/api/other", "message": "x", "request_id": "r2", "status": 500},
        {"id": 1, "ts": base, "exc_type": "AttributeError", "method": "GET",
         "path": "/api/db/status", "message": msg, "request_id": "r1", "status": 500},
    ]
    groups = group_error_rows(rows)
    assert len(groups) == 2
    top = groups[0]
    assert top["exc_type"] == "AttributeError"
    assert top["count"] == 2
    assert top["first_ts"] == base
    assert top["last_ts"] == base + timedelta(hours=2)
    assert top["last_request_id"] == "r3"
    assert groups[1]["count"] == 1


def test_group_security_rows_folds_one_burst():
    base = datetime(2026, 10, 1, 12, 0, 0)
    rows = []
    # 同じ ip の 1 回のスキャン: 30 行が 1 秒おき
    for i in range(30):
        rows.append({"id": 100 - i, "ts": base + timedelta(seconds=30 - i), "ip_addr": "10.0.0.1",
                     "event_type": "probe_attempt", "severity": "warn", "path": f"/p{i}"})
    # 別の ip の 1 件
    rows.append({"id": 50, "ts": base, "ip_addr": "10.0.0.2", "event_type": "rate_limit_hit",
                 "severity": "critical", "path": "/api/login"})
    groups = group_security_rows(rows, gap_seconds=300)
    assert len(groups) == 2
    burst = next(g for g in groups if g["ip_addr"] == "10.0.0.1")
    assert burst["count"] == 30
    assert burst["distinct_paths"] == 30
    assert len(burst["sample_paths"]) == 5
    assert burst["first_ts"] == base + timedelta(seconds=1)
    assert burst["last_ts"] == base + timedelta(seconds=30)
    assert "_paths" not in burst


def test_group_security_rows_splits_on_long_gap_and_takes_max_severity():
    base = datetime(2026, 10, 1, 12, 0, 0)
    rows = [  # 新しい順
        {"id": 3, "ts": base + timedelta(hours=3), "ip_addr": "10.0.0.1", "event_type": "probe_attempt",
         "severity": "info", "path": "/a"},
        {"id": 2, "ts": base + timedelta(seconds=10), "ip_addr": "10.0.0.1", "event_type": "probe_attempt",
         "severity": "critical", "path": "/b"},
        {"id": 1, "ts": base, "ip_addr": "10.0.0.1", "event_type": "probe_attempt",
         "severity": "warn", "path": "/c"},
    ]
    groups = group_security_rows(rows, gap_seconds=300)
    assert [g["count"] for g in groups] == [1, 2]
    assert groups[1]["severity"] == "critical"
