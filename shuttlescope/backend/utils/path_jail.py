"""パスジェイル: 指定ルート外へのファイルアクセスを封鎖するユーティリティ。

HDD に別用途データ（ドローン映像等）が存在する環境で、
ShuttleScope のファイル操作が許可された領域外に出ないことを保証する。

重要:
  - Path.resolve() はシンボリックリンク/ジャンクションを解決する（CPython 3.6+）
  - これにより `app/data/link_to_drone` のような攻撃を防ぐ
  - ただし resolve() は存在しないパスでも動作する → 書き込み前のチェックにも使える
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union


def resolve_within(
    target: Union[str, Path],
    root: Union[str, Path],
) -> Path:
    """target を resolve（シンボリックリンク追跡）し、root 内にあることを検証して返す。

    root 外に出る（../ やシンボリックリンク経由を含む）場合は ValueError を送出する。
    """
    resolved = Path(target).resolve()
    root_resolved = Path(root).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise ValueError(
            f"[path_jail] アクセス拒否: '{resolved}' は許可されたルート '{root_resolved}' の外です"
        )
    return resolved


def is_within(
    target: Union[str, Path],
    root: Union[str, Path],
) -> bool:
    """target が root 内にある場合 True を返す。例外を送出しない。"""
    try:
        resolve_within(target, root)
        return True
    except (ValueError, OSError):
        return False


def assert_safe_filename(name: str) -> str:
    """ファイル名にディレクトリセパレータやパストラバーサルが含まれないことを確認する。"""
    if any(c in name for c in ('/', '\\', '\x00')):
        raise ValueError(f"[path_jail] 不正なファイル名: {name!r}")
    if name in ('.', '..'):
        raise ValueError(f"[path_jail] 不正なファイル名: {name!r}")
    return name


# ─── 動画パス専用のジェイル ─────────────────────────────────────────────────

_BACKEND_DATA = Path(__file__).resolve().parent.parent / "data"


def allowed_video_roots() -> List[Path]:
    """動画アクセスが許可されているルートディレクトリ一覧を返す。

    含まれる:
      - backend/data/             (録画・クリップなどアプリ生成物)
      - ss_video_root             (設定された動画インポートディレクトリ)
      - ss_live_archive_root      (HDD 上のアーカイブルート)
      - ss_video_extra_roots      (ユーザーが明示的に許可した追加ディレクトリ; ; 区切り)

    HDD 上の他データ（ドローン映像等）は含まれない。
    """
    roots: List[Path] = [_BACKEND_DATA]
    try:
        from backend.config import settings
        for attr in ("ss_video_root", "ss_live_archive_root"):
            v = (getattr(settings, attr, "") or "").strip()
            if v:
                roots.append(Path(v))
        extra = (getattr(settings, "ss_video_extra_roots", "") or "").strip()
        if extra:
            for part in extra.split(";"):
                part = part.strip()
                if part:
                    roots.append(Path(part))
    except Exception:
        pass
    # 重複と存在しないパスは保持（resolve は存在チェックしない）
    seen: dict[str, Path] = {}
    for r in roots:
        try:
            key = str(r.resolve()).lower()
            if key not in seen:
                seen[key] = r.resolve()
        except Exception:
            continue
    return list(seen.values())


def assert_allowed_video_path(path: Union[str, Path]) -> Path:
    """動画ファイルパスが許可されたルート内にあることを確認する。

    - シンボリックリンクは resolve() で解決される
    - HDD 上の archive root 外にあるパスはここで拒否される
    - 許可されたルート: allowed_video_roots() 参照

    違反時は ValueError を送出する。
    """
    real = Path(path).resolve()
    for root in allowed_video_roots():
        try:
            real.relative_to(root)
            return real
        except ValueError:
            continue
    raise ValueError(
        f"[path_jail] 動画パス拒否: '{real}' は許可されたいずれのルートにも含まれません。"
        f" 許可ルート: {[str(r) for r in allowed_video_roots()]}"
    )


def is_allowed_video_path(path: Union[str, Path]) -> bool:
    """動画ファイルパスが許可されたルート内にある場合 True。例外を送出しない。"""
    try:
        assert_allowed_video_path(path)
        return True
    except (ValueError, OSError):
        return False


def normalize_match_local_path(video_local_path: Optional[str]) -> Optional[Path]:
    """Match.video_local_path (localfile:/// 形式 or 生パス) を Path に正規化する。

    URL スキーム (http/https/server) の場合は None を返す。
    """
    if not video_local_path:
        return None
    raw = video_local_path
    if raw.startswith(("http://", "https://", "server://")):
        return None
    if raw.startswith("localfile:///"):
        raw = raw[len("localfile:///"):]
    return Path(raw)


def assert_match_video_path_allowed(video_local_path: Optional[str]) -> None:
    """Match.video_local_path がローカルファイルなら path_jail でチェックする。

    URL スキーム (http/https/server) の場合は何もしない（外部 URL は別経路）。
    違反時は ValueError を送出する。呼び出し側は HTTPException 等に変換すること。
    """
    p = normalize_match_local_path(video_local_path)
    if p is None:
        return
    if not is_allowed_video_path(p):
        raise ValueError(
            f"[path_jail] 動画パスが許可ルート外です: {p}"
        )
