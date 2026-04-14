"""ブラウザ中継用リアルタイム YOLO WebSocket

オペレーター PC 側のフロントが MediaStream から抽出した JPEG フレームを送ると、
yolov8n (person class) の検出結果を JSON で返す。

- セッション毎に独立したワーカー（接続ごとに 1 タスク）。複数オペレーター PC の
  並列接続は session_code + 接続 ID で区別し、バックエンド内部の共有状態なし
- 重処理のバッチ YOLO (`yolo.py`) とは完全に独立
- モデル未配置時は接続直後に 1008 (policy violation) で閉じる
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

from backend.cv import yolov8n

logger = logging.getLogger(__name__)

# 送信側レートリミット（同時推論のスタックを防ぐ）
_MAX_INFLIGHT = 1
# 1 接続あたりの最大 JPEG バイト数（640x480 JPEG 0.5 ~ 30KB 目安）
_MAX_FRAME_BYTES = 500 * 1024


async def ws_realtime_yolo_handler(session_code: str, websocket: WebSocket) -> None:
    await websocket.accept()

    if not yolov8n.is_available():
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "reason": "model_not_available",
                "message": "yolov8n.onnx が backend/models/ に配置されていません",
            }))
        finally:
            await websocket.close(code=1008)
        return

    await websocket.send_text(json.dumps({"type": "ready", "session": session_code}))

    loop = asyncio.get_event_loop()
    inflight = 0
    client = f"{session_code}:{id(websocket) & 0xFFFFFF:06x}"
    logger.info("[realtime-yolo] connected %s", client)

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data is None:
                # テキスト（ping 等）は単純に ack
                text = msg.get("text")
                if text:
                    try:
                        obj = json.loads(text)
                    except Exception:
                        obj = None
                    if isinstance(obj, dict) and obj.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            if len(data) == 0 or len(data) > _MAX_FRAME_BYTES:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "reason": "frame_size",
                    "size": len(data),
                }))
                continue

            if inflight >= _MAX_INFLIGHT:
                # バックプレッシャ: 直前フレームをスキップ
                await websocket.send_text(json.dumps({"type": "skipped"}))
                continue

            inflight += 1
            t0 = time.perf_counter()
            try:
                dets = await loop.run_in_executor(None, yolov8n.infer_jpeg, data)
            except Exception as e:  # pragma: no cover
                logger.warning("[realtime-yolo] infer error: %s", e)
                dets = []
            finally:
                inflight -= 1
            dt_ms = (time.perf_counter() - t0) * 1000.0

            payload = {
                "type": "detections",
                "infer_ms": round(dt_ms, 1),
                "boxes": [
                    {
                        "x1": round(d.x1, 4),
                        "y1": round(d.y1, 4),
                        "x2": round(d.x2, 4),
                        "y2": round(d.y2, 4),
                        "conf": round(d.conf, 3),
                    }
                    for d in dets
                ],
            }
            await websocket.send_text(json.dumps(payload))

    except WebSocketDisconnect:
        pass
    except Exception as e:  # pragma: no cover
        logger.warning("[realtime-yolo] handler error %s: %s", client, e)
    finally:
        logger.info("[realtime-yolo] closed %s", client)
