# cluster / benchmark / network_diag / db_maintenance / archive_ops を常時 mount 化

実施日: 2026-05-08

## 背景

`backend/main.py:1582-1593` の旧 SEC-001 ガード:

```python
if not app_settings.is_production_posture:
    app.include_router(cv_benchmark.router, prefix="/api")
    app.include_router(network_diag.router, prefix="/api")
    app.include_router(db_maintenance_router.router, prefix="/api")
    app.include_router(archive_ops_router.router, prefix="/api")
    app.include_router(cluster_router.router, prefix="/api")
```

production posture (PUBLIC_MODE) では危険ルーター群を mount から除外する設計だった。

## 問題

外部 (Cloudflare tunnel) 経由で admin が cluster 設定 UI を開くと、`/api/cluster/config` が 404 を返し `cfg.network.primary_ip` が空のまま。frontend は「primary_ip が未設定です」と出して Ray ヘッドが起動できない。同じ理由で `/api/cv/benchmark` も外部からは叩けない。

admin operator がリモートからクラスタ起動・ベンチマーク・DB メンテを実施できないと、運用ブロッカーになる。

## 認可整合性確認

各 router は endpoint レベルで role gate を持つため、production で mount 解除しても anonymous からは触れない:

| router | gate |
|---|---|
| `cluster.py` | router-level `dependencies=[Depends(_require_admin_dep)]` + 各 endpoint `require_local_operator_or_admin` |
| `db_maintenance.py` | 各 endpoint `require_admin(request)` |
| `archive_ops.py` | 各 endpoint `require_admin(request)` |
| `network_diag.py` | `require_admin_or_analyst(request)` |
| `cv_benchmark.py` | **gate 無し → 本対応で `require_analyst` 追加** |

加えて `main.py:1139` の `_GLOBAL_AUTH_EXEMPT` regex には該当 path が含まれていないため、middleware で anonymous は先に 401。

## 修正

1. `backend/main.py:1582-1593` の `if not is_production_posture:` ガードを削除し、5 router を常時 mount。
2. `backend/routers/cv_benchmark.py` の `/cv/benchmark` に `require_analyst` を追加 (重い GPU/CPU 処理なので analyst 以上に制限、defense-in-depth)。

## 検証

deploy 後:
- anonymous で `/api/cluster/config` → 401 (期待: 認証必要)
- admin で `/api/cluster/config` → 200 (期待: yaml 内容)
- non-admin (player) で `/api/cluster/config` → 403 (期待: admin gate)
- anonymous で `/api/cv/benchmark` → 401
- player で `/api/cv/benchmark` → 403

## 攻撃面への影響

production で mount 解除前は path 自体が存在せず "404 Not Found"。今回の変更で path は存在し、auth/role gate で守る形になる。**外部攻撃面そのものは増えない** (anonymous は middleware で先に弾かれる、role gate で正規認証ユーザでも非 admin は 403)。

ただし将来的に cluster.py 等に新しい endpoint を追加する際は、router-level dep + endpoint-level gate の二段防御が効いていることを必ず確認すること。
