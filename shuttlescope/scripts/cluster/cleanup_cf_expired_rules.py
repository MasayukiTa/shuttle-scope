"""Cleanup Cloudflare access_rules whose TTL has passed.

R45 で TTL 付き auto-ban を入れた際、process 内 `threading.Timer` で
TTL 経過後の rule DELETE をスケジュールしている。しかし backend
process が restart すると Timer が消えるため、TTL 切れの rule が CF 側に
残骸として残ることがある。

このスクリプトは:
  1. CF API で access_rules を全件取得
  2. notes が `Auto-ban via canary: ... expires=<unix_ts>` の rule を抽出
  3. expires が現在より過去なら DELETE

実行: weekly cron 想定。Free CF plan で API rate limit は十分余裕あり
      (Access Rules API は 1200 req/5min)。

env:
  - SS_CF_BAN_TOKEN  (必須)
  - SS_CF_ZONE_ID    (必須)
  - SS_CF_CLEANUP_DRY_RUN=1  (任意、削除せず表示のみ)

実行方法:
  python scripts/cluster/cleanup_cf_expired_rules.py
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Optional


def _load_local_env() -> None:
    """Auto-load `.env.development` or `.env` from the repo root if present.

    Backend は FastAPI settings 経由で読み込むが、本 CLI スクリプトは独立
    起動なので明示的に dotenv-style load する。
    """
    here = Path(__file__).resolve()
    # repo/shuttlescope/scripts/cluster/this.py → repo/shuttlescope/
    candidates = [
        here.parent.parent.parent / ".env.development",
        here.parent.parent.parent / ".env",
    ]
    for c in candidates:
        if not c.is_file():
            continue
        try:
            with open(c, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            break  # 最初に見つかったものだけ
        except Exception:
            continue


_load_local_env()


_NOTES_EXPIRES_RE = re.compile(r"expires=(\d{10,12})")


def _required(name: str) -> str:
    v = (os.environ.get(name) or "").strip()
    if not v:
        print(f"[cleanup] FATAL: env {name} is not set", file=sys.stderr)
        sys.exit(2)
    return v


def _extract_expires(notes: Optional[str]) -> Optional[int]:
    if not notes:
        return None
    m = _NOTES_EXPIRES_RE.search(notes)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def main() -> int:
    import requests  # type: ignore
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    token = _required("SS_CF_BAN_TOKEN")
    zone = _required("SS_CF_ZONE_ID")
    dry_run = (os.environ.get("SS_CF_CLEANUP_DRY_RUN") or "").strip() == "1"
    headers = {"Authorization": f"Bearer {token}"}

    now = int(time.time())
    base = f"https://api.cloudflare.com/client/v4/zones/{zone}/firewall/access_rules/rules"

    deleted = 0
    inspected = 0
    expired_seen = 0
    page = 1
    per_page = 50

    while True:
        r = requests.get(
            base,
            headers=headers,
            params={"page": page, "per_page": per_page,
                    "notes": "Auto-ban via canary"},
            timeout=20, verify=False,
        )
        if r.status_code != 200:
            print(f"[cleanup] FATAL list page={page} status={r.status_code} "
                  f"body={r.text[:200]}", file=sys.stderr)
            return 3
        body = r.json() or {}
        result = body.get("result") or []
        if not result:
            break
        for rule in result:
            inspected += 1
            notes = rule.get("notes") or ""
            rule_id = rule.get("id") or ""
            if not rule_id:
                continue
            exp = _extract_expires(notes)
            if exp is None:
                # TTL 表記がない old rule は安全側でスキップ
                continue
            if exp > now:
                continue
            expired_seen += 1
            print(f"[cleanup] EXPIRED rule_id={rule_id} expires={exp} "
                  f"(now={now}) notes={notes[:120]}")
            if dry_run:
                continue
            dr = requests.delete(f"{base}/{rule_id}", headers=headers,
                                  timeout=15, verify=False)
            if dr.status_code in (200, 204):
                deleted += 1
            else:
                print(f"[cleanup] WARN delete failed rule_id={rule_id} "
                      f"status={dr.status_code} body={dr.text[:200]}",
                      file=sys.stderr)
        result_info = body.get("result_info") or {}
        total_pages = int(result_info.get("total_pages") or 1)
        if page >= total_pages:
            break
        page += 1

    mode = "(DRY RUN)" if dry_run else ""
    print(f"[cleanup] DONE inspected={inspected} expired={expired_seen} "
          f"deleted={deleted} {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
