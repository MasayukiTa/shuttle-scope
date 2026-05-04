"""振り返りタブ bundle エンドポイントと個別エンドポイントのレスポンス形状同一性を検証する。

各キーについて個別 endpoint と bundle.data[key] を deep compare し、差分があれば報告する。
浮動小数は tolerance 1e-9 で比較する。
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
PAIRS = [
    ("pre_loss_patterns", "/api/analysis/pre_loss_patterns"),
    ("pre_win_patterns", "/api/analysis/pre_win_patterns"),
    ("effective_distribution_map", "/api/analysis/effective_distribution_map"),
    ("received_vulnerability", "/api/analysis/received_vulnerability"),
    ("set_comparison", "/api/analysis/set_comparison"),
    ("rally_sequence_patterns", "/api/analysis/rally_sequence_patterns"),
]


def diff(a, b, path=""):
    """Return a list of string diff descriptions. Empty = identical."""
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
        # Accept int vs float equivalence if within tol
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(a - b) <= TOL:
                return []
        return [f"{path}: type mismatch {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, dict):
        diffs = []
        keys = set(a.keys()) | set(b.keys())
        for k in keys:
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
    client = TestClient(app)
    response_cache.clear()

    print(f"Fetching bundle for player_id={PLAYER_ID} ...")
    bundle_resp = client.get(
        f"/api/analysis/bundle/review?player_id={PLAYER_ID}",
        headers=HEADERS,
    )
    bundle_resp.raise_for_status()
    bundle_data = bundle_resp.json()["data"]

    overall_ok = True
    for key, url in PAIRS:
        response_cache.clear()
        indiv_resp = client.get(f"{url}?player_id={PLAYER_ID}", headers=HEADERS)
        indiv_resp.raise_for_status()
        indiv_json = indiv_resp.json()
        bundle_json = bundle_data.get(key)
        diffs = diff(indiv_json, bundle_json, path=key)
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
        print("PARITY OK: all 6 cards match individual endpoints")
        return 0
    else:
        print("PARITY FAIL: diffs found above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
