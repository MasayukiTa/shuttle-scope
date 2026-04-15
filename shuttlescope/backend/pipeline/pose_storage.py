"""PoseFrame.landmarks_json の圧縮/解凍 helper。

1 試合 ~54k フレーム × 2 選手 × 33 landmarks で JSON が 300MB 級になるため、
landmarks を gzip 圧縮して DB (Text/BLOB いずれも可) に格納する。

- エンコード: json.dumps → gzip.compress(level=6) で bytes を返す
- デコード: gzip マジックバイト (0x1f, 0x8b) を検出して自動判別。
  旧形式 (非圧縮 JSON 文字列) もそのまま decode できる後方互換 reader。

将来 parquet 等に差し替えたくなった場合は本 helper のみ置換すれば済む。
"""
from __future__ import annotations

import gzip
import json
from typing import Any, Union

# gzip マジックバイト
_GZIP_MAGIC = b"\x1f\x8b"


def encode_landmarks(landmarks: list[dict] | list[list] | Any) -> bytes:
    """landmarks を JSON 化し gzip 圧縮した bytes を返す。

    DB カラムが Text の場合でも SQLite は bytes を BLOB として透過的に
    保存できるため、スキーマ変更なしで使用可能。
    """
    payload = json.dumps(landmarks, ensure_ascii=False, separators=(",", ":"))
    return gzip.compress(payload.encode("utf-8"), compresslevel=6)


def decode_landmarks(raw: Union[bytes, bytearray, memoryview, str, None]) -> list:
    """保存された landmarks を復元する。

    - bytes で先頭が gzip マジックなら gzip として復号
    - それ以外の bytes / str は旧形式 (非圧縮 JSON) とみなして json.loads
    - None や空は空リストを返す
    """
    if raw is None:
        return []
    if isinstance(raw, (bytearray, memoryview)):
        raw = bytes(raw)
    if isinstance(raw, bytes):
        if raw[:2] == _GZIP_MAGIC:
            text = gzip.decompress(raw).decode("utf-8")
        else:
            # 旧形式: UTF-8 JSON 文字列が bytes で返った場合
            text = raw.decode("utf-8")
    elif isinstance(raw, str):
        if not raw:
            return []
        # SQLite が BLOB を latin-1 文字列として返すケースへの保険
        if raw.startswith("\x1f\x8b"):
            text = gzip.decompress(raw.encode("latin-1")).decode("utf-8")
        else:
            text = raw
    else:
        raise TypeError(f"decode_landmarks: 未対応の型 {type(raw)!r}")
    return json.loads(text)
