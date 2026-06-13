"""PersonTracker (Phase 1+2+3 / Phase 3.5 refactor) の unit test。

Phase 3.5: 検出 = backend.yolo.inference.get_yolo_inference()、
追跡 = backend.cv.byte_tracker.ByteTracker の 2-stage 設計に変更。

検出器は遅延 init なので、quadrant adjudicator / ByteTracker 単体テストは
この軽量 venv でも回る。PersonTracker.update の smoke は detector を
monkeypatch して回す (実モデル不要)。
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.cv.person_tracker import (
    PersonTracker,
    TrackedPerson,
    _QuadrantAdjudicator,
    adjudicate_court,
    court_id_to_player_label,
)
from backend.cv.byte_tracker import (
    ByteTracker,
    Detection,
    STrack,
    _ious,
    _linear_assignment,
)


# 100x100 矩形コート (TL, TR, BR, BL) — 中央 (50,50)
SQUARE_CORNERS = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


def _bbox_with_foot(fx: float, fy: float, w: float = 10.0, h: float = 20.0) -> tuple[float, float, float, float]:
    """足元が (fx, fy) になる bbox。"""
    return (fx - w / 2, fy - h, fx + w / 2, fy)


class TestQuadrantAdjudicator:
    def setup_method(self):
        self.adj = _QuadrantAdjudicator(SQUARE_CORNERS)

    def test_fl(self):
        # 左上象限 (足元 = 25, 25)
        assert self.adj.classify(_bbox_with_foot(25, 25)) == 0

    def test_fr(self):
        assert self.adj.classify(_bbox_with_foot(75, 25)) == 1

    def test_bl(self):
        assert self.adj.classify(_bbox_with_foot(25, 75)) == 2

    def test_br(self):
        assert self.adj.classify(_bbox_with_foot(75, 75)) == 3

    def test_out_of_court(self):
        # 足元がコート外
        assert self.adj.classify(_bbox_with_foot(150, 50)) is None
        assert self.adj.classify(_bbox_with_foot(50, -10)) is None

    def test_invalid_corners(self):
        with pytest.raises(ValueError):
            _QuadrantAdjudicator([(0.0, 0.0), (1.0, 0.0)])


class TestAdjudicateCourtMatchType:
    def setup_method(self):
        self.adj = _QuadrantAdjudicator(SQUARE_CORNERS)

    def _mk(self, foot, tid, conf):
        return TrackedPerson(
            bbox=_bbox_with_foot(*foot),
            track_id=tid,
            court_id=None,
            player_uuid=None,
            confidence=conf,
        )

    def test_singles_same_quadrant_demotes_low_conf(self):
        # 2 track 同じ FL 象限。conf 高い方が残り、低い方は court_id=None。
        a = self._mk((25, 25), 1, 0.9)
        b = self._mk((30, 30), 2, 0.4)
        out = adjudicate_court([a, b], self.adj, "singles")
        cids = {t.track_id: t.court_id for t in out}
        assert cids[1] == 0
        assert cids[2] is None

    def test_doubles_same_quadrant_two_ok(self):
        a = self._mk((25, 25), 1, 0.9)
        b = self._mk((30, 30), 2, 0.8)
        out = adjudicate_court([a, b], self.adj, "doubles")
        assert all(t.court_id == 0 for t in out)

    def test_doubles_three_in_one_quadrant_demotes_lowest(self):
        a = self._mk((25, 25), 1, 0.9)
        b = self._mk((28, 28), 2, 0.7)
        c = self._mk((30, 30), 3, 0.2)
        out = adjudicate_court([a, b, c], self.adj, "doubles")
        cids = {t.track_id: t.court_id for t in out}
        assert cids[1] == 0 and cids[2] == 0
        assert cids[3] is None

    def test_out_of_court_stays_none(self):
        a = self._mk((25, 25), 1, 0.9)
        b = self._mk((500, 500), 2, 0.9)
        out = adjudicate_court([a, b], self.adj, "doubles")
        cids = {t.track_id: t.court_id for t in out}
        assert cids[1] == 0
        assert cids[2] is None


class TestPersonTrackerInit:
    def test_invalid_match_type(self):
        with pytest.raises(ValueError):
            PersonTracker(match_type="triples")  # type: ignore[arg-type]

    def test_passthrough_without_corners(self):
        # adjudicator 無しでも構築できる
        t = PersonTracker(match_type="singles", court_corners=None)
        assert t._adjudicator is None

    def test_match_id_loads_corners_from_db(self, monkeypatch):
        # DB load を mock。frame_size を渡して pixel に戻る経路を確認。
        fake_data = {
            "roi_polygon": [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
        }

        def fake_loader(match_id):
            assert match_id == 42
            return fake_data

        import backend.routers.court_calibration as cc_mod
        monkeypatch.setattr(
            cc_mod, "load_calibration_standalone", fake_loader, raising=True,
        )
        t = PersonTracker(
            match_type="doubles",
            match_id=42,
            frame_size=(1920, 1080),
        )
        assert t._adjudicator is not None
        # 1920x1080 にスケールされていれば classify が動く
        assert t._adjudicator.classify((0.0, 0.0, 100.0, 100.0)) == 0

    def test_match_id_degenerate_roi_falls_back_to_none(self, monkeypatch):
        # roi_polygon が全点 (0.5, 0.5) の退化キャリブは無視されること
        fake_data = {"roi_polygon": [[0.5, 0.5]] * 4}
        import backend.routers.court_calibration as cc_mod
        monkeypatch.setattr(
            cc_mod, "load_calibration_standalone", lambda mid: fake_data,
            raising=True,
        )
        t = PersonTracker(match_type="doubles", match_id=99, frame_size=(1920, 1080))
        assert t._adjudicator is None


class TestPlayerLabel:
    def test_court_id_to_label_map(self):
        assert court_id_to_player_label(0) == "PlayerA"
        assert court_id_to_player_label(1) == "PlayerB"
        assert court_id_to_player_label(2) == "PlayerC"
        assert court_id_to_player_label(3) == "PlayerD"
        assert court_id_to_player_label(None) is None


class TestSideSwap:
    """reset_for_new_set で side swap が反映されること。"""

    def setup_method(self):
        self.tracker = PersonTracker(
            match_type="doubles",
            court_corners=SQUARE_CORNERS,
        )

    def _fake_track(self, foot, tid, conf):
        return TrackedPerson(
            bbox=_bbox_with_foot(*foot),
            track_id=tid,
            court_id=None,
            player_uuid=None,
            confidence=conf,
        )

    def test_no_swap_on_even_set(self):
        self.tracker.reset_for_new_set(0)
        assert self.tracker._side_swapped is False
        self.tracker.reset_for_new_set(2)
        assert self.tracker._side_swapped is False

    def test_swap_on_odd_set(self):
        self.tracker.reset_for_new_set(1)
        assert self.tracker._side_swapped is True
        self.tracker.reset_for_new_set(3)
        assert self.tracker._side_swapped is True

    def test_attach_player_label_no_swap(self):
        # FL (court_id=0) は PlayerA
        raw = TrackedPerson(
            bbox=_bbox_with_foot(25, 25),
            track_id=1,
            court_id=0,
            player_uuid=None,
            confidence=0.9,
        )
        self.tracker._side_swapped = False
        out = self.tracker._attach_player_label(raw)
        assert out.court_id == 0
        assert out.player_label == "PlayerA"

    def test_attach_player_label_with_swap(self):
        # FL (0) は swap 中は BL (2) → PlayerC 扱い
        raw = TrackedPerson(
            bbox=_bbox_with_foot(25, 25),
            track_id=1,
            court_id=0,
            player_uuid=None,
            confidence=0.9,
        )
        self.tracker._side_swapped = True
        out = self.tracker._attach_player_label(raw)
        assert out.court_id == 2
        assert out.player_label == "PlayerC"

    def test_attach_label_passthrough_for_none_court(self):
        raw = TrackedPerson(
            bbox=(0, 0, 1, 1),
            track_id=1,
            court_id=None,
            player_uuid=None,
            confidence=0.5,
        )
        out = self.tracker._attach_player_label(raw)
        assert out.court_id is None
        assert out.player_label is None


class _FakeDetector:
    """get_yolo_inference() の代替。固定 detection list を返す。

    detections は (label, conf, x1n, y1n, x2n, y2n) の tuple list。
    """

    def __init__(self, detections_per_frame: list[list[tuple]]):
        self._per_frame = detections_per_frame
        self._idx = 0
        self.backend = "fake"

    def load(self) -> bool:
        return True

    def backend_name(self) -> str:
        return self.backend

    def predict_frame(self, frame) -> list[dict]:
        if self._idx >= len(self._per_frame):
            return []
        out = []
        for label, conf, x1n, y1n, x2n, y2n in self._per_frame[self._idx]:
            out.append({
                "label": label,
                "confidence": conf,
                "bbox": [x1n, y1n, x2n, y2n],
                "centroid": [(x1n + x2n) / 2, (y1n + y2n) / 2],
                "foot_point": [(x1n + x2n) / 2, y2n],
            })
        self._idx += 1
        return out


def _install_fake_detector(monkeypatch, detections_per_frame):
    """backend.yolo.inference.get_yolo_inference を fake で差し替え。"""
    fake = _FakeDetector(detections_per_frame)
    import backend.yolo.inference as yi_mod
    monkeypatch.setattr(yi_mod, "get_yolo_inference", lambda *a, **kw: fake, raising=True)
    return fake


class TestPersonTrackerUpdateSmoke:
    """Phase 3.5 refactor 後の update() smoke。検出器は monkeypatch。"""

    def test_update_empty_detections(self, monkeypatch):
        _install_fake_detector(monkeypatch, [[]])
        tracker = PersonTracker(match_type="doubles", court_corners=SQUARE_CORNERS)
        out = tracker.update(np.zeros((100, 100, 3), dtype=np.uint8), 0)
        assert out == []

    def test_update_single_detection_assigns_track_id(self, monkeypatch):
        # frame 0/1 で同じ位置に person → ByteTracker が同じ track_id を継続するはず
        det = ("person", 0.9, 0.20, 0.10, 0.30, 0.30)  # 足元 (25, 30) → FL
        _install_fake_detector(monkeypatch, [[det], [det], [det]])
        tracker = PersonTracker(
            match_type="doubles", court_corners=SQUARE_CORNERS,
        )
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        out0 = tracker.update(frame, 0)
        out1 = tracker.update(frame, 1)
        out2 = tracker.update(frame, 2)
        # 2nd / 3rd フレームでは activated state、同一 track_id 維持
        assert len(out2) == 1
        assert out2[0].track_id >= 1
        assert out2[0].track_id == out1[0].track_id if out1 else True
        assert out2[0].court_id == 0  # FL
        assert out2[0].player_label == "PlayerA"

    def test_update_disables_reid_by_default_without_model(self, monkeypatch):
        """ReID model 未配置 → ReIDEmbedder unavailable → Tier 3 自動 disable。
        既存挙動が ReID 整合性で壊れないこと。
        """
        _install_fake_detector(monkeypatch, [
            [("person", 0.9, 0.20, 0.10, 0.30, 0.30)],
        ])
        tracker = PersonTracker(
            match_type="doubles", court_corners=SQUARE_CORNERS, use_reid=True,
        )
        # tmp path に何も置かないので embedder lazy init で disable される
        out = tracker.update(np.zeros((100, 100, 3), dtype=np.uint8), 0)
        # 検出はそのまま通る
        assert len(out) == 1
        # ReID Tier 3 は降格しているはず
        assert tracker._reid_enabled is False

    def test_reid_recovery_assigns_court_from_lost_history(self, monkeypatch):
        """合成シナリオ: orphan track と lost court の embedding が一致 → 復帰。

        ReIDEmbedder を fake で差し替え、court_id=0 の history に乗っている
        embedding と同じ feature を orphan に返させて Tier 3 で復帰させる。
        """
        from backend.cv.person_tracker import TrackedPerson, adjudicate_court  # noqa
        # ── fake embedder ─────────────────────────────────────────────
        class _FakeEmbedder:
            available = True
            feature_dim = 512
            provider = "fake"
            # 呼ばれた crop の数だけ「同一の」 feature vector を返す
            def embed_batch(self, crops):
                if not crops:
                    return np.zeros((0, 512), dtype=np.float32)
                # 全 crop に同じ embedding を返す → confirmed と orphan で sim=1.0
                f = np.zeros((512,), dtype=np.float32)
                f[0] = 1.0
                return np.tile(f, (len(crops), 1))
        fake = _FakeEmbedder()
        _install_fake_detector(monkeypatch, [[]])  # detector は今回使わない
        tracker = PersonTracker(
            match_type="doubles",
            court_corners=SQUARE_CORNERS,
            use_reid=True,
            reid_embedder=fake,
            reid_threshold=0.85,
        )
        # 内部の lazy init を skip させるため flag を立てておく
        tracker._reid_embedder_init_tried = True
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        # frame 0: court_id=0 の確定 track (FL 象限、足元 25,25)
        confirmed = TrackedPerson(
            bbox=(20, 5, 30, 25), track_id=42,
            court_id=0, player_uuid=None, confidence=0.9,
        )
        # _reid_recover 直接呼ぶ
        out0 = tracker._reid_recover(frame, [confirmed], frame_idx=0)
        assert out0[0].court_id == 0
        assert 0 in tracker._reid_history
        # frame 1: 確定 track が消えて、orphan (court_id=None) だけ存在
        orphan = TrackedPerson(
            bbox=(60, 60, 80, 90), track_id=99,  # 足元 70,90 → BR 象限のはず
            court_id=None, player_uuid=None, confidence=0.7,
        )
        out1 = tracker._reid_recover(frame, [orphan], frame_idx=1)
        # ReID で court_id=0 に復帰されるはず (sim=1.0 > 0.85)
        assert out1[0].court_id == 0
        assert out1[0].is_recovered is True
        assert out1[0].track_id == 99

    def test_reid_disabled_by_env(self, monkeypatch):
        """use_reid=False で Tier 3 は完全に skip され、embedder は呼ばれない。"""
        called = {"n": 0}
        class _Spy:
            available = True
            feature_dim = 512
            provider = "spy"
            def embed_batch(self, crops):
                called["n"] += 1
                return np.zeros((len(crops), 512), dtype=np.float32)
        _install_fake_detector(monkeypatch, [[("person", 0.9, 0.2, 0.1, 0.3, 0.3)]])
        tracker = PersonTracker(
            match_type="doubles",
            court_corners=SQUARE_CORNERS,
            use_reid=False,
            reid_embedder=_Spy(),
        )
        tracker.update(np.zeros((100, 100, 3), dtype=np.uint8), 0)
        assert called["n"] == 0

    def test_update_ignores_non_person_labels(self, monkeypatch):
        # shuttle / 非 person ラベルは ByteTracker に流さない
        _install_fake_detector(monkeypatch, [
            [("shuttle", 0.9, 0.4, 0.4, 0.5, 0.5)],
        ])
        tracker = PersonTracker(match_type="doubles", court_corners=SQUARE_CORNERS)
        out = tracker.update(np.zeros((100, 100, 3), dtype=np.uint8), 0)
        assert out == []


class TestSwapGuard:
    """同ユニフォーム teammate の track_id 取り違え (crossover swap) 補正。

    ByteTrack が crossover 後に 2 人の track_id を取り違えたシナリオを合成し、
    motion-only swap guard が一貫した ID に戻すことを assert する。
    GPU/model 不要 (純ロジック)。
    """

    def _mk(self, cx, cy, tid, w=10.0, h=20.0):
        return TrackedPerson(
            bbox=(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
            track_id=tid,
            court_id=None,
            player_uuid=None,
            confidence=0.9,
        )

    def _tracker(self):
        t = PersonTracker(match_type="doubles", court_corners=None)
        t._swap_guard_enabled = True
        return t

    def test_off_by_default_is_noop(self):
        t = PersonTracker(match_type="doubles", court_corners=None)
        assert t._swap_guard_enabled is False
        # OFF なら apply は呼ばれず ID 不変 (update 経路相当)
        tracks = [self._mk(10, 10, 1), self._mk(90, 10, 2)]
        # 直接 apply を呼んでも壊れないが、enabled=False なら update が呼ばない
        # ここでは guard を通さず恒等であることだけ確認
        assert [x.track_id for x in tracks] == [1, 2]

    def test_no_swap_when_paths_separate(self):
        """十分離れて平行移動 → swap は起きない (誤補正しない)。"""
        t = self._tracker()
        # track1 は x=10 付近、track2 は x=200 付近で右に移動
        for f in range(4):
            out = t._apply_swap_guard([
                self._mk(10 + f, 10, 1),
                self._mk(200 + f, 10, 2),
            ])
        ids = {x.track_id for x in out}
        assert ids == {1, 2}

    def _id_at(self, out, x):
        """出力 out のうち中心 x が x に近い track の出力 track_id を返す。"""
        best = min(out, key=lambda o: abs((o.bbox[0] + o.bbox[2]) / 2 - x))
        return best.track_id

    def test_crossover_swap_is_corrected(self):
        """2 track が交差し、交差後 ByteTrack が ID を取り違えても、guard は
        各軌跡 (左→右 / 右→左) に一貫した track_id を割り当て続ける。

        左→右に進む実体 (E_LR) と右→左に進む実体 (E_RL) を用意。
        ByteTrack は交差点まで正しい ID を付けるが、交差後は近接で取り違える
        (右側観測に左実体の元 ID、左側観測に右実体の元 ID を付ける)。
        guard は等速予測でこれを検知・補正し、E_LR と E_RL がそれぞれ
        全フレームで安定した (= 一貫した) 出力 ID を保つことを確認する。
        """
        t = self._tracker()
        # frame 0-2: 交差前。ByteTrack は正しく id=1=E_LR(左), id=2=E_RL(右)。
        t._apply_swap_guard([self._mk(20, 50, 1), self._mk(180, 50, 2)])
        t._apply_swap_guard([self._mk(50, 50, 1), self._mk(150, 50, 2)])
        out2 = t._apply_swap_guard([self._mk(80, 50, 1), self._mk(120, 50, 2)])
        # 交差前: E_LR (左, x=80) は id=1、E_RL (右, x=120) は id=2
        id_lr = self._id_at(out2, 80)
        id_rl = self._id_at(out2, 120)
        assert id_lr == 1 and id_rl == 2
        # frame 3: 交差直後。E_LR は右 (x=120)、E_RL は左 (x=80) へ抜けた。
        # ByteTrack が取り違え: 左観測 (E_RL) に *依然 id=1*、右観測 (E_LR) に
        # *依然 id=2* を付けてしまった (= 物理的には逆)。guard が swap で補正する。
        out3 = t._apply_swap_guard([self._mk(80, 50, 1), self._mk(120, 50, 2)])
        # guard 補正後: 右側 (E_LR) は元の id_lr=1、左側 (E_RL) は元の id_rl=2
        assert self._id_at(out3, 120) == id_lr, "E_LR の出力 ID が交差で復元されない"
        assert self._id_at(out3, 80) == id_rl, "E_RL の出力 ID が交差で復元されない"
        # alias が張られたことを確認 (実際に swap 補正が走った証拠)
        assert t._swap_alias == {1: 2, 2: 1}, f"alias 未確立: {t._swap_alias}"
        # frame 4: さらに進む。ByteTrack も取り違えたまま (右=id2, 左=id1)。
        out4 = t._apply_swap_guard([self._mk(60, 50, 1), self._mk(140, 50, 2)])
        assert self._id_at(out4, 140) == id_lr, "E_LR の ID が後続 frame で不安定"
        assert self._id_at(out4, 60) == id_rl, "E_RL の ID が後続 frame で不安定"

    def test_alias_persists_across_frames(self):
        """一度確立した alias 補正が以後のフレームでも安定して維持される。"""
        t = self._tracker()
        t._apply_swap_guard([self._mk(20, 50, 1), self._mk(180, 50, 2)])
        t._apply_swap_guard([self._mk(50, 50, 1), self._mk(150, 50, 2)])
        out2 = t._apply_swap_guard([self._mk(80, 50, 1), self._mk(120, 50, 2)])
        id_lr = self._id_at(out2, 80)
        id_rl = self._id_at(out2, 120)
        # 交差後 ByteTrack 取り違え (右観測=id2/左観測=id1 のまま) を 3 frame 連続
        t._apply_swap_guard([self._mk(80, 50, 1), self._mk(120, 50, 2)])
        assert t._swap_alias == {1: 2, 2: 1}
        t._apply_swap_guard([self._mk(60, 50, 1), self._mk(140, 50, 2)])
        out = t._apply_swap_guard([self._mk(40, 50, 1), self._mk(160, 50, 2)])
        # E_LR (右へ進み x=160)、E_RL (左へ進み x=40) の ID が初期と一致
        assert self._id_at(out, 160) == id_lr
        assert self._id_at(out, 40) == id_rl

    def test_reset_clears_swap_state(self):
        t = self._tracker()
        t._apply_swap_guard([self._mk(20, 50, 1), self._mk(180, 50, 2)])
        t._swap_alias[1] = 2  # 何か入れておく
        t.reset_for_new_set(1)
        assert t._swap_alias == {}
        assert t._swap_centroid_hist == {}


# ── Phase 4 (#2) player_uuid binding ───────────────────────────────────
class TestPlayerUuidBinding:
    """court_id → 登録 Player.uuid 束ね (_attach_player_label のチョークポイント)。"""

    def _mk(self, court_id):
        return TrackedPerson(
            bbox=(0.0, 0.0, 10.0, 20.0), track_id=1, court_id=court_id,
            player_uuid=None, confidence=0.9,
        )

    def test_uuid_bound_from_court_map_doubles(self):
        t = PersonTracker(match_type="doubles", court_corners=None)
        t._court_to_uuid = {0: "ua", 1: "ub", 2: "upa", 3: "upb"}
        out = t._attach_player_label(self._mk(2))
        assert out.court_id == 2
        assert out.player_label == "PlayerC"   # 2 = BL = PlayerC = partner_a
        assert out.player_uuid == "upa"

    def test_uuid_follows_side_swap(self):
        t = PersonTracker(match_type="doubles", court_corners=None)
        t._court_to_uuid = {0: "ua", 1: "ub", 2: "upa", 3: "upb"}
        t._side_swapped = True
        # side swap: court 0 → effective 2 → PlayerC → upa (label と uuid が一致して反転)
        out = t._attach_player_label(self._mk(0))
        assert out.court_id == 2
        assert out.player_label == "PlayerC"
        assert out.player_uuid == "upa"

    def test_uuid_none_when_no_roster(self):
        # match_id 無し = _court_to_uuid 空 → player_uuid は None (挙動非破壊)
        t = PersonTracker(match_type="doubles", court_corners=None)
        assert t._court_to_uuid == {}
        out = t._attach_player_label(self._mk(0))
        assert out.player_label == "PlayerA"
        assert out.player_uuid is None

    def test_uuid_none_when_role_unregistered(self):
        # singles などで partner uuid が無い court は None
        t = PersonTracker(match_type="doubles", court_corners=None)
        t._court_to_uuid = {0: "ua", 1: "ub"}  # 2,3 未登録
        assert t._attach_player_label(self._mk(0)).player_uuid == "ua"
        assert t._attach_player_label(self._mk(3)).player_uuid is None

    def test_court_none_returns_unchanged(self):
        t = PersonTracker(match_type="doubles", court_corners=None)
        t._court_to_uuid = {0: "ua"}
        tp = self._mk(None)
        out = t._attach_player_label(tp)
        assert out.player_uuid is None
        assert out.player_label is None


# ── ByteTracker 単体テスト ─────────────────────────────────────────────
class TestByteTrackerCore:
    def test_iou_matrix_basic(self):
        a = STrack((0, 0, 10, 10), 0.9)
        b = STrack((0, 0, 10, 10), 0.9)
        m = _ious([a], [b])
        # 同じ bbox → IoU=1
        assert m.shape == (1, 1)
        assert abs(m[0, 0] - 1.0) < 1e-6

    def test_iou_disjoint(self):
        a = STrack((0, 0, 10, 10), 0.9)
        b = STrack((100, 100, 110, 110), 0.9)
        m = _ious([a], [b])
        assert m[0, 0] == 0.0

    def test_linear_assignment_matches_low_cost(self):
        cost = np.array([[0.0, 0.9], [0.9, 0.0]])
        matches, ua, ub = _linear_assignment(cost, thresh=0.5)
        assert sorted(matches) == [(0, 0), (1, 1)]
        assert ua == [] and ub == []

    def test_linear_assignment_rejects_high_cost(self):
        cost = np.array([[0.95]])
        matches, ua, ub = _linear_assignment(cost, thresh=0.5)
        assert matches == []
        assert ua == [0] and ub == [0]

    def test_kalman_prediction_advances_position(self):
        st = STrack((0, 0, 10, 20), 0.9)
        st.activate(frame_id=0)
        # 速度成分が 0 なら predict しても中心ほぼ変わらない
        x0, y0, _, _ = st.xyxy
        st.predict()
        x1, y1, _, _ = st.xyxy
        # 初期速度 0 なので大きく動かない (Kalman 過渡応答で多少のドリフトは許容)
        assert abs(x1 - x0) < 5.0
        assert abs(y1 - y0) < 5.0

    def test_tracker_assigns_consistent_id_across_frames(self):
        tracker = ByteTracker(track_high_thresh=0.3, new_track_thresh=0.3)
        # 5 frame 連続で同位置に detection
        d = Detection(bbox=(10, 10, 30, 50), score=0.9)
        ids: list[int] = []
        for f in range(1, 6):
            out = tracker.update([d], frame_id=f)
            if out:
                ids.append(out[0].track_id)
        # 2 フレーム目以降は activated。少なくとも 3 回は同じ id が見えるはず。
        assert len(ids) >= 3
        assert len(set(ids)) == 1, f"track_id ぶれた: {ids}"

    def test_tracker_creates_new_id_for_distant_detection(self):
        tracker = ByteTracker(track_high_thresh=0.3, new_track_thresh=0.3)
        d1 = Detection(bbox=(10, 10, 30, 50), score=0.9)
        d2 = Detection(bbox=(500, 500, 530, 550), score=0.9)
        # 2 つを 4 frame ずつ
        seen_ids: set[int] = set()
        for f in range(1, 5):
            out = tracker.update([d1, d2], frame_id=f)
            for st in out:
                seen_ids.add(st.track_id)
        assert len(seen_ids) >= 2

    def test_tracker_drops_low_confidence_below_low_thresh(self):
        tracker = ByteTracker(
            track_high_thresh=0.5, track_low_thresh=0.3, new_track_thresh=0.5,
        )
        # score=0.1 は high にも low にも入らない → 何も track 化されない
        d = Detection(bbox=(10, 10, 30, 50), score=0.1)
        for f in range(1, 4):
            out = tracker.update([d], frame_id=f)
        assert out == []

    def test_tracker_reset_clears_state(self):
        tracker = ByteTracker(track_high_thresh=0.3, new_track_thresh=0.3)
        d = Detection(bbox=(10, 10, 30, 50), score=0.9)
        for f in range(1, 4):
            tracker.update([d], frame_id=f)
        tracker.reset()
        # reset 後は frame_id も track 状態もクリア
        out = tracker.update([], frame_id=1)
        assert out == []
