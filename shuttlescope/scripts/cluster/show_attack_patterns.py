"""Pretty-print the attack_pattern aggregator snapshot.

Reads the JSON dump produced by `backend/utils/attack_pattern.flush_to_file()`
(default `backend/data/attack_pattern.json`) and shows:
  - top entry paths (= where attackers first land)
  - top transitions (= 1-step Markov edges)
  - top paths overall
  - depth distribution (= how deep each IP crawls)
  - kind counts

Usage:
  python scripts/cluster/show_attack_patterns.py [path-to-snapshot.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    default = Path(__file__).resolve().parent.parent.parent / "backend" / "data" / "attack_pattern.json"
    p = Path(argv[1]) if len(argv) > 1 else default
    if not p.is_file():
        print(f"[show_attack_patterns] snapshot file not found: {p}")
        return 1
    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    uptime = data.get("uptime_sec", 0)
    print(f"=== Attack pattern snapshot ===")
    print(f"uptime: {uptime}s ({uptime // 3600}h{(uptime % 3600) // 60}m)")
    print(f"total IPs: {data.get('total_ips', 0)}")
    print(f"total hits: {data.get('total_hits', 0)}")
    print()

    print("--- Kind counts ---")
    for k, v in (data.get("kind_counts") or {}).items():
        print(f"  {k:24s} {v}")
    print()

    print("--- Depth distribution (per-IP crawl depth) ---")
    for k, v in (data.get("depth_distribution") or {}).items():
        print(f"  {k:8s} IPs: {v}")
    print()

    print("--- Top entry paths (first-hit) ---")
    for item in (data.get("top_first_hits") or [])[:20]:
        print(f"  {item['count']:6d}  {item['path']}")
    print()

    print("--- Top overall paths ---")
    for item in (data.get("top_paths") or [])[:30]:
        print(f"  {item['count']:6d}  {item['path']}")
    print()

    print("--- Top transitions (1-step Markov) ---")
    for item in (data.get("top_transitions") or [])[:30]:
        print(f"  {item['count']:6d}  {item['from']}  ->  {item['to']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
