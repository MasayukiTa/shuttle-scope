"""INFRA Phase D: cluster.bootstrap の最低保証テスト

- SS_CLUSTER_MODE=off のとき init_ray が no-op
- ray 未インストール (= import 失敗) 時でも init_ray は例外を投げず WARN のみ
"""
from __future__ import annotations

import builtins
import logging

import pytest

from backend.cluster import bootstrap


def test_init_ray_noop_when_cluster_mode_off(monkeypatch, caplog):
    """SS_CLUSTER_MODE=off のとき init_ray は False を返し ray を触らない"""
    monkeypatch.setattr(bootstrap.settings, "ss_cluster_mode", "off", raising=False)

    # ray を import しようとしないことを、import を壊してでも確認する
    real_import = builtins.__import__

    def _guard(name, *args, **kwargs):
        if name == "ray" or name.startswith("ray."):
            raise AssertionError("off のとき ray を import してはならない")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guard)

    assert bootstrap.init_ray() is False


def test_init_ray_handles_missing_ray(monkeypatch, caplog):
    """ray 未インストール時に init_ray は WARN ログのみで例外を投げない"""
    monkeypatch.setattr(bootstrap.settings, "ss_cluster_mode", "ray", raising=False)
    # 多重 init ガードをリセット
    monkeypatch.setattr(bootstrap, "_ray_initialized", False, raising=False)

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "ray" or name.startswith("ray."):
            raise ImportError("simulated: ray not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with caplog.at_level(logging.WARNING, logger=bootstrap.logger.name):
        result = bootstrap.init_ray()

    assert result is False
    # 何らかの WARN が出ていること
    assert any(rec.levelno >= logging.WARNING for rec in caplog.records)


def test_shutdown_ray_noop_when_not_initialized(monkeypatch):
    """未起動時 shutdown_ray は no-op"""
    monkeypatch.setattr(bootstrap, "_ray_initialized", False, raising=False)
    # 例外を投げないこと
    bootstrap.shutdown_ray()
