"""例外文言をクライアントに返す前に、本番姿勢では秘匿する。

背景 (CodeQL py/stack-trace-exposure):
  例外の `str()` をそのまま API 応答に載せると、モデルの絶対パス・DB のカラム名・
  ONNX / CUDA ランタイムの内部エラー等が外部ユーザへ漏れ、後続攻撃の material に
  なる。`main.py` の汎用例外ハンドラは `is_production_posture` で既に秘匿している
  が、「例外を捕まえて **正常応答 (200) の一部** として返す」経路
  (レポートの section error、推論の debug 情報) はそのハンドラを通らないため、
  同じ判定を個別に通す必要がある。

判定は main.py と同じ `settings.is_production_posture` に一元化する。
これは PUBLIC_MODE / HIDE_API_DOCS / HIDE_STACK_TRACES / ENVIRONMENT=production /
SS_PUBLIC_HOSTNAME のいずれかで真になる fail-safe な統合判定なので、個別 env の
設定漏れで秘匿が外れる (fail-open する) ことがない。
"""
from __future__ import annotations

# 公開しても攻撃面情報を含まない汎用文言。
GENERIC_ERROR_JA = "内部エラーが発生しました"


def client_safe_error(
    exc: BaseException | str,
    *,
    limit: int = 200,
    generic: str = GENERIC_ERROR_JA,
) -> str:
    """クライアントへ返して安全な例外文言を返す。

    本番姿勢では固定の汎用文言、開発時は原因調査のため詳細を返す。

    呼び出し側の責務: 完全な情報は必ず logger 側に残すこと
    (この関数は記録を行わない。秘匿するのは「応答に載せる文字列」だけ)。
    """
    from backend.config import settings

    if settings.is_production_posture:
        return generic
    return str(exc)[:limit]
