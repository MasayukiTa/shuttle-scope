"""S-6: シグナリング層が approval_status / viewer_permission を一度も見ていなかった。

`backend/ws/` に `approval_status` の参照が 1 件も無い状態だった。
つまり **operator の「拒否」ボタンはシグナリングに対して無力**で、
`pending`（既定値）のままの端末も、明示的に `rejected` された端末も、
接続して配信できた。

入場券の発行側 (`POST /sessions/{code}/ws-ticket`) には検査があったが、
そこも `role` が `str` だったため **`role="operator"` を送ると
`if body.role == "device"` にも `"viewer"` にも入らず、承認検査を
一つも通らずに券が出ていた**（その券は WS 側の対応表で device 扱いになる）。

さらに券を使わない JWT 経路は、クライアントが送った `participant_id` を
そのまま採用していた。`SessionParticipant` に `user_id` は無く、JWT の
持ち主とその行を結びつけるものが無いので、**session_code を知る
認証済み利用者なら誰でも他人の端末になりすませた**。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.routers.sessions import WsTicketRequest


class TestTheTicketRoleIsAClosedSet:
    """未知の role で券を出さない（承認検査を素通りする経路を閉じる）。"""

    @pytest.mark.parametrize("role", ["device", "viewer"])
    def test_the_two_real_roles_are_accepted(self, role):
        body = WsTicketRequest(participant_id=1, participant_token="x" * 16, role=role)
        assert body.role == role

    @pytest.mark.parametrize("role", ["operator", "Device", "admin", "", "devicex"])
    def test_anything_else_is_refused(self, role):
        """特に `operator`: どちらの分岐にも入らないので検査を一つも通らなかった。"""
        with pytest.raises(ValidationError):
            WsTicketRequest(participant_id=1, participant_token="x" * 16, role=role)


class TestTheHandlerChecksApproval:
    """ハンドラ側に承認検査が在ること。

    入場券の検査は発行時の 1 回きりで、券は 30 秒有効。発行後の拒否は
    反映されないし、JWT 経路は券を通らない。接続を張る側で見るのが正しい。
    """

    def test_approval_status_is_read_in_the_ws_layer(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "ws" / "camera.py").read_text(encoding="utf-8")
        assert "approval_status" in src, "WS 層が approval_status を見ていない"
        assert "approved" in src

    def test_viewer_permission_is_read_in_the_ws_layer(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "ws" / "camera.py").read_text(encoding="utf-8")
        assert "viewer_permission" in src, "WS 層が viewer_permission を見ていない"


class TestTheJwtPathNoLongerTakesAClientSuppliedParticipant:
    """JWT だけで device / viewer として繋げないこと。

    「アプリの JWT を持っている」ことは「participant N を支配している」
    ことの証拠にならない。両者を結ぶ列が存在しないので、サーバには
    区別する手段がない。
    """

    def test_main_refuses_participant_id_without_a_ticket(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "main.py").read_text(encoding="utf-8")
        # 券経路を抜けたあとに participant_id / viewer_id を閉じる枝がある
        assert 'reason="device / viewer は入場券が必要です' in src or \
               "入場券が必要です" in src, "JWT 経路が participant_id をまだ受けている"
