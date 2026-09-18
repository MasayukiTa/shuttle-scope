"""cluster.config.yaml 由来の .bat パスが SSH で実行される前に絞られること。

この値は worker 上で `cmd /c "{bat}"` に埋め込まれる。cmd は二重引用符の
**内側でも** `&` や `|` を解釈するので、`"` を 1 つ入れられた時点で
コマンドを継ぎ足せる。

同じ検証が head 再起動の一括処理にはあり、
`POST /cluster/nodes/{ip}/ray-restart` には**無かった**。
`POST /cluster/config` は `Dict[str, Any]` を無検証で書き込んでいたので、
設定を書ける相手はそこから**ワーカー上での任意コマンド実行**に到達できた。

規則を 2 箇所に分けて書いていたのが原因なので、1 つに寄せたうえで
その 1 つをここで固定する。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.routers.cluster import validate_worker_bat_path


# ── 通すもの ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    r"C:\Users\worker\Desktop\ray-restart.bat",
    r"C:/tools/ray/restart.cmd",
    r"D:\ops\restart script.bat",  # 空白は許容 (実際のパスに現れる)
])
def test_plain_windows_bat_paths_are_accepted(value):
    assert validate_worker_bat_path(value) == value


# ── 弾くもの ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    # cmd の引用符を閉じてコマンドを継ぎ足す
    'C:\\x.bat" & calc & "',
    "C:\\x.bat' & calc",
    # 区切り記号
    r"C:\x.bat & calc",
    r"C:\x.bat | calc",
    r"C:\x.bat ; calc",
    # 変数展開
    r"C:\x.bat %COMSPEC%",
    "C:\\x.bat `calc`",
    r"C:\x.bat $(calc)",
    # 改行でコマンドを分ける
    "C:\\x.bat\ncalc",
    "C:\\x.bat\r\ncalc",
    # 拡張子が違う / 絶対パスでない / UNC
    r"C:\x.exe",
    r"x.bat",
    r"\\server\share\x.bat",
    # 型が違う
    None,
    123,
    {"path": r"C:\x.bat"},
])
def test_dangerous_or_malformed_values_are_refused(value):
    with pytest.raises(HTTPException) as e:
        validate_worker_bat_path(value)
    assert e.value.status_code == 400
