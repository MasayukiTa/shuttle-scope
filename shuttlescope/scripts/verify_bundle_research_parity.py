"""研究タブ bundle エンドポイントと個別エンドポイントのレスポンス形状同一性を検証する。

各キーについて個別 endpoint と bundle.data[key] を deep compare し、差分があれば報告する。
浮動小数は tolerance 1e-9 で比較する。

既知の例外系 endpoint (shot_influence_v2 KeyError, bayes_matchup AttributeError 等) は
bundle 側でも同じ例外になりうるため、個別が 500/例外を返す場合は「両方エラー」なら OK とする。
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = f"sqlite:///{(ROOT / 'backend' / 'db' / 'shuttlescope.db').as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.utils import response_cache  # noqa: E402

PLAYER_ID = int(os.environ.get("VERIFY_PLAYER_ID", "12"))
TOL = 1e-9
HEADERS = {"X-Role": "analyst", "X-Player-Id": str(PLAYER_ID), "X-Team-Name": ""}

# (bundle_key, individual_url_path)
# counterfactual_v2 の Bootstrap CI 関連フィールドは RNG が seed されない random.choices
# ベースのため、同じ入力でも呼び出しごとに微変動する。parity 検証ではこれらを除外する。
STOCHASTIC_FIELDS = {
    "actual_ci_low", "actual_ci_high",
    "ci_low", "ci_high", "overlap_score",
}

PAIRS = [
    ("epv", "/api/analysis/epv"),
    ("epv_state_table", "/api/analysis/epv_state_table"),
    ("state_action_values", "/api/analysis/state_action_values"),
    ("counterfactual_shots", "/api/analysis/counterfactual_shots"),
    ("counterfactual_v2", "/api/analysis/counterfactual_v2"),
    ("bayes_matchup", "/api/analysis/bayes_matchup"),
    ("opponent_policy", "/api/analysis/opponent_policy"),
    ("doubles_role", "/api/analysis/doubles_role"),
    ("shot_influence_v2", "/api/analysis/shot_influence_v2"),
    ("hazard_fatigue", "/api/analysis/hazard_fatigue"),
]


def diff(a, b, path=""):
    if isinstance(a, float) or isinstance(b, float):
        try:
            af = float(a); bf = float(b)
            if math.isnan(af) and math.isnan(bf):
                return []
            if abs(af - bf) <= TOL:
                return []
            return [f"{path}: float diff {af} vs {bf}"]
        except Exception:
            return [f"{path}: type mismatch {type(a).__name__} vs {type(b).__name__}"]
    if type(a) is not type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(a - b) <= TOL:
                return []
        return [f"{path}: type mismatch {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, dict):
        diffs = []
        keys = set(a.keys()) | set(b.keys())
        for k in keys:
            if k in STOCHASTIC_FIELDS:
                continue
            if k not in a:
                diffs.append(f"{path}.{k}: missing in individual")
                continue
            if k not in b:
                diffs.append(f"{path}.{k}: missing in bundle")
                continue
            diffs.extend(diff(a[k], b[k], f"{path}.{k}"))
        return diffs
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: list len {len(a)} vs {len(b)}"]
        diffs = []
        for i, (x, y) in enumerate(zip(a, b)):
            diffs.extend(diff(x, y, f"{path}[{i}]"))
        return diffs
    if a != b:
        return [f"{path}: {a!r} vs {b!r}"]
    return []


def main() -> int:
    import random as _random
    client = TestClient(app, raise_server_exceptions=False)
    response_cache.clear()

    # counterfactual_v2 など bootstrap CI 系は random.choices を seed なしで呼ぶため、
    # 同一入力でも呼び出しごとに値が微妙に変動する。
    # parity 検証では各リクエスト前に同じ seed を張ることで再現性を確保する。
    _random.seed(12345)
    print(f"Fetching research bundle for player_id={PLAYER_ID} ...")
    bundle_resp = client.get(
        f"/api/analysis/bundle/research?player_id={PLAYER_ID}",
        headers=HEADERS,
    )
    bundle_resp.raise_for_status()
    bundle_json = bundle_resp.json()
    bundle_data = bundle_json["data"]
    bundle_errors = (bundle_json.get("meta") or {}).get("errors") or {}

    overall_ok = True
    for key, url in PAIRS:
        response_cache.clear()
        _random.seed(12345)
        indiv_resp = client.get(f"{url}?player_id={PLAYER_ID}", headers=HEADERS)
        indiv_status = indiv_resp.status_code
        bundle_value = bundle_data.get(key)
        bundle_err = bundle_errors.get(key)

        if indiv_status >= 500 or indiv_status == 404:
            # 個別が例外/404 を返すケースは既知バグ。
            # bundle が error 文字列 + None を返していれば OK とする。
            if bundle_err is not None and bundle_value is None:
                print(f"  OK*     {key}  (both errored: indiv={indiv_status}, bundle={bundle_err[:60]})")
            else:
                overall_ok = False
                print(f"  DIFF    {key}  indiv={indiv_status} but bundle returned value/no-error")
            continue

        try:
            indiv_json = indiv_resp.json()
        except Exception as e:
            overall_ok = False
            print(f"  DIFF    {key}  indiv json decode failed: {e}")
            continue

        if bundle_err is not None:
            overall_ok = False
            print(f"  DIFF    {key}  indiv OK but bundle errored: {bundle_err[:100]}")
            continue

        diffs = diff(indiv_json, bundle_value, path=key)
        if not diffs:
            print(f"  OK      {key}")
        else:
            overall_ok = False
            print(f"  DIFF    {key}  ({len(diffs)} diffs)")
            for d in diffs[:10]:
                print(f"     - {d}")
            if len(diffs) > 10:
                print(f"     ... +{len(diffs) - 10} more")

    print()
    if overall_ok:
        print("PARITY OK: all 10 research cards match individual endpoints (known-bug endpoints error in both)")
        return 0
    else:
        print("PARITY FAIL: diffs found above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
