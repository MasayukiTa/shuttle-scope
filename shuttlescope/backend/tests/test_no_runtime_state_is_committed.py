"""実行時に書かれるファイルがリポジトリに入っていないことを見る。

`backend/data/worker.lock` が **tracked** だった（`31dc6f1` で一緒に入った）。
中身は誰かの機械の PID `21036`。影響:

- `services/status_monitor._check_worker` は「lock があって PID 生存 → 稼働中 /
  lock があって PID 死亡 → **応答なし (DEGRADED)**」と判定する。
  clone したてでワーカーを起動していなくても lock が存在するので、
  ステータスページが**存在しないワーカーの異常を報告する**。
  PID が別プロセスに再利用されていれば逆に「稼働中」と報告する
- テストを 1 回走らせるとワーカー関連のコードが lock を消すので、
  **毎回作業ツリーが汚れる**

`.gitignore` には最初から書いてあったが、**ignore は既に tracked なファイルを
外さない**。commit された後にルールを足しても効かない。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[3]

#: 実行時に生成される＝コミットしてはいけないファイル名の断片。
_RUNTIME_ARTIFACTS = (
    ".lock",
    ".pid",
    ".sqlite-journal",
    ".sqlite-wal",
    ".db-journal",
)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [l for l in out.split("\n") if l]


def test_no_lock_or_pid_file_is_tracked():
    offenders = [
        f for f in _tracked_files()
        if any(f.lower().endswith(suffix) for suffix in _RUNTIME_ARTIFACTS)
        # package-lock.json / poetry.lock 等の依存ロックは別物
        and not f.endswith(("package-lock.json", "poetry.lock", "Cargo.lock", "uv.lock"))
    ]
    assert not offenders, (
        "実行時に書かれるファイルがコミットされている。"
        "clone しただけで「ワーカーが動いている / 落ちている」と誤判定される:\n  "
        + "\n  ".join(offenders)
    )


def test_the_snapshot_writer_creates_its_own_directory(tmp_path):
    """`backend/data/` が無い clone でも attack_pattern の flush が通ること。

    worker.lock を untrack すると `backend/data/` は clone に現れなくなる。
    `flush_to_file` はディレクトリを作らず、失敗を warning に落として
    握りつぶしていたので、**5 分ごとの flush が一度も成功しないまま
    静かに終わる**状態になるところだった。
    """
    from backend.utils import attack_pattern

    target = tmp_path / "does" / "not" / "exist" / "attack_pattern.json"
    attack_pattern.flush_to_file(str(target))
    assert target.exists(), "保存先ディレクトリを作っていない"
