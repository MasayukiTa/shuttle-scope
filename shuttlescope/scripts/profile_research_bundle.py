"""研究タブ bundle vs 個別 10 endpoint の比較計測。

Writes TSV to docs/perf/2026-04-15-bundle-research.tsv
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = f"sqlite:///{(ROOT / 'backend' / 'db' / 'shuttlescope.db').as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.utils import response_cache  # noqa: E402

PLAYER_ID = int(os.environ.get("PROFILE_PLAYER_ID", "12"))

INDIV = [
    f"/api/analysis/epv?player_id={PLAYER_ID}",
    f"/api/analysis/epv_state_table?player_id={PLAYER_ID}",
    f"/api/analysis/state_action_values?player_id={PLAYER_ID}",
    f"/api/analysis/counterfactual_shots?player_id={PLAYER_ID}",
    f"/api/analysis/counterfactual_v2?player_id={PLAYER_ID}",
    f"/api/analysis/bayes_matchup?player_id={PLAYER_ID}",
    f"/api/analysis/opponent_policy?player_id={PLAYER_ID}",
    f"/api/analysis/doubles_role?player_id={PLAYER_ID}",
    f"/api/analysis/shot_influence_v2?player_id={PLAYER_ID}",
    f"/api/analysis/hazard_fatigue?player_id={PLAYER_ID}",
]
BUNDLE = f"/api/analysis/bundle/research?player_id={PLAYER_ID}"

HEADERS = {"X-Role": "analyst", "X-Player-Id": str(PLAYER_ID), "X-Team-Name": ""}


def main() -> None:
    out_path = ROOT / "docs" / "perf" / "2026-04-15-bundle-research.tsv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    client = TestClient(app, raise_server_exceptions=False)
    rows = ["mode\trun_no\telapsed_sec\tstatus"]

    for run in range(1, 4):
        response_cache.clear()
        t0 = time.perf_counter()
        total_status: list = []
        for url in INDIV:
            try:
                r = client.get(url, headers=HEADERS)
                total_status.append(r.status_code)
            except Exception as e:
                total_status.append(f"ERR:{type(e).__name__}")
        elapsed = time.perf_counter() - t0
        status_str = ",".join(str(s) for s in total_status)
        rows.append(f"indiv_sum\t{run}\t{elapsed:.3f}\t{status_str}")
        print(rows[-1])

    for run in range(1, 4):
        response_cache.clear()
        t0 = time.perf_counter()
        try:
            r = client.get(BUNDLE, headers=HEADERS)
            status = r.status_code
        except Exception as e:
            status = f"ERR:{type(e).__name__}"
        elapsed = time.perf_counter() - t0
        rows.append(f"bundle\t{run}\t{elapsed:.3f}\t{status}")
        print(rows[-1])

    out_path.write_text("\n".join(rows), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
