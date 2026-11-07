"""idempotency の予約 API (reserve / release / store) の状態遷移テスト。

守りたい性質:
  - reserve は初回 RESERVED、完了前の 2 回目は IN_PROGRESS を返す。
  - release 後は再び RESERVED を取れる (commit 前失敗 -> 再送可)。
  - store 後は REPLAY を返し、本処理を再実行させない。
  - 別ユーザ / 別エンドポイントが同じ key を使うと衝突とみなし RESERVED を
    与えない (IN_PROGRESS)。get_cached がミスマッチ時に None を返して二重副作用を
    許していた穴を踏まない。
  - TTL を過ぎた予約は残骸として奪える。

_db_store / _db_get は本物の AnalysisCache テーブルに触れるため、ここでは
monkeypatch で no-op 化し、in-memory の予約ロジックだけを検証する
(conftest の _reset_idempotency_cache が _records / _reservations を毎回クリアする)。
"""
from __future__ import annotations

import pytest

from backend.utils import idempotency as idem


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    # DB 永続化層を切り、純粋に in-memory の予約/完了ロジックを見る。
    monkeypatch.setattr(idem, "_db_store", lambda rec: None)
    monkeypatch.setattr(idem, "_db_get", lambda key: None)
    yield


def test_first_reserve_is_reserved_second_is_in_progress():
    status, rec = idem.reserve("key-aaaaaaaa", user_id=1, endpoint="batch_save_rally")
    assert status == idem.RESERVED
    assert rec is None

    # 完了前の 2 回目 (同じユーザ・同じエンドポイント) は処理中扱い。
    status2, _ = idem.reserve("key-aaaaaaaa", user_id=1, endpoint="batch_save_rally")
    assert status2 == idem.IN_PROGRESS


def test_release_allows_rereserve():
    k = "key-bbbbbbbb"
    assert idem.reserve(k, 1, "batch_save_rally")[0] == idem.RESERVED
    # commit 前失敗で解放。
    idem.release(k, 1, "batch_save_rally")
    # 再送が予約を取り直せる。
    assert idem.reserve(k, 1, "batch_save_rally")[0] == idem.RESERVED


def test_store_promotes_reservation_to_replay():
    k = "key-cccccccc"
    assert idem.reserve(k, 1, "batch_save_rally")[0] == idem.RESERVED
    idem.store(k, 1, "batch_save_rally", {"success": True, "data": {"rally_id": 7}}, status_code=201)

    status, rec = idem.reserve(k, 1, "batch_save_rally")
    assert status == idem.REPLAY
    assert rec is not None
    assert idem.replay_response(rec)["data"]["rally_id"] == 7


def test_release_does_not_touch_completed_record():
    k = "key-dddddddd"
    idem.reserve(k, 1, "batch_save_rally")
    idem.store(k, 1, "batch_save_rally", {"success": True}, status_code=201)
    # 完了後の release は no-op (完了レコードを壊さない)。
    idem.release(k, 1, "batch_save_rally")
    status, rec = idem.reserve(k, 1, "batch_save_rally")
    assert status == idem.REPLAY
    assert rec is not None


def test_cross_user_key_collision_is_not_granted():
    k = "key-eeeeeeee"
    assert idem.reserve(k, 1, "batch_save_rally")[0] == idem.RESERVED
    # 別ユーザが同じ key を使う -> 予約を与えない (IN_PROGRESS)。
    status, _ = idem.reserve(k, 2, "batch_save_rally")
    assert status == idem.IN_PROGRESS


def test_cross_endpoint_completed_record_is_not_replayed():
    k = "key-ffffffff"
    idem.reserve(k, 1, "batch_save_rally")
    idem.store(k, 1, "batch_save_rally", {"success": True}, status_code=201)
    # 同じ key を別エンドポイントで使う -> replay させない (衝突扱い)。
    status, rec = idem.reserve(k, 1, "create_stroke:5")
    assert status == idem.IN_PROGRESS
    assert rec is None


def test_stale_reservation_can_be_taken_over(monkeypatch):
    k = "key-gggggggg"
    assert idem.reserve(k, 1, "batch_save_rally")[0] == idem.RESERVED
    # 予約を TTL より前の時刻に押し戻し、残骸にする。
    resv = idem._reservations[k]
    resv.reserved_at -= idem._RESERVATION_TTL_SECONDS + 1
    # 別処理が奪える。
    status, _ = idem.reserve(k, 1, "batch_save_rally")
    assert status == idem.RESERVED
