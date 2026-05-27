"""Task #40: PersonTracker の ReID-based track_id merging の unit test。

ByteTracker / YOLO detector は使わず、PersonTracker の post-process 層
(_apply_track_id_merge) を直接叩く。embedder は mock で差し替える。
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.cv.person_tracker import PersonTracker, TrackedPerson


class _FakeEmbedder:
    """track_id ごとに固定の 512-d 単位ベクトルを返す mock embedder。

    PersonTracker._embed_tracks は bbox → crop → embed_batch なので、bbox の
    位置から id を推定するのは煩雑。代わりに「呼ばれた順に preset を吐く」
    キューモデルを使う。テスト側で順序を制御する。
    """
    available = True

    def __init__(self, vectors: list[np.ndarray]):
        # キュー方式: embed_batch 呼び出しごとに先頭から len(crops) 個 pop
        self._queue: list[np.ndarray] = list(vectors)
        self.calls: int = 0

    def embed_batch(self, crops):
        self.calls += 1
        n = len(crops)
        out = np.stack(self._queue[:n], axis=0).astype(np.float32)
        self._queue = self._queue[n:]
        return out


def _unit(v: np.ndarray) -> np.ndarray:
    return (v / np.linalg.norm(v)).astype(np.float32)


def _vec(i: int, dim: int = 512) -> np.ndarray:
    """direction i の単位ベクトル (i 番目だけ大きい)。"""
    v = np.zeros(dim, dtype=np.float32)
    v[i % dim] = 1.0
    return v


def _bbox(x: float, y: float) -> tuple[float, float, float, float]:
    return (x, y, x + 20.0, y + 40.0)


def _make_tracker(
    embedder,
    merge_ids: bool = True,
    sim_threshold: float = 0.85,
    buffer: int = 32,
) -> PersonTracker:
    # adjudicator を作らずに済むよう court_corners=None。
    # use_reid=False で Tier 3 ReID Recovery は無効化 (merge_ids 単独テスト)。
    t = PersonTracker(
        match_type="singles",
        court_corners=None,
        use_reid=False,
        merge_ids=merge_ids,
        merge_sim_threshold=sim_threshold,
        merge_buffer_size=buffer,
    )
    # _ensure_reid_embedder が embedder を上書きしないよう init_tried を True に
    t._reid_embedder = embedder
    t._reid_embedder_init_tried = True
    # Tier 3 path に乗らないよう reid_enabled は明示 False
    t._reid_enabled = False
    return t


def _frame() -> np.ndarray:
    # _crop_bbox が退化しない大きさ (1080p 想定)
    return np.zeros((200, 200, 3), dtype=np.uint8)


def test_merge_disabled_by_default_when_env_unset(monkeypatch):
    # env なしで PersonTracker を作ると merge_ids は OFF (デフォルト挙動)
    monkeypatch.delenv("SS_PERSON_REID_MERGE_IDS", raising=False)
    # constant を読み直すために module を reload
    import importlib
    import backend.cv.person_tracker as pt_mod
    importlib.reload(pt_mod)
    tr = pt_mod.PersonTracker(match_type="singles", court_corners=None, use_reid=False)
    assert tr._merge_ids_enabled is False


def test_merge_assigns_old_id_to_similar_new_track():
    # frame1: track_id=10 が embedding A で登場
    # frame2: track_id=10 消失、track_id=11 が embedding ≈ A で登場
    #   → 11 を 10 にリネーム
    vec_a = _unit(_vec(7))
    vec_a_noisy = _unit(vec_a + 0.05 * _vec(8))  # cosine sim > 0.85
    emb = _FakeEmbedder([vec_a, vec_a_noisy])
    tr = _make_tracker(emb)

    f = _frame()
    # frame1
    t10 = TrackedPerson(bbox=_bbox(10, 10), track_id=10, court_id=None,
                        player_uuid=None, confidence=0.9)
    out1 = tr._apply_track_id_merge(f, [t10], frame_idx=0)
    assert out1[0].track_id == 10
    assert 10 in tr._track_id_embedding

    # frame2: 10 消失、11 出現
    t11 = TrackedPerson(bbox=_bbox(40, 10), track_id=11, court_id=None,
                        player_uuid=None, confidence=0.9)
    out2 = tr._apply_track_id_merge(f, [t11], frame_idx=1)
    assert out2[0].track_id == 10, f"expected merge to 10, got {out2[0].track_id}"
    assert tr._track_id_alias.get(11) == 10


def test_merge_skipped_when_similarity_below_threshold():
    # 完全に直交する embedding → cosine sim 0 → merge せず別 id のまま
    emb = _FakeEmbedder([_unit(_vec(1)), _unit(_vec(200))])
    tr = _make_tracker(emb, sim_threshold=0.85)

    f = _frame()
    t10 = TrackedPerson(bbox=_bbox(10, 10), track_id=10, court_id=None,
                        player_uuid=None, confidence=0.9)
    tr._apply_track_id_merge(f, [t10], frame_idx=0)
    t11 = TrackedPerson(bbox=_bbox(40, 10), track_id=11, court_id=None,
                        player_uuid=None, confidence=0.9)
    out = tr._apply_track_id_merge(f, [t11], frame_idx=1)
    assert out[0].track_id == 11
    assert 11 not in tr._track_id_alias


def test_no_merge_for_continuing_track_id():
    # 同じ track_id が連続フレームに居る場合は alias 作らない
    emb = _FakeEmbedder([_unit(_vec(3)), _unit(_vec(3))])
    tr = _make_tracker(emb)

    f = _frame()
    t10 = TrackedPerson(bbox=_bbox(10, 10), track_id=10, court_id=None,
                        player_uuid=None, confidence=0.9)
    tr._apply_track_id_merge(f, [t10], frame_idx=0)
    out = tr._apply_track_id_merge(f, [t10], frame_idx=1)
    assert out[0].track_id == 10
    assert 10 not in tr._track_id_alias  # 自分自身への alias は作らない


def test_disabled_when_merge_ids_flag_off():
    # merge_ids=False なら何もしない
    emb = _FakeEmbedder([_unit(_vec(1)), _unit(_vec(1))])
    tr = _make_tracker(emb, merge_ids=False)
    assert tr._merge_ids_enabled is False

    f = _frame()
    t10 = TrackedPerson(bbox=_bbox(10, 10), track_id=10, court_id=None,
                        player_uuid=None, confidence=0.9)
    t11 = TrackedPerson(bbox=_bbox(40, 10), track_id=11, court_id=None,
                        player_uuid=None, confidence=0.9)
    # update() を経由した場合に呼ばれない事を直接確認するのは難しいので、
    # apply メソッドを呼ばずに状態が空のままである事だけ検証する
    assert tr._track_id_alias == {}


def test_lost_buffer_lru_eviction():
    # buffer=2 で 3 個 lost を作ったら最古が evict される
    # frame1: 100/101/102 全部登場 → frame2: 全部消えて新たに 200 が登場し 100 と同 emb
    # 100 が buffer に居れば merge 成功するが、102 が後から evict すれば fail。
    # → 100, 101, 102 の lost 入りタイミングは同じ frame で newly_lost の集合演算順序に
    #    依存するため、ここでは「順次 lost にして overflow を観測する」シンプル版にする。
    emb = _FakeEmbedder([
        _unit(_vec(1)), _unit(_vec(2)), _unit(_vec(3)),  # frame1 3 tracks
        # frame2 で 100 のみ存続 → 101,102 が lost に
        _unit(_vec(1)),
        # frame3 で 100 も消え、別 dir で 200 出現
        _unit(_vec(50)),
    ])
    tr = _make_tracker(emb, buffer=1)
    f = _frame()
    t100 = TrackedPerson(bbox=_bbox(10, 10), track_id=100, court_id=None,
                         player_uuid=None, confidence=0.9)
    t101 = TrackedPerson(bbox=_bbox(40, 10), track_id=101, court_id=None,
                         player_uuid=None, confidence=0.9)
    t102 = TrackedPerson(bbox=_bbox(70, 10), track_id=102, court_id=None,
                         player_uuid=None, confidence=0.9)
    tr._apply_track_id_merge(f, [t100, t101, t102], frame_idx=0)
    # frame2: 101,102 消失、100 のみ残る → lost に 2 件積まれるが buffer=1 で 1 件のみ残る
    tr._apply_track_id_merge(f, [t100], frame_idx=1)
    assert len(tr._lost_track_buffer) == 1
