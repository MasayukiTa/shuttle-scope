"""Swap Guard 評価用 proxy 指標 (ground-truth 不要・純 Python)。

設計書: private_docs/2026-05-27_person_tracking_design.md (Swap Guard 検証)

正解ラベル (ground-truth) が無いため厳密な IDSW (ID switch) は計算できない。
代わりに「追跡の安定度」を測る ground-truth 不要の proxy 指標を計算する:

- per_court_unique_ids:
    court_id (0=FL,1=FR,2=BL,3=BR) ごとに、その court に一度でも割り当てられた
    distinct な track_id の総数。少ないほど安定 (churn-tuning で使った指標と同系)。

- proxy_idsw (per court):
    各 court_id を「スロット」と見なし、そのスロットを占める track_id 集合が
    フレーム間でどれだけ入れ替わったかを数える。具体的には、ある court が
    占有されているフレーム列を時系列に並べ、フレーム n でそのスロットに
    *新たに現れた* track_id (直前の占有フレームの集合に居なかった ID) の数を
    累積する。初回占有フレームの ID は switch として数えない (= 初期割当)。
    完全に安定なら 0。同一スロットの占有 ID が k 回切り替われば proxy_idsw=k。

    singles: 1 court = 1 人想定なので「占有 ID が別 ID に変わった回数」に一致する。
    doubles: 1 court に最大 2 人。集合差分で新規流入 ID 数を数えるため、
             2 人のうち片方だけ入れ替わっても 1 とカウントされる。

- swap_event 集計:
    PersonTracker.swap_guard_stats() 由来の swap_detected / swap_applied を
    そのまま受け渡す (本モジュールは計算しないが、比較 JSON に同梱するための
    集約ヘルパを提供する)。

入力はすべて per-frame の dict 系列:
    [{"frame": int, "track_id": int, "court_id": Optional[int]}, ...]
court_id が None の (コート外) レコードはどの指標でも無視する。
track_id < 0 (未付与) も無視する。

CV / GPU 依存を一切持ち込まない。import して関数単位で unit test 可能。
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence


# 評価対象の court スロット (doubles の 4 象限)。
COURT_SLOTS = (0, 1, 2, 3)


def _iter_valid(records: Iterable[Mapping]) -> list[dict]:
    """track_id>=0 かつ court_id is not None のレコードだけを正規化して返す。

    各レコードから frame / track_id / court_id を int に正規化する。
    frame 欠損は ValueError (順序が定義できないため)。
    """
    out: list[dict] = []
    for r in records:
        court_id = r.get("court_id")
        if court_id is None:
            continue
        track_id = r.get("track_id")
        if track_id is None or int(track_id) < 0:
            continue
        if "frame" not in r or r["frame"] is None:
            raise ValueError("record に frame がありません: %r" % (r,))
        out.append(
            {
                "frame": int(r["frame"]),
                "track_id": int(track_id),
                "court_id": int(court_id),
            }
        )
    return out


def per_court_unique_ids(records: Iterable[Mapping]) -> dict[int, int]:
    """court_id ごとの distinct track_id 数を返す。

    返り値は {court_id: unique_count}。占有が無かった court は 0。
    """
    valid = _iter_valid(records)
    seen: dict[int, set[int]] = {c: set() for c in COURT_SLOTS}
    for r in valid:
        cid = r["court_id"]
        seen.setdefault(cid, set()).add(r["track_id"])
    return {cid: len(ids) for cid, ids in seen.items()}


def proxy_idsw_per_court(records: Iterable[Mapping]) -> dict[int, int]:
    """court_id スロットごとの proxy ID-switch 回数を返す。

    各 court について、占有フレームを時系列 (frame 昇順) に並べ、隣接する
    占有フレーム間で *新たに流入した* track_id の数を累積する。初回占有
    フレームの ID は初期割当として数えない。

    例 (singles, court 0):
        frame 0: id=1, frame 1: id=1, frame 2: id=5, frame 3: id=5, frame 4: id=9
        → frame2 で 5 が流入 (+1)、frame4 で 9 が流入 (+1) = proxy_idsw=2
    """
    valid = _iter_valid(records)
    # court_id -> frame -> set(track_id)
    by_court: dict[int, dict[int, set[int]]] = {}
    for r in valid:
        by_court.setdefault(r["court_id"], {}).setdefault(r["frame"], set()).add(
            r["track_id"]
        )

    result: dict[int, int] = {c: 0 for c in COURT_SLOTS}
    for cid, frames in by_court.items():
        switches = 0
        prev_ids: Optional[set[int]] = None
        for frame in sorted(frames.keys()):
            cur_ids = frames[frame]
            if prev_ids is None:
                # 初回占有フレーム: 初期割当として数えない
                prev_ids = set(cur_ids)
                continue
            # 直前の占有フレームに居なかった ID = 新規流入 (switch)
            newcomers = cur_ids - prev_ids
            switches += len(newcomers)
            prev_ids = set(cur_ids)
        result[cid] = switches
    return result


def proxy_idsw_total(records: Iterable[Mapping]) -> int:
    """全 court の proxy_idsw 合計。"""
    return sum(proxy_idsw_per_court(records).values())


def aggregate_swap_events(stats: Optional[Mapping]) -> dict[str, int]:
    """PersonTracker.swap_guard_stats() の値を正規化して返す。

    None (= 統計未取得) の場合は 0 埋め。OFF 実行では両方 0 が期待値。
    """
    stats = stats or {}
    return {
        "swap_detected": int(stats.get("swap_detected", 0) or 0),
        "swap_applied": int(stats.get("swap_applied", 0) or 0),
    }


def evaluate_run(
    records: Sequence[Mapping],
    *,
    swap_stats: Optional[Mapping] = None,
    frames: Optional[int] = None,
    seconds: Optional[float] = None,
) -> dict:
    """1 回の追跡実行 (OFF または ON) に対する proxy 指標一式を計算する。

    Args:
        records: per-frame の [{"frame","track_id","court_id"}] 系列。
        swap_stats: PersonTracker.swap_guard_stats() の dict (OFF なら 0)。
        frames: 処理フレーム数 (記録用)。
        seconds: 処理秒数 (記録用)。

    Returns:
        proxy 指標 dict。仕様で定めた key を含む:
            per_court_unique_ids, swap_detected, swap_applied,
            proxy_idsw_per_court, proxy_idsw_total, frames, seconds
    """
    per_court = per_court_unique_ids(records)
    idsw_per_court = proxy_idsw_per_court(records)
    swaps = aggregate_swap_events(swap_stats)
    return {
        "per_court_unique_ids": per_court,
        "unique_ids_total": sum(per_court.values()),
        "swap_detected": swaps["swap_detected"],
        "swap_applied": swaps["swap_applied"],
        "proxy_idsw_per_court": idsw_per_court,
        "proxy_idsw_total": sum(idsw_per_court.values()),
        "frames": int(frames) if frames is not None else None,
        "seconds": round(float(seconds), 3) if seconds is not None else None,
    }


def compare_runs(off: Mapping, on: Mapping) -> dict:
    """Swap Guard OFF / ON の proxy 指標を比較した dict を返す。

    Args:
        off: evaluate_run(...) の OFF 実行結果。
        on:  evaluate_run(...) の ON 実行結果。

    Returns:
        {"off": ..., "on": ..., "delta": {...}} 形式。delta は ON - OFF。
        delta が負 = ON で指標が下がった (= 安定度向上の方向)。
    """
    def _num(d: Mapping, key: str) -> float:
        v = d.get(key)
        return float(v) if v is not None else 0.0

    delta = {
        "unique_ids_total": _num(on, "unique_ids_total") - _num(off, "unique_ids_total"),
        "proxy_idsw_total": _num(on, "proxy_idsw_total") - _num(off, "proxy_idsw_total"),
    }
    # per-court delta も出す (両方に存在する court のみ)
    per_court_delta: dict[int, dict[str, float]] = {}
    off_uc = off.get("per_court_unique_ids", {}) or {}
    on_uc = on.get("per_court_unique_ids", {}) or {}
    off_sw = off.get("proxy_idsw_per_court", {}) or {}
    on_sw = on.get("proxy_idsw_per_court", {}) or {}
    for cid in sorted({*off_uc.keys(), *on_uc.keys(), *off_sw.keys(), *on_sw.keys()}):
        per_court_delta[int(cid)] = {
            "unique_ids": float(on_uc.get(cid, 0)) - float(off_uc.get(cid, 0)),
            "proxy_idsw": float(on_sw.get(cid, 0)) - float(off_sw.get(cid, 0)),
        }
    delta["per_court"] = per_court_delta
    return {"off": dict(off), "on": dict(on), "delta": delta}
