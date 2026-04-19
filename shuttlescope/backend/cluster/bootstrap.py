"""Ray クラスタの起動/停止ラッパ (INFRA Phase D)

設計方針:
- Ray 未インストール環境でも backend 起動・pytest が通ること
- ray の import は関数スコープに閉じる
- SS_CLUSTER_MODE=off のとき一切 Ray を触らない
- 失敗は WARN ログのみ、例外は投げない
- Windows Firewall 環境では ray.init() TCP接続がブロックされるため
  subprocess 経由の ray status/list で状態確認する
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional

from backend.config import settings

logger = logging.getLogger(__name__)

# ray.init() による接続済みフラグ
_ray_initialized: bool = False
# subprocess (ray status) 経由での確認済みフラグ
_ray_subprocess_connected: bool = False


def _import_ray():
    """ray モジュールをインポートして返す（テストで monkeypatch 可能な単一ポイント）。"""
    import ray  # noqa: F401
    return ray


def is_ray_available() -> bool:
    """ray パッケージが import 可能かを安全に判定する"""
    try:
        import ray  # noqa: F401
        return True
    except Exception:  # pragma: no cover - 環境依存
        return False


# ────────────────────────────────────────────────────────────────────────────
# subprocess ベース Ray 状態確認 (Windows Firewall 回避用)
# ────────────────────────────────────────────────────────────────────────────

def _find_ray_cmd() -> str:
    """ray 実行ファイルのパスを返す。現在の venv 内を優先する。"""
    scripts_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(scripts_dir, "ray.exe" if sys.platform == "win32" else "ray")
    if os.path.exists(candidate):
        return candidate
    return "ray"


def _subprocess_kwargs() -> dict:
    """subprocess.run に渡す共通キーワード引数。"""
    kw: dict = {"capture_output": True, "text": True, "timeout": 15}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return kw


def subprocess_ray_status() -> Dict[str, Any]:
    """ray status をサブプロセスで実行してクラスタ状態を返す。

    ray.init() の TCP 接続を使わずローカルソケット経由で状態を確認する。
    戻り値: {"running": bool, "nodes": [{"node_ip": str, "state": "ALIVE"}], "output": str}
    """
    try:
        result = subprocess.run(
            [_find_ray_cmd(), "status"],
            **_subprocess_kwargs(),
        )
        running = result.returncode == 0
        active_count = _parse_ray_status_active_count(result.stdout) if running else 0
        return {"running": running, "active_count": active_count, "output": result.stdout, "error": result.stderr}
    except FileNotFoundError:
        return {"running": False, "nodes": [], "output": "", "error": "ray コマンドが見つかりません"}
    except subprocess.TimeoutExpired:
        return {"running": False, "nodes": [], "output": "", "error": "ray status タイムアウト"}
    except Exception as exc:
        logger.debug("subprocess_ray_status 失敗: %s", exc)
        return {"running": False, "nodes": [], "output": "", "error": str(exc)}


def _parse_ray_status_active_count(output: str) -> int:
    """ray status 出力から Active セクションのノード数を返す。

    出力例:
      Active:
       1 node_c2f2006c...
       1 node_b7ce000...
    → 2 を返す
    """
    count = 0
    in_active = False
    for line in output.split("\n"):
        stripped = line.strip()
        if stripped == "Active:":
            in_active = True
            continue
        if not in_active:
            continue
        if stripped.startswith("Pending:") or stripped.startswith("Recent"):
            break
        if stripped.startswith("(no"):
            break
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def subprocess_ray_nodes() -> List[Dict[str, Any]]:
    """ダッシュボードなし環境ではノード IP を取得できないため空リストを返す。

    呼び出し元は active_count ベースの判定にフォールバックすること。
    """
    return []


def is_ray_connected() -> bool:
    """ray.init() または subprocess 確認のいずれかで接続済みかを返す。"""
    if _ray_initialized:
        try:
            import ray  # type: ignore
            return ray.is_initialized()
        except Exception:
            pass
    return _ray_subprocess_connected


def mark_ray_connected() -> None:
    """subprocess 確認後に接続済みフラグを立てる。"""
    global _ray_subprocess_connected
    _ray_subprocess_connected = True
    logger.info("mark_ray_connected: Ray クラスタ接続済みとしてマーク (subprocess)")
    try:
        from backend.benchmark.devices import invalidate_cache
        invalidate_cache()
    except Exception:
        pass
    # バックグラウンドで ray.init() を試みる（Windows Firewall 対応）
    try_ray_init_background()


def unmark_ray_connected() -> None:
    """subprocess 接続フラグをクリアする。"""
    global _ray_subprocess_connected
    _ray_subprocess_connected = False


def try_ray_init_background() -> None:
    """ray.init() をバックグラウンドスレッドで非同期実行する。

    _ray_subprocess_connected が True のときのみ実行する。
    ray.init() が 30 秒以内に成功すれば _ray_initialized = True を設定する。
    失敗・タイムアウトしても subprocess 接続フラグには影響しない。
    この関数は即座に返る（ノンブロッキング）。
    """
    if not _ray_subprocess_connected:
        logger.debug("try_ray_init_background: subprocess 未接続のためスキップ")
        return

    if _ray_initialized:
        logger.debug("try_ray_init_background: 既に ray.init() 済みのためスキップ")
        return

    def _worker() -> None:
        global _ray_initialized
        logger.info("try_ray_init_background: ray.init() を試みます (timeout=30s)")

        # ray が利用可能か確認
        try:
            ray = _import_ray()
        except Exception as exc:
            logger.warning("try_ray_init_background: ray を import できません (%s)", exc)
            return

        # タイムアウト付きで ray.init() を実行する
        # threading.Event + 内部スレッドで 30 秒タイムアウトを実装する
        result_holder: Dict[str, Any] = {}
        done_event = threading.Event()

        def _init_ray_inner() -> None:
            try:
                if not ray.is_initialized():
                    ray.init(address="auto", ignore_reinit_error=True)
                result_holder["ok"] = True
            except Exception as exc:
                result_holder["error"] = str(exc)
            finally:
                done_event.set()

        init_thread = threading.Thread(target=_init_ray_inner, daemon=True, name="ray-init-bg")
        init_thread.start()

        finished = done_event.wait(timeout=30)

        if not finished:
            logger.warning(
                "try_ray_init_background: ray.init() が 30 秒以内に完了しませんでした。"
                " subprocess 接続は有効なまま継続します。"
            )
            return

        if result_holder.get("ok"):
            _ray_initialized = True
            logger.info("try_ray_init_background: ray.init() 成功 — _ray_initialized = True")
        else:
            logger.warning(
                "try_ray_init_background: ray.init() 失敗 (%s) — subprocess 接続は有効なまま継続",
                result_holder.get("error", "不明なエラー"),
            )

    bg_thread = threading.Thread(target=_worker, daemon=True, name="ray-init-bg-outer")
    bg_thread.start()
    logger.debug("try_ray_init_background: バックグラウンドスレッドを起動しました")


def init_ray(address: Optional[str] = None, force: bool = False) -> bool:
    """Ray クラスタに接続する。

    force=True の場合は SS_CLUSTER_MODE に関わらず接続を試みる（UI からの手動起動用）。
    ray 未インストール / 接続失敗時は WARN ログのみで False を返す。
    成功時は True を返す。
    """
    global _ray_initialized

    # クラスタモードが off かつ force でなければ何もしない
    mode = getattr(settings, "ss_cluster_mode", "off")
    if mode != "ray" and not force:
        logger.debug("init_ray: SS_CLUSTER_MODE=%s のためスキップ", mode)
        return False

    if _ray_initialized:
        logger.debug("init_ray: 既に初期化済み")
        return True

    # ray を _import_ray() 経由で取得（テストで差し替え可能）
    try:
        ray = _import_ray()
    except Exception as exc:  # ImportError 以外もキャッチ
        logger.warning("init_ray: ray を import できません (%s)。同期フォールバックに切替。", exc)
        return False

    target_address = address or getattr(settings, "ss_ray_address", "auto")

    try:
        if not ray.is_initialized():
            ray.init(address=target_address, ignore_reinit_error=True)
        _ray_initialized = True
        logger.info("init_ray: Ray クラスタ接続成功 address=%s", target_address)
        return True
    except Exception as exc:
        logger.warning("init_ray: Ray 接続に失敗 address=%s err=%s", target_address, exc)
        return False


def shutdown_ray() -> None:
    """Ray クラスタから切断する。未接続なら no-op。"""
    global _ray_initialized, _ray_subprocess_connected

    if not _ray_initialized and not _ray_subprocess_connected:
        return

    if _ray_initialized:
        try:
            import ray  # type: ignore
            if ray.is_initialized():
                ray.shutdown()
            logger.info("shutdown_ray: Ray クラスタを停止しました")
        except Exception as exc:
            logger.warning("shutdown_ray: 停止時に例外 (%s) — 無視", exc)
        finally:
            _ray_initialized = False

    _ray_subprocess_connected = False
    logger.info("shutdown_ray: Ray 接続フラグをクリアしました")
    try:
        from backend.benchmark.devices import invalidate_cache
        invalidate_cache()
    except Exception:
        pass
