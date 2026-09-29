# Security CI Attack Suite

`shuttlescopeattacktest/round110〜155` で見つけた脆弱性を CI で再発防止するための **無認証**攻撃テスト集。

## 設計方針
- **admin / analyst / coach 等の本番アカウント情報は一切使わない**。
- 攻撃対象は `SS_ATTACK_HOST` / `SS_ATTACK_PORT` 環境変数で切替。
- 1 つでも `CRITICAL` を見つけたら exit 1。
- HIGH / WARN は出力するが exit 0 (最低限 CI を止めない)。

## 含まれる攻撃

| Suite | 元 round | 内容 |
|---|---|---|
| `test_no_auth_endpoints.py` | round128 | 認証必須 endpoint × 50+ を no-auth で叩いて 200 が出ないか |
| `test_jwt_forgery.py` | round122 + 133 | 偽 JWT 11 種 × 19 endpoint = 209 プローブ + Auth header spoof |
| `test_tls_headers.py` | round145 + 150 + 154 | TLS 1.0/1.1 reject / 弱い cipher / HSTS / X-Frame / CORS / dump path |
| `test_smuggling_methods.py` | round119 + 134 | XXE / TE / method override / TRACE/PURGE/CONNECT / CRLF / Host poison |
| `test_public_endpoints.py` | round137 | contact / register / verify / reset の入力検証 + OAuth probe |

## 認証境界の strict probe

`test_no_auth_endpoints.py` は 2 層で検査する。

1. broad sweep: 列挙・dump・near-miss を広く GET し、公開/認証境界の異常を探す。
2. `STRICT_AUTH_PROBES`: 高リスク route を **実際の HTTP method** で呼び、401/403 だけを合格とする。

strict probe では 404 / 405 / 422 を合格にしない。route 名や method が変わって probe が
空振りしても「認証されている」と誤認しないためである。通常 pytest の
`backend/tests/test_route_inventory.py` が strict probe と実 FastAPI route/method を
突き合わせるので、route 変更時は CI で drift を検出する。

保護対象 endpoint の 200 は、レスポンスが空でも auth bypass として失敗する。
例外は明示 public endpoint と、本文の固有マーカーまで一致した intentional decoy
(`/graphql`, `/dump.sql`) だけ。decoy path が将来本物の漏洩へ変わっても、
単なる path allowlist では通らない。

## 使い方

### 本番 (default)
```bash
python run_all.py
```

### ローカル backend (CI 内で起動した backend を攻撃)
```bash
SS_ATTACK_HOST=localhost SS_ATTACK_PORT=8765 SS_ATTACK_INSECURE=1 \
  python run_all.py
```

### 個別 suite
```bash
python test_jwt_forgery.py
```

## CI 統合
`.github/workflows/security-attacks.yml` 参照。

## 含まれない攻撃 (理由: admin 認証必須)
round70/110-117/120-131/135-144/147-153/155 の大半。これらは PR 毎に走らせるなら
**ローカル backend + テスト用 admin** を CI 内で起動する 2 段階構成が必要。

## 拡張するには
1. 既存の `shuttlescopeattacktest/roundNN.py` から **無認証で動く部分** を抽出
2. `_common.py` の `Findings` API でレポート
3. `run_all.py` の `SUITES` に追加

各 suite は独立で動き、`SS_ATTACK_HOST` を読むだけで OK。
