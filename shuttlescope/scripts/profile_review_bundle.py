"""振り返りタブ bundle vs 個別 6 endpoint の比較計測。

Writes TSV to docs/perf/2026-04-15-bundle-review.tsv
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
    f"/api/analysis/pre_loss_patterns?player_id={PLAYER_ID}",
    f"/api/analysis/pre_win_patterns?player_id={PLAYER_ID}",
    f"/api/analysis/effective_distribution_map?player_id={PLAYER_ID}",
    f"/api/analysis/received_vulnerability?player_id={PLAYER_ID}",
    f"/api/analysis/set_comparison?player_id={PLAYER_ID}",
    f"/api/analysis/rally_sequence_patterns?player_id={PLAYER_ID}",
]
BUNDLE = f"/api/analysis/bundle/review?player_id={PLAYER_ID}"

HEADERS = {"X-Role": "analyst", "X-Player-Id": str(PLAYER_ID), "X-Team-Name": ""}


def main() -> None:
    out_path = ROOT / "docs" / "perf" / "2026-04-15-bundle-review.tsv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    rows = ["mode\trun_no\telapsed_sec\tstatus"]

    # 3 run ずつ: 1 回目は cold cache
    for run in range(1, 4):
        response_cache.clear()
        t0 = time.perf_counter()
        total_status: list[int | str] = []
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
