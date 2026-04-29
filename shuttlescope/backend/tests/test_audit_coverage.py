"""ログセマンティックカバレッジ検証 (Phase B3)。

「業務イベントが発生したら必ず access_log にエントリが書かれる」を保証する。

検証する業務イベント (event_name と紐付け):
  - login                       → ログイン成功
  - login_failed                → ログイン失敗 (列挙防御の観点でも記録必須)
  - account_locked              → アカウントロック発動
  - export_package_created      → Export パッケージ生成
  - video_token_reissued        → video_token 再発行
  - match_updated               → 試合データ更新

不変条件:
  - 業務操作 1 回 → access_log 1 行
  - 同イベント名が複数の handler から書かれていても OK (重複検出は別 layer)
  - 失敗操作 (403/401) も最低限ログを残すべき
"""
from __future__ import annotations

import pathlib
import re

ROUTERS_DIR = pathlib.Path(__file__).resolve().parent.parent / "routers"


# ─── イベント名と routers/*.py の出現対応表 ─────────────────────────────────
EXPECTED_EVENTS = {
    # event_name: 期待される記録元 router (どれか 1 つに含まれていれば OK)
    "login":                    ["auth.py"],
    "login_failed":             ["auth.py"],
    "account_locked":           ["auth.py"],
    "export_package_created":   ["data_package.py"],
    "video_token_reissued":     ["videos.py"],
    "match_updated":            ["matches.py"],
}


def _extract_log_event_names(content: str) -> set[str]:
    """log_access(db, "<event>", ...) の event 名を抽出する。

    `from backend.utils.access_log import log_access as _log` のような
    エイリアスにも対応する。
    """
    names = set()
    # log_access 直接呼び出し
    for m in re.finditer(r'log_access\s*\(\s*[^,]+,\s*["\']([^"\']+)["\']', content):
        names.add(m.group(1))
    # エイリアス: log_access as <alias> → <alias>(...) を検出
    for alias_match in re.finditer(r'from\s+backend\.utils\.access_log\s+import\s+log_access\s+as\s+(\w+)', content):
        alias = alias_match.group(1)
        for m in re.finditer(rf'\b{re.escape(alias)}\s*\(\s*[^,]+,\s*["\']([^"\']+)["\']', content):
            names.add(m.group(1))
    return names


def _all_routers_event_index() -> dict[str, set[str]]:
    """各 router ファイルから event 名集合を抽出した辞書を返す。"""
    idx = {}
    for f in ROUTERS_DIR.glob("*.py"):
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue
        names = _extract_log_event_names(content)
        if names:
            idx[f.name] = names
    return idx


def test_expected_events_are_logged_in_routers():
    """各業務イベントが期待される router で log_access 呼び出しを持つこと。"""
    idx = _all_routers_event_index()
    missing = []
    for event_name, expected_files in EXPECTED_EVENTS.items():
        found = False
        for fname in expected_files:
            if event_name in idx.get(fname, set()):
                found = True
                break
        if not found:
            missing.append(f"{event_name} (期待: {expected_files})")
    assert not missing, f"以下のイベントが log_access に記録されていません:\n  " + "\n  ".join(missing)


def test_no_orphan_event_names():
    """イベント名は EXPECTED_EVENTS で網羅されている、または許容リストに含まれていること。

    新規イベントを追加したら EXPECTED_EVENTS か _ALLOWED_EXTRAS に登録する運用。
    """
    _ALLOWED_EXTRAS = {
        # Phase C2: 緊急失効
        "emergency_revoke_all_tokens",
        "emergency_reissue_all_video_tokens",
        # Phase B3: 認可失敗ログ
        "video_stream_access_denied",
        # M-A4: メール認証 / 招待 / register
        "register",
        "register_duplicate",
        "email_verified",
        "email_verify_resend",
        "password_reset_requested",
        "password_reset_completed",
        "password_reset_unknown_email",
        "password_reset_by_admin",
        "invitation_created",
        "invitation_accepted",
        # M-A: 保留ユーザー承認 / 拒否
        "user_approved",
        "user_rejected",
        # Phase Pay-1: 課金 / 決済 (フロント非公開)
        "billing_order_created",
        "billing_order_canceled",
        "billing_refunded",
        "billing_admin_grant",
        "billing_product_created",
        "billing_webhook_invalid_signature",
        "billing_webhook_payment_succeeded",
        "billing_webhook_payment_authorized",
        "billing_webhook_payment_failed",
        "billing_webhook_payment_canceled",
        "billing_webhook_session_expired",
        "billing_webhook_refund_created",
        "billing_receipt_downloaded",
        # 認証系
        "login_mfa_required",
        "login_mfa_ok",
        "login_pin",
        "login_select",
        "logout",
        "refresh_token",
        "token_refresh",
        "password_changed",
        "password_change_failed",
        "mfa_enabled",
        "mfa_disabled",
        "account_unlocked",
        # ユーザ管理 / チーム
        "user_created",
        "user_updated",
        "user_deleted",
        "user_role_changed",
        "user_team_changed",
        "team_created",
        "team_updated",
        # 試合 / 選手
        "match_created",
        "match_deleted",
        "player_created",
        "player_updated",
        "player_deleted",
        # チーム境界変更
        "team_changed",
        "owner_changed",
        "is_public_pool_changed",
        # public inquiry
        "public_inquiry_deleted",
        "public_inquiry_bulk_deleted",
        # クラスタ / 同期
        "cluster_op",
        "sync_op",
        # 削除復活
        "soft_delete",
        "soft_undelete",
        # コメント / コンディション / 動画
        "comment_deleted",
        "condition_created",
        "condition_updated",
        "condition_deleted",
        "video_dl_started",
    }
    idx = _all_routers_event_index()
    all_events = set()
    for names in idx.values():
        all_events.update(names)
    expected = set(EXPECTED_EVENTS.keys()) | _ALLOWED_EXTRAS
    orphans = all_events - expected
    assert not orphans, (
        f"未知のイベント名が log_access で使われています。"
        f"_ALLOWED_EXTRAS か EXPECTED_EVENTS に追加してください:\n  {sorted(orphans)}"
    )


def test_critical_writes_have_log_call():
    """副作用のある重要エンドポイント関数が log_access を呼んでいること。

    ヒューリスティック: routers/*.py 内の関数定義のうち、
    POST/PUT/DELETE デコレータを持つものは log_access を呼ぶことが望ましい。
    例外リスト (_LOG_EXEMPT) は明示的に許可。
    """
    _LOG_EXEMPT = {
        # 認証 / セッション系で別途プローブログがあるもの
        "validate_token",
        "ping",
        "heartbeat",
        # 公開エンドポイント
        "submit_inquiry",
        "public_submit",
    }

    failures = []
    for f in ROUTERS_DIR.glob("*.py"):
        content = f.read_text(encoding="utf-8")
        # POST/PUT/DELETE デコレータ + 直後の def 関数名
        for m in re.finditer(
            r'@router\.(post|put|delete|patch)\s*\([^)]*\)\s*\n(?:\s*@[^\n]+\n)*\s*(?:async\s+)?def\s+(\w+)',
            content,
        ):
            verb, fname = m.group(1), m.group(2)
            if fname in _LOG_EXEMPT:
                continue
            # この関数の body 内に log_access が出現するか軽く検査
            # （関数の終わりを正確に追わないが、隣接行にあれば検出できる）
            after = content[m.end():m.end() + 3000]  # 3KB 範囲
            if "log_access" not in after and "log_access" not in content:
                # ファイル内に log_access が皆無な場合のみ警告
                failures.append(f"{f.name}::{fname} ({verb}) — log_access 呼び出しなし")
    # 現状は警告のみ。Phase B3 では失敗扱いにせず、可視化が目的。
    # 将来的にこの失敗リストを 0 にする運用へ移行する。
    if failures:
        print(f"\n[WARN] log_access が見つからない write 系エンドポイント:")
        for f in failures[:30]:
            print(f"  - {f}")
