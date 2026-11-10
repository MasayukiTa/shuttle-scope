"""昇格 override の保存は、途中で落ちても・同時に走っても・ファイルが壊れていても、データを失わない。

以前の実装は open("w") で先に空にしてから書き、読み込みの失敗を空として扱っていた。
書き込み中に落ちる (または壊れた) と、次の保存で全 override が消え、監査ログは
読み込みに失敗すると空から書き直されて履歴ごと消えた。同時に 2 件走ると片方が失われた。
"""
import json
import threading
import time

import pytest

from backend.analysis import promotion_override_store as store


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_OVERRIDE_FILE", tmp_path / "promotion_overrides.json")
    monkeypatch.setattr(store, "_AUDIT_LOG_FILE", tmp_path / "promotion_audit_log.json")
    return tmp_path


def test_roundtrip_with_audit(paths):
    e = store.save_override("epv", "hold", note="要確認", analyst="admin")
    assert e["status"] == "hold" and store.get_override("epv")["note"] == "要確認"
    store.save_override("epv", "promotion_ready", analyst="admin")
    assert store.delete_override("epv", analyst="admin") is True
    actions = [(a["action"], a["old_status"], a["new_status"]) for a in reversed(store.get_audit_log("epv"))]
    assert actions == [("create", None, "hold"), ("update", "hold", "promotion_ready"), ("delete", "promotion_ready", None)]
    assert store.get_override("epv") is None


def test_a_corrupt_override_file_is_not_overwritten(paths):
    store.save_override("epv", "hold", analyst="a")
    (paths / "promotion_overrides.json").write_text("{ broken", encoding="utf-8")
    assert store.load_all_overrides() == {}                       # 読み取りは空を返すだけ
    with pytest.raises(store.StoreCorruptError):
        store.save_override("q", "hold", analyst="a")             # 書き込みは止まる
    assert (paths / "promotion_overrides.json").read_text(encoding="utf-8") == "{ broken"   # 手で直せるよう残す


def test_a_corrupt_audit_log_is_never_rewritten_from_empty(paths):
    store.save_override("epv", "hold", analyst="a")
    audit = paths / "promotion_audit_log.json"
    audit.write_text("[ {broken", encoding="utf-8")
    with pytest.raises(store.StoreCorruptError):
        store.save_override("q", "hold", analyst="a")
    assert audit.read_text(encoding="utf-8") == "[ {broken"       # 履歴を空から書き直さない
    assert "q" not in store.load_all_overrides()                  # 記録のできない変更は行わない


def test_a_failed_write_leaves_the_previous_file(paths, monkeypatch):
    store.save_override("epv", "hold", analyst="a")
    before = (paths / "promotion_overrides.json").read_text(encoding="utf-8")
    real_replace = store.os.replace

    def boom(src, dst):
        if str(dst).endswith("promotion_overrides.json"):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        store.save_override("q", "hold", analyst="a")
    monkeypatch.setattr(store.os, "replace", real_replace)
    assert (paths / "promotion_overrides.json").read_text(encoding="utf-8") == before
    assert not list(paths.glob("*.tmp-*"))                        # 一時ファイルを残さない


def test_concurrent_saves_are_not_lost(paths, monkeypatch):
    """読んでから書くまでの間に別の保存が入ると、片方が失われる。読み込みに間を入れて重ねる。"""
    real = store._read_json

    def slow(*a, **k):
        r = real(*a, **k)
        time.sleep(0.01)
        return r

    monkeypatch.setattr(store, "_read_json", slow)
    n = 12
    errors = []

    def work(i):
        try:
            store.save_override(f"t{i}", "hold", analyst="a")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert set(store.load_all_overrides()) == {f"t{i}" for i in range(n)}
    assert len(json.loads((paths / "promotion_audit_log.json").read_text(encoding="utf-8"))) == n
