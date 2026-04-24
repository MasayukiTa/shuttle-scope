"""パストラバーサル対策ユーティリティ"""
from pathlib import Path
from fastapi import HTTPException


def safe_path(base_dir: str | Path, user_input: str | Path) -> Path:
    """user_input を base_dir 配下に限定して解決する。

    base_dir の外を指す場合は 403 を返す。
    シンボリックリンクは resolve() で展開してから検証する。
    """
    base = Path(base_dir).resolve()
    target = (base / user_input).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="指定パスはベースディレクトリ外です")
    return target
