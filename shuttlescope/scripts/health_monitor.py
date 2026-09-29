#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ShuttleScope 常時稼働ヘルスモニタ (INFRA Phase C).

backend コードには一切触れず、HTTP 経由で /api/health を叩く。
通知先は Notifier interface で差し替え可能。
LINE Notify は 2025-04 で終了したため、Discord Webhook / ntfy / ログ の 3 実装を同梱。

環境変数:
  SS_HEALTH_URL         : ヘルスエンドポイント (default: http://localhost:8765/api/health)
  SS_HEALTH_INTERVAL    : ポーリング秒数 (default: 30)
  SS_HEALTH_FAIL_THRESH : 連続失敗何回でエスカレーション通知 (default: 3)
  SS_NOTIFY_KIND        : log | discord | ntfy (default: log)
  SS_NOTIFY_WEBHOOK_URL : Discord webhook URL または ntfy topic URL

単発モード:
  python scripts/health_monitor.py --once
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

LOG = logging.getLogger("ss.health_monitor")


# ---------------------------------------------------------------------------
# Notifier interface
# ---------------------------------------------------------------------------
class Notifier(ABC):
    """通知先の抽象インタフェース。"""

    @abstractmethod
    def notify(self, level: str, title: str, payload: Dict[str, Any]) -> None:
        """通知を送る。level: info/warn/critical"""


class LogNotifier(Notifier):
    """標準ログ出力のみの Notifier (開発機デフォルト)。"""

    def notify(self, level: str, title: str, payload: Dict[str, Any]) -> None:
        line = json.dumps(
            {"level": level, "title": title, "payload": payload},
            ensure_ascii=False,
        )
        # 開発機でも副作用ゼロに保つため stdout のみ
        print(line, flush=True)


class DiscordWebhookNotifier(Notifier):
    """Discord webhook への通知。"""

    def __init__(self, url: str) -> None:
        self.url = url

    def notify(self, level: str, title: str, payload: Dict[str, Any]) -> None:
        content = f"[{level.upper()}] {title}\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)[:1800]}\n```"
        body = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as exc:  # pragma: no cover - 外部通信
            LOG.warning("Discord 通知失敗: %s", exc)


class NtfyNotifier(Notifier):
    """ntfy.sh への通知 (topic URL を SS_NOTIFY_WEBHOOK_URL で指定)。"""

    def __init__(self, url: str) -> None:
        self.url = url

    def notify(self, level: str, title: str, payload: Dict[str, Any]) -> None:
        priority = {"info": "3", "warn": "4", "critical": "5"}.get(level, "3")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": level,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as exc:  # pragma: no cover
            LOG.warning("ntfy 通知失敗: %s", exc)


def build_notifier() -> Notifier:
    """環境変数から Notifier を組み立てる。"""
    kind = os.environ.get("SS_NOTIFY_KIND", "log").lower()
    url = os.environ.get("SS_NOTIFY_WEBHOOK_URL", "")
    if kind == "discord" and url:
        return DiscordWebhookNotifier(url)
    if kind == "ntfy" and url:
        return NtfyNotifier(url)
    return LogNotifier()


# ---------------------------------------------------------------------------
# GPU health (任意)
# ---------------------------------------------------------------------------
def _probe_gpu() -> Optional[Dict[str, Any]]:
    """backend.services.gpu_health.probe を try-import。無ければ None。"""
    try:
        from backend.services.gpu_health import probe  # type: ignore
    except Exception:
        return None
    try:
        result = probe()
        # 返り値が dict でなくても辞書化を試みる
        if isinstance(result, dict):
            return result
        return {"gpu": str(result)}
    except Exception as exc:
        return {"error": f"gpu probe failed: {exc}"}


# ---------------------------------------------------------------------------
# ヘルスチェック本体
# ---------------------------------------------------------------------------
@dataclass
class MonitorConfig:
    url: str = field(
        default_factory=lambda: os.environ.get(
            "SS_HEALTH_URL", "http://localhost:8765/api/health"
        )
    )
    interval: float = field(
        default_factory=lambda: float(os.environ.get("SS_HEALTH_INTERVAL", "30"))
    )
    fail_threshold: int = field(
        default_factory=lambda: int(os.environ.get("SS_HEALTH_FAIL_THRESH", "3"))
    )


def check_once(cfg: MonitorConfig) -> Dict[str, Any]:
    """1 回だけヘルスを叩いて結果 dict を返す。"""
    started = time.time()
    result: Dict[str, Any] = {
        "ts": int(started),
        "url": cfg.url,
        "ok": False,
        "status": None,
        "latency_ms": None,
        "body": None,
        "error": None,
    }
    try:
        with urllib.request.urlopen(cfg.url, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            result["status"] = resp.status
            result["ok"] = 200 <= resp.status < 300
            try:
                result["body"] = json.loads(raw)
            except Exception:
                result["body"] = raw[:500]
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        result["error"] = f"HTTPError: {exc}"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["latency_ms"] = int((time.time() - started) * 1000)

    gpu = _probe_gpu()
    if gpu is not None:
        result["gpu"] = gpu
    return result


def run_loop(cfg: MonitorConfig, notifier: Notifier) -> None:
    """常時稼働ループ。連続失敗でエスカレーション。"""
    consecutive_fail = 0
    was_down = False
    LOG.info("health_monitor 起動 url=%s interval=%s", cfg.url, cfg.interval)
    while True:
        snapshot = check_once(cfg)
        if snapshot["ok"]:
            if was_down:
                notifier.notify("info", "ShuttleScope 復旧", snapshot)
                was_down = False
            consecutive_fail = 0
        else:
            consecutive_fail += 1
            level = "warn"
            if consecutive_fail >= cfg.fail_threshold:
                level = "critical"
                was_down = True
            notifier.notify(
                level,
                f"ShuttleScope health NG ({consecutive_fail}連続)",
                snapshot,
            )
        time.sleep(cfg.interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ShuttleScope health monitor")
    parser.add_argument(
        "--once",
        action="store_true",
        help="単発実行モード (1 回チェックして JSON を stdout に出力)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("SS_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = MonitorConfig()
    notifier = build_notifier()

    if args.once:
        snapshot = check_once(cfg)
        # --once は必ず stdout に JSON を 1 行出す (検証用)
        print(json.dumps(snapshot, ensure_ascii=False))
        # log Notifier のときは二重になるので呼ばない
        if not isinstance(notifier, LogNotifier):
            level = "info" if snapshot["ok"] else "warn"
            notifier.notify(level, "ShuttleScope health (once)", snapshot)
        return 0 if snapshot["ok"] else 1

    try:
        run_loop(cfg, notifier)
    except KeyboardInterrupt:
        LOG.info("停止要求を受信")
    return 0


if __name__ == "__main__":
    sys.exit(main())
