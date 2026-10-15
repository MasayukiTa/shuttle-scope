"""role=player の JSON 応答を 1 箇所でサニタイズする純 ASGI ミドルウェア。

  - 対象: テーブル (backend.utils.player_response_sanitiser) に該当する GET/HEAD の
    application/json 応答 *のみ*。非 JSON / ストリーミング / ファイルは一切触らない
    (応答開始時に content-type を見て、JSON でなければバッファせず素通し)。
  - 対象ロール: 認証済みロールが player のとき *だけ*。admin / analyst / coach / demo は
    リクエストもレスポンスもバイト単位で素通し (ロール判定は get_auth と同じ関数)。
  - fail-closed: サニタイズ中の例外・パース不能・圧縮済み JSON は、未加工の本文を返さず 500。
  - Content-Length は書き換え後の本文から再計算する。
  - `result=win|loss` 等のクエリは player では無視する (クエリ文字列から取り除く)。
"""
from __future__ import annotations

import json
from typing import Any

from backend.utils.player_response_sanitiser import (
    keys_to_drop,
    query_params_to_drop,
    sanitize_for_player,
    strip_query_for_player,
)

_FAIL_BODY = b'{"detail":"player response could not be sanitised"}'


def _is_player(scope) -> bool:
    """get_auth と同じ規則でロールを決める。判定自体が壊れたら player 扱い (fail-closed)。"""
    try:
        from starlette.requests import Request
        from backend.utils.auth import get_auth

        return get_auth(Request(scope)).role == "player"
    except Exception:
        return True


class PlayerResponseSanitiserMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        method = scope.get("method") or "GET"
        drops_keys = bool(keys_to_drop(path, method))
        drops_query = bool(query_params_to_drop(path, method))
        if not (drops_keys or drops_query) or not _is_player(scope):
            await self.app(scope, receive, send)
            return

        if drops_query:
            qs = scope.get("query_string") or b""
            new_qs = strip_query_for_player(path, qs, method)
            if new_qs != qs:
                scope = dict(scope)
                scope["query_string"] = new_qs
        if not drops_keys:
            await self.app(scope, receive, send)
            return

        start_msg: dict[str, Any] | None = None
        chunks: list[bytes] = []
        buffering = False
        failed = False

        async def wrapped_send(message):
            nonlocal start_msg, buffering, failed
            if failed:
                return
            mtype = message["type"]
            if mtype == "http.response.start":
                headers = {k.lower(): v for k, v in message.get("headers", [])}
                ctype = headers.get(b"content-type", b"").lower()
                if ctype.startswith(b"application/json") or ctype.endswith(b"+json"):
                    buffering = True
                    start_msg = message
                    return
                await send(message)
                return
            if mtype == "http.response.body" and buffering:
                chunks.append(message.get("body", b"") or b"")
                if message.get("more_body", False):
                    return
                await _flush()
                return
            await send(message)

        async def _flush():
            nonlocal failed
            assert start_msg is not None
            try:
                hdrs = [(k, v) for k, v in start_msg.get("headers", [])]
                lower = {k.lower(): v for k, v in hdrs}
                if lower.get(b"content-encoding", b"identity") not in (b"identity", b""):
                    raise ValueError("encoded JSON body cannot be sanitised")
                raw = b"".join(chunks)
                if raw.strip():
                    body = json.dumps(
                        sanitize_for_player(path, json.loads(raw), method),
                        ensure_ascii=False, separators=(",", ":"),
                    ).encode("utf-8")
                else:
                    body = raw
                hdrs = [(k, v) for k, v in hdrs if k.lower() != b"content-length"]
                hdrs.append((b"content-length", str(len(body)).encode("ascii")))
                out_start = {**start_msg, "headers": hdrs}
            except Exception:
                failed = True
                body = _FAIL_BODY
                out_start = {
                    "type": "http.response.start", "status": 500,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode("ascii"))],
                }
            await send(out_start)
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, wrapped_send)
