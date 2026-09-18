"""S-9: `SS_` 付きの環境変数が本当に効くかのテスト。

Settings には env_prefix が無いので、`SS_FOO` という環境変数は**読まれない**
— フィールド名 `FOO` がそのまま env 名になる。ところがコメントも運用手順も
長らく `SS_` 付きで書かれていた。実測:

    SS_ALLOW_LOOPBACK_NO_AUTH=0 を設定しても ALLOW_LOOPBACK_NO_AUTH は True

つまり **本番で loopback 無認証バイパスを閉じる手順が、手順どおりに実行しても
何もしていなかった。** 同じことが PUBLIC_MODE / HIDE_API_DOCS /
HIDE_STACK_TRACES / PUBLIC_HOSTNAME にも起きていた。

既存デプロイが素の名前を使っている可能性があるので、名前を変えるのではなく
両方を受けるようにした。ここでは **両方の綴りが効くこと** を固定する。
片方だけ通るようになったら、それは退行。
"""
from __future__ import annotations

import pytest

from backend.config import Settings


# (env 名の素の部分, 設定する値, 期待値)
BOOL_SWITCHES = [
    ("ALLOW_LOOPBACK_NO_AUTH", "0", False),
    ("PUBLIC_MODE", "1", True),
    ("HIDE_API_DOCS", "1", True),
    ("HIDE_STACK_TRACES", "1", True),
]

ALL_ENV_NAMES = [n for n, _, _ in BOOL_SWITCHES] + ["PUBLIC_HOSTNAME"]


@pytest.fixture()
def clean_env(monkeypatch):
    """対象の env をすべて消してから個別に設定できるようにする。"""
    for name in ALL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv("SS_" + name, raising=False)
    return monkeypatch


@pytest.mark.parametrize("field,value,expected", BOOL_SWITCHES)
@pytest.mark.parametrize("prefix", ["SS_", ""])
def test_both_spellings_take_effect(clean_env, prefix, field, value, expected):
    clean_env.setenv(prefix + field, value)
    s = Settings()
    assert getattr(s, field) is expected, (
        f"{prefix}{field}={value} が {field} に反映されていない。"
        " 運用手順は SS_ 付きで書かれているので、効かないと本番の防御が黙って開く。"
    )


@pytest.mark.parametrize("prefix", ["SS_", ""])
def test_public_hostname_is_a_real_field(clean_env, prefix):
    """PUBLIC_HOSTNAME は以前 Settings のフィールドですらなく、
    os.environ 直読みだったので `.env` に書いても効かなかった
    (backend に load_dotenv は無い)。"""
    clean_env.setenv(prefix + "PUBLIC_HOSTNAME", "app.example.com")
    s = Settings()
    assert s.PUBLIC_HOSTNAME == "app.example.com"


@pytest.mark.parametrize("prefix", ["SS_", ""])
def test_public_hostname_implies_production_posture(clean_env, prefix):
    clean_env.setenv(prefix + "PUBLIC_HOSTNAME", "app.example.com")
    clean_env.setenv("ENVIRONMENT", "development")
    assert Settings().is_production_posture is True


def test_loopback_switch_defaults_open(clean_env):
    """既定は True (Electron 単体運用の UX 維持)。
    本番はこれを 0 にする手順なので、既定が変わったら手順を見直すこと。"""
    clean_env.setenv("ENVIRONMENT", "development")
    assert Settings().ALLOW_LOOPBACK_NO_AUTH is True
