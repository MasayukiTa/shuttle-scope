"""service_shots.py -- サーブ系ショットの扱いを一か所に集める (監査 #327 / #330 / #38 / #41)。

バドミントンではサーブはラリーの最初の 1 打にしか現れない。ところが記録の食い違いや
ラリーの連結で、ラリーの途中に short_service / long_service が混じることがある。
これを素のまま n-gram・遷移・「ラリー中盤の球」として数えると、
「サーブが 2 回入った 3 連ショット」や「ショートサーブ -> ショートサーブ」のような
競技上あり得ない並びが集計に出る。

このモジュールは依存を持たない純粋関数だけを置く (DB・numpy を読み込まない)。
"""
from __future__ import annotations

from typing import Iterable, Optional

SERVICE_SHOTS = frozenset({"short_service", "long_service"})


def is_service_shot(shot_type: Optional[str]) -> bool:
    """サーブ系のショットか。"""
    return shot_type in SERVICE_SHOTS


def truncate_at_stray_service(shots: Iterable[str]) -> list[str]:
    """ラリーの先頭以外に現れたサーブ系ショットで列を打ち切る。

    先頭の 1 打がサーブなのは正常なので残す。2 打目以降にサーブが出た列は
    ラリーが連結された、または記録が壊れているので、そこから後ろは信用せず捨てる
    (捨てた部分を前後でつなぎ直さないので、偽の遷移は作られない)。
    """
    out: list[str] = []
    for i, s in enumerate(shots):
        if i > 0 and s in SERVICE_SHOTS:
            break
        out.append(s)
    return out


def without_service(shots: Iterable[str]) -> list[str]:
    """サーブ系ショットを除いた列。「ラリー中盤の球」を数えるときに使う。"""
    return [s for s in shots if s not in SERVICE_SHOTS]
