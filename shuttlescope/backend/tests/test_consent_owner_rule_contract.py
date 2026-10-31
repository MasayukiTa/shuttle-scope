"""owner 方針 (2026-10-31) の backend 側契約を固定する。

文書が改定されたとき、再同意を求めるのは改定された文書に紐づく同意だけ、という
方針の「per-document 再同意判定」は frontend (OnboardingConsentPage) が、同意
レコードに付随する privacy_policy_version / terms_version を現行版と突き合わせて
行う。そのために backend が満たすべき契約は次の 2 点:

1. /auth/consents が返す current_versions に、少なくとも privacy_policy と terms
   の両方 (frontend が突き合わせに使う 2 軸) が含まれること。これが欠けると
   frontend は「一致を確認できない」= 全件再同意に倒れてしまう。

2. 任意同意の「未回答」gate (_optional_consent_pending, /auth/me の
   optional_consent_pending) は、文書バージョンに依存せず「回答レコードが 1 度でも
   存在するか」だけで判定すること。再同意を促す prefill ロジック (owner 方針) とは
   別軸であり、gate をバージョン依存にすると、過去に回答済みのユーザが文書改定の
   たびに毎回ブロックされてしまう。この分離を回帰で固定する。

どちらも DB を使わない純粋な契約テスト。
"""
from backend.routers.auth import (
    CURRENT_PRIVACY_VERSION,
    CURRENT_TERMS_VERSION,
    CURRENT_DCT_VERSION,
    _OPTIONAL_CONSENT_TYPES,
    _PROMPTED_OPTIONAL_CONSENT_TYPES,
    _optional_consent_pending,
)


def test_current_versions_expose_privacy_and_terms_for_per_document_compare():
    # frontend は privacy / terms の 2 軸で record を突き合わせる。
    # 両方が非空で提供されていること (= 突き合わせ可能) を固定する。
    assert isinstance(CURRENT_PRIVACY_VERSION, str) and CURRENT_PRIVACY_VERSION
    assert isinstance(CURRENT_TERMS_VERSION, str) and CURRENT_TERMS_VERSION
    # data_contribution も現行版として提供される (将来の per-document 拡張のため)。
    assert isinstance(CURRENT_DCT_VERSION, str) and CURRENT_DCT_VERSION


def test_pending_gate_is_version_independent():
    # 「全提示項目に回答済み」なら、文書バージョンに関係なく pending=False。
    assert _optional_consent_pending(set(_PROMPTED_OPTIONAL_CONSENT_TYPES)) is False
    # 1 件も回答が無ければ pending=True。
    assert _optional_consent_pending(set()) is True
    # gate は recorded_types (= 回答の有無) だけを見るので、どのバージョンで
    # 回答したかの情報は引数に一切現れない。これが owner 方針の prefill (再同意)
    # とは別軸であることの担保。
    assert _optional_consent_pending.__code__.co_argcount == 1


def test_pending_gate_only_counts_prompted_optional_types():
    # cross_border_transfer は UI 非提示なので gate 対象外 (提示集合は真部分集合)。
    assert _PROMPTED_OPTIONAL_CONSENT_TYPES < _OPTIONAL_CONSENT_TYPES
    # 提示される任意同意の一部しか回答していなければ pending のまま。
    partial = set(list(_PROMPTED_OPTIONAL_CONSENT_TYPES)[:1])
    if partial != _PROMPTED_OPTIONAL_CONSENT_TYPES:
        assert _optional_consent_pending(partial) is True
