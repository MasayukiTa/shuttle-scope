"""Profile analysis endpoints for player_id=12.

Writes TSV rows: url\trun_no\telapsed_sec
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# Must be set before importing backend.main
os.environ["DATABASE_URL"] = f"sqlite:///{(ROOT / 'backend' / 'db' / 'shuttlescope.db').as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.utils import response_cache  # noqa: E402

ENDPOINTS = [
    # research
    "/api/analysis/epv?player_id=12",
    "/api/analysis/epv_state_table?player_id=12",
    "/api/analysis/state_action_values?player_id=12",
    "/api/analysis/counterfactual_shots?player_id=12",
    "/api/analysis/counterfactual_v2?player_id=12",
    "/api/analysis/bayes_matchup?player_id=12",
    "/api/analysis/opponent_policy?player_id=12",
    "/api/analysis/doubles_role?player_id=12",
    "/api/analysis/shot_influence_v2?player_id=12",
    "/api/analysis/hazard_fatigue?player_id=12",
    # spatial
    "/api/analysis/heatmap?player_id=12&type=hit",
    "/api/analysis/heatmap?player_id=12&type=land",
    "/api/analysis/heatmap/composite?player_id=12",
    "/api/analysis/spatial_density?player_id=12",
    # looking-back
    "/api/analysis/pre_loss_patterns?player_id=12",
    "/api/analysis/pre_win_patterns?player_id=12",
    "/api/analysis/effective_distribution_map?player_id=12",
    "/api/analysis/received_vulnerability_map?player_id=12",
    "/api/analysis/score_progression?player_id=12",
    "/api/analysis/set_comparison?player_id=12",
    "/api/analysis/rally_sequence_patterns?player_id=12",
    # bundle (振り返りタブ一括)
    "/api/analysis/bundle/review?player_id=12",
]

HEADERS = {
    "X-Role": "analyst",
    "X-Player-Id": "12",
    "X-Team-Name": "",
}


def main() -> None:
    out_path = ROOT / "docs" / "perf" / (sys.argv[1] if len(sys.argv) > 1 else "2026-04-15-baseline.tsv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    rows: list[str] = ["url\trun_no\telapsed_sec\tstatus"]
    for url in ENDPOINTS:
        for run_no in range(1, 4):
            if run_no == 1:
                # in-memory + DB 両方を無効化（DATA_VERSION bump）
                try:
                    response_cache.clear()
                except Exception:
                    response_cache.MEMORY_CACHE.clear()
            t0 = time.perf_counter()
            try:
                r = client.get(url, headers=HEADERS)
                status = r.status_code
            except Exception as e:  # pragma: no cover
                status = f"ERR:{type(e).__name__}"
            elapsed = time.perf_counter() - t0
            line = f"{url}\t{run_no}\t{elapsed:.3f}\t{status}"
            print(line, flush=True)
            rows.append(line)
    out_path.write_text("\n".join(rows), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
