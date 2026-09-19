"""cluster.config.yaml に SSH パスワードの平文を置かない。

2026-04-24 から約5か月、`shuttlescope/cluster.config.yaml` に
ワーカー機の SSH パスワードが平文で入ったまま public リポジトリに置かれていた。

設計自体は最初から「YAML には置かず env から読む」つもりで、
`topology._redact_secrets` は save のたびに値をセンチネルへ書き換える。
ところが読み出し側は 4 箇所あり、**env を見るのは 1 箇所だけ**だった:

| 読み出し | 修正前 |
|---|---|
| `remote_tasks._get_worker_ssh_creds` | env → YAML（正しい） |
| `routers/cluster.py` head 一括再起動 | YAML を素で読む |
| `routers/cluster.py` ray-restart | YAML を素で読む |
| `benchmark/devices._probe_ssh_workers` | YAML を素で読む |

素で読む 3 箇所は、save が一度走ると `"SSH_PASSWORD_REDACTED"` という
**文字列そのものを SSH のパスワードとして送る**（devices は「SSH 不可」と
誤判定する）。つまり「YAML から平文を消す」と壊れる作りになっていた。
規則を 1 つにまとめ、平文を消しても動くことをここで固定する。
"""
from __future__ import annotations

import pathlib

import pytest

from backend.cluster.topology import REDACTED_PASSWORD, resolve_worker_ssh_password


_REPO_YAML = pathlib.Path(__file__).resolve().parents[2] / "cluster.config.yaml"


class TestTheConfigFileHoldsNoPlaintextPassword:
    def test_committed_yaml_has_no_plaintext_ssh_password(self):
        """追跡されている cluster.config.yaml に平文が戻っていないこと。"""
        if not _REPO_YAML.exists():
            pytest.skip("cluster.config.yaml が無い環境")
        import yaml

        cfg = yaml.safe_load(_REPO_YAML.read_text(encoding="utf-8")) or {}
        workers = ((cfg.get("network") or {}).get("workers") or [])
        assert workers, "workers が空だと検査にならない"
        for w in workers:
            pwd = (w or {}).get("ssh_password")
            assert pwd in (None, "", REDACTED_PASSWORD), (
                f"cluster.config.yaml の worker {w.get('id') or w.get('ip')!r} に "
                f"平文の ssh_password が入っている"
            )


class TestResolveWorkerSshPassword:
    def test_the_redaction_sentinel_is_not_a_password(self, monkeypatch):
        monkeypatch.delenv("SS_K10_SSH_PASSWORD", raising=False)
        monkeypatch.delenv("SS_WORKER_SSH_PASSWORD", raising=False)
        worker = {"id": "k10", "ssh_password": REDACTED_PASSWORD}
        assert resolve_worker_ssh_password(worker) is None

    def test_empty_and_missing_are_none(self, monkeypatch):
        monkeypatch.delenv("SS_K10_SSH_PASSWORD", raising=False)
        monkeypatch.delenv("SS_WORKER_SSH_PASSWORD", raising=False)
        assert resolve_worker_ssh_password({"id": "k10"}) is None
        assert resolve_worker_ssh_password({"id": "k10", "ssh_password": "   "}) is None

    def test_env_is_used_when_yaml_is_redacted(self, monkeypatch):
        monkeypatch.delenv("SS_K10_SSH_PASSWORD", raising=False)
        monkeypatch.setenv("SS_WORKER_SSH_PASSWORD", "from-env")
        worker = {"id": "k10", "ssh_password": REDACTED_PASSWORD}
        assert resolve_worker_ssh_password(worker) == "from-env"

    def test_per_worker_env_beats_the_shared_one(self, monkeypatch):
        monkeypatch.setenv("SS_WORKER_SSH_PASSWORD", "shared")
        monkeypatch.setenv("SS_K10_SSH_PASSWORD", "k10-common")
        monkeypatch.setenv("SS_GMK_SSH_PASSWORD", "per-worker")
        assert resolve_worker_ssh_password({"id": "gmk"}) == "per-worker"

    def test_env_beats_a_plaintext_yaml_value(self, monkeypatch):
        """YAML に平文が残っていても env が勝つ（移行中に両方ある場合）。"""
        monkeypatch.delenv("SS_K10_SSH_PASSWORD", raising=False)
        monkeypatch.setenv("SS_WORKER_SSH_PASSWORD", "from-env")
        worker = {"id": "k10", "ssh_password": "still-in-yaml"}
        assert resolve_worker_ssh_password(worker) == "from-env"

    def test_a_non_dict_worker_does_not_raise(self):
        assert resolve_worker_ssh_password(None) is None  # type: ignore[arg-type]
        assert resolve_worker_ssh_password("k10") is None  # type: ignore[arg-type]


class TestEveryReaderGoesThroughTheResolver:
    """読み出し側が YAML を素で読んでいないこと。

    「resolver を足した」だけでは、素で読む行が残っていれば意味がない。
    修正前はこの検査が 3 箇所で落ちる。
    """

    _READERS = [
        "backend/routers/cluster.py",
        "backend/benchmark/devices.py",
        "backend/cluster/remote_tasks.py",
    ]

    def test_no_reader_takes_ssh_password_straight_from_the_mapping(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        offenders: list[str] = []
        for rel in self._READERS:
            path = root.parent / rel
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # `.get("ssh_password")` / `["ssh_password"]` で値を取り出す形
                if '.get("ssh_password")' in stripped or '["ssh_password"]' in stripped:
                    offenders.append(f"{rel}:{i}: {stripped}")
        assert not offenders, (
            "ssh_password を設定ファイルから素で読んでいる箇所が残っている:\n"
            + "\n".join(offenders)
        )
