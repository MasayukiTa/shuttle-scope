"""データ変更監査(audit_events)の対象判定と、変更内容の非可逆要約。

ここは middleware と テストの両方が import する「対象の単一定義」。
対象エンティティ(試合・セット・ラリー・ストローク・選手・ユーザー・設定)の
作成/更新/削除だけを監査する。値そのものは保存せず、
  - changed_fields: 変更 body に現れたトップレベルのキー名(=列名候補)のみ
  - field_count:    その件数
  - body_hash:      正規化した body の SHA-256(照合用の指紋)
に要約する。

パス設計の前提(backend/main.py の include_router で確認):
  matches/sets/rallies/strokes/players は prefix 無しで main 側が
  "/api" を付けてマウントする。auth は router 側 prefix "/auth"。
  したがってここでは "/api" と素の両方を許容する正規表現で判定する。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

# (正規表現, entity_type)。先頭から順に最初にマッチしたものを採用。
# {id} 部分は entity_id として取り出す。末尾にサブアクション(例 /end, /batch,
# /download)が付くものも、親 entity にひも付けて監査する。
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^/(?:api/)?matches/(?P<id>[^/]+)(?:/.*)?$"), "match"),
    (re.compile(r"^/(?:api/)?matches/?$"), "match"),
    (re.compile(r"^/(?:api/)?sets/(?P<id>[^/]+)(?:/.*)?$"), "set"),
    (re.compile(r"^/(?:api/)?sets/?$"), "set"),
    (re.compile(r"^/(?:api/)?rallies/(?P<id>[^/]+)(?:/.*)?$"), "rally"),
    (re.compile(r"^/(?:api/)?rallies/?$"), "rally"),
    (re.compile(r"^/(?:api/)?annotation/(?P<id>[^/]+)/undo/?$"), "rally"),
    (re.compile(r"^/(?:api/)?strokes/batch/?$"), "stroke"),
    (re.compile(r"^/(?:api/)?strokes/(?P<id>[^/]+)(?:/.*)?$"), "stroke"),
    (re.compile(r"^/(?:api/)?strokes/?$"), "stroke"),
    (re.compile(r"^/(?:api/)?players/(?P<id>[^/]+)(?:/.*)?$"), "player"),
    (re.compile(r"^/(?:api/)?players/?$"), "player"),
    # コンディションタグ(condition_tags)は conditions より先に判定する
    # (接頭辞が被るため)。語境界を固定して conditions 側が食わないようにする。
    (re.compile(r"^/(?:api/)?condition_tags/(?P<id>[^/]+)(?:/.*)?$"), "condition_tag"),
    (re.compile(r"^/(?:api/)?condition_tags/?$"), "condition_tag"),
    # 選手コンディション測定(conditions)。/questionnaire 等のサブパスも親に紐付け。
    (re.compile(r"^/(?:api/)?conditions/(?P<id>[^/]+)(?:/.*)?$"), "condition"),
    (re.compile(r"^/(?:api/)?conditions/?$"), "condition"),
    (re.compile(r"^/(?:api/)?settings/?$"), "settings"),
    # ユーザー: auth router(prefix /auth)。users を user エンティティとする。
    (re.compile(r"^/(?:api/)?auth/users/(?P<id>[^/]+)(?:/.*)?$"), "user"),
    (re.compile(r"^/(?:api/)?auth/users/?$"), "user"),
    # チーム管理(auth router /teams CRUD)。team エンティティとして監査する。
    (re.compile(r"^/(?:api/)?auth/teams/(?P<id>[^/]+)(?:/.*)?$"), "team"),
    (re.compile(r"^/(?:api/)?auth/teams/?$"), "team"),
]

_METHOD_ACTION = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}

# 監査する HTTP メソッド
AUDITED_METHODS = frozenset(_METHOD_ACTION.keys())


def classify_path(path: str) -> Optional[tuple[str, Optional[str]]]:
    """path を (entity_type, entity_id) に分類。対象外なら None。

    entity_id は path に id があれば文字列で返す(無ければ None=コレクション作成)。
    """
    if not path:
        return None
    # クエリを除去
    path = path.split("?", 1)[0]
    for pat, etype in _PATTERNS:
        m = pat.match(path)
        if m:
            gid = m.groupdict().get("id") if m.groupdict() else None
            return etype, gid
    return None


def action_for_method(method: str) -> Optional[str]:
    return _METHOD_ACTION.get((method or "").upper())


def should_audit(method: str, path: str, status: int) -> bool:
    """監査対象か。成功(2xx)の変更系のみ。"""
    if (method or "").upper() not in AUDITED_METHODS:
        return False
    if not (200 <= int(status) < 300):
        return False
    return classify_path(path) is not None


def _collect_field_names(obj: Any, out: set[str], depth: int = 0) -> None:
    """dict のキー名(=列名候補)だけを集める。値は一切見ない。
    list[dict] (strokes batch 等)にも対応。深さは 3 まで。"""
    if depth > 3:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            if isinstance(v, (dict, list)):
                _collect_field_names(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _collect_field_names(item, out, depth + 1)


def summarize_body(raw: Optional[bytes]) -> tuple[Optional[list[str]], Optional[int], Optional[str]]:
    """リクエスト body(bytes)を (changed_fields, field_count, body_hash) に要約。

    - changed_fields: JSON body のキー名の一覧(値は含めない)。JSON でない/空なら None。
    - field_count:    changed_fields の件数(JSON でなくても body があれば 0 ではなく
                      None を返し、ハッシュだけ残す)。
    - body_hash:      body 全体の SHA-256(hex)。値は復元できないが照合に使える。
    """
    if not raw:
        return None, None, None
    body_hash = hashlib.sha256(raw).hexdigest()
    fields: Optional[list[str]] = None
    count: Optional[int] = None
    try:
        parsed = json.loads(raw.decode("utf-8"))
        names: set[str] = set()
        _collect_field_names(parsed, names)
        if names:
            fields = sorted(names)
            count = len(fields)
    except Exception:
        # JSON でない(multipart の動画アップロード等)。ハッシュのみ残す。
        pass
    return fields, count, body_hash
