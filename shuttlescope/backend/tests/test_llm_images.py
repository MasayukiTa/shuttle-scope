"""LLM チャットの画像 (マルチモーダル) 入力サポートのテスト。
ネットワークは張らず、検証ロジック / content 構築 / config / エンドポイント拒否を検証する。"""
import base64
import os

from fastapi.testclient import TestClient

from backend.main import app
from backend.routers.llm_chat import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    _build_multimodal_content,
    _validate_images,
)
from backend.utils.jwt_utils import create_access_token


def _hdr(uid: int, role: str):
    return {"Authorization": f"Bearer {create_access_token(user_id=uid, role=role, minutes=10)}"}


def _dataurl(mime: str = "image/png", raw: bytes = b"\x89PNG\r\n\x1a\n") -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _with_env(**kv):
    class _C:
        def __enter__(self):
            self.old = {k: os.environ.get(k) for k in kv}
            for k, v in kv.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        def __exit__(self, *a):
            for k, v in self.old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _C()


# ── _validate_images ─────────────────────────────────────────────────────────

def test_validate_empty_returns_empty():
    assert _validate_images([]) == []


def test_validate_accepts_allowed_mimes():
    metas = _validate_images([_dataurl("image/png"), _dataurl("image/jpeg"),
                              _dataurl("image/webp"), _dataurl("image/gif")])
    assert len(metas) == 4
    assert {m["mime"] for m in metas} == {"image/png", "image/jpeg", "image/webp", "image/gif"}


def test_validate_rejects_too_many():
    import pytest
    from fastapi import HTTPException
    imgs = [_dataurl() for _ in range(MAX_IMAGES + 1)]
    with pytest.raises(HTTPException) as ei:
        _validate_images(imgs)
    assert ei.value.status_code == 422


def test_validate_rejects_bad_mime():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        _validate_images([_dataurl("image/bmp")])
    assert ei.value.status_code == 422


def test_validate_rejects_non_dataurl():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        _validate_images(["https://example.com/x.png"])
    assert ei.value.status_code == 422


def test_validate_rejects_broken_base64():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        _validate_images(["data:image/png;base64,@@@not-base64@@@"])
    assert ei.value.status_code == 422


def test_validate_rejects_oversized():
    import pytest
    from fastapi import HTTPException
    big = b"\x00" * (MAX_IMAGE_BYTES + 1)
    with pytest.raises(HTTPException) as ei:
        _validate_images([_dataurl("image/png", big)])
    assert ei.value.status_code == 422


# ── _build_multimodal_content ────────────────────────────────────────────────

def test_build_multimodal_content_shape():
    url = _dataurl()
    parts = _build_multimodal_content("hello", [url])
    assert parts[0] == {"type": "text", "text": "hello"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"] == url


def test_build_multimodal_content_text_optional():
    parts = _build_multimodal_content("", [_dataurl()])
    # text が空なら text part は付かず、image part のみ。
    assert all(p["type"] == "image_url" for p in parts)
    assert len(parts) == 1


# ── /llm/config が capability を surface する ─────────────────────────────────

def test_config_exposes_vision_and_tools_flags():
    with TestClient(app) as client:
        r = client.get("/api/llm/config", headers=_hdr(9201, "llm"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "vision_available" in body
        assert "tools_available" in body
        assert "reasoning_available" in body


# ── エンドポイント: vision 未対応時は画像送信を 422 で拒否 ────────────────────

def test_post_message_with_images_rejected_when_vision_off():
    """LLM_VISION 未設定 (既定) の状態で画像を送ると 422 (silent drop しない)。"""
    with _with_env(LLM_VISION=None):
        with TestClient(app) as client:
            c = client.post("/api/llm/conversations", json={}, headers=_hdr(9202, "llm"))
            cid = c.json()["id"]
            r = client.post(f"/api/llm/conversations/{cid}/messages",
                            json={"content": "見て", "images": [_dataurl()]},
                            headers=_hdr(9202, "llm"))
        assert r.status_code == 422, r.text
        assert "未対応" in r.json()["detail"]


def test_post_message_invalid_image_is_422_before_ratelimit():
    """壊れた data URL は vision 設定に関係なく 422 (検証は副作用より前)。"""
    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={}, headers=_hdr(9203, "llm"))
        cid = c.json()["id"]
        r = client.post(f"/api/llm/conversations/{cid}/messages",
                        json={"content": "x", "images": ["not-a-data-url"]},
                        headers=_hdr(9203, "llm"))
    assert r.status_code == 422


def test_post_message_no_images_still_works_contract():
    """画像なしの既存契約は不変 (provider 未設定なら 503/429、画像検証で落ちない)。"""
    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={}, headers=_hdr(9204, "llm"))
        cid = c.json()["id"]
        r = client.post(f"/api/llm/conversations/{cid}/messages",
                        json={"content": "hello"}, headers=_hdr(9204, "llm"))
    assert r.status_code in (503, 429)
