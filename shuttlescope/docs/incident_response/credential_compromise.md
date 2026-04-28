# Credential Compromise Runbook

漏洩した可能性のある秘密鍵・トークン:

- `SECRET_KEY` (JWT 署名鍵)
- `SS_FIELD_ENCRYPTION_KEY` (Fernet)
- `SS_BACKUP_PASSPHRASE` (ZIP)
- `SS_EXPORT_SIGNING_KEY` (HMAC)
- `SS_OPERATOR_TOKEN` (Electron→backend)
- 個別ユーザの JWT / refresh token
- 個別 video_token

## 即時アクション (10 分以内)

### A. SECRET_KEY 漏洩

**影響**: 全 JWT が偽造可能 → 全アカウント乗っ取りリスク

```powershell
# 1. 新 SECRET_KEY 生成
python -c "import secrets; print(secrets.token_hex(32))"

# 2. .env.development の SECRET_KEY を置換

# 3. backend 再起動
.\start.bat

# 4. 全 JWT 失効 (再起動で全トークンが署名検証失敗 = 自動失効)
#    → 全ユーザーが再ログイン要

# 5. access_log 確認: 直近 24h の login イベント全件レビュー
```

### B. SS_FIELD_ENCRYPTION_KEY 漏洩

**影響**: DB ファイルを取得していた攻撃者が暗号化フィールドを復号可能

```powershell
# 鍵ローテ手順
# 1. 旧鍵を保持しつつ新鍵を生成
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. 全暗号化レコードを「旧鍵で復号 → 新鍵で再暗号化」
#    → backend/scripts/rotate_field_key.py (要作成、Phase C 後半)

# 3. .env.development の SS_FIELD_ENCRYPTION_KEY を新鍵に
# 4. backend 再起動
# 5. 復号確認: 任意の condition レコードを GET して読めるか
```

### C. SS_BACKUP_PASSPHRASE 漏洩

**影響**: 過去のバックアップ ZIP を全て復号可能

```powershell
# 1. 既存バックアップを別パスフレーズで再暗号化 (要スクリプト)
# 2. 新パスフレーズ生成
python -c "import secrets; print(secrets.token_hex(32))"

# 3. .env.development を更新
# 4. 旧パスフレーズで作成された ZIP を物理破棄するか再暗号化
```

### D. SS_EXPORT_SIGNING_KEY 漏洩

**影響**: 過去発行の export パッケージが偽造可能、有効期限内のものは import される

```powershell
# 1. 新鍵生成
python -c "import secrets; print(secrets.token_hex(32))"

# 2. .env.development を更新 → backend 再起動
# 3. 全既存 export パッケージは即座に無効化される (verify 失敗)
# 4. 顧客に「過去発行の export は無効」を通知
```

### E. video_token 大量漏洩

→ [`video_token_leak.md`](video_token_leak.md) 参照

## 事後対応 (24 時間以内)

1. `access_log` で漏洩鍵を使った操作の有無を全件監査
2. 影響を受けたユーザに通知 (要配慮個人情報含む場合は法令遵守)
3. ポストモーテム: `docs/incident_response/incidents/` に記録
4. 再発防止策の実装 (例: 鍵を環境変数ではなく外部 KMS に移行検討)

## 緊急失効 API (Phase C2 で実装)

```bash
# 全ユーザーの JWT を強制失効
curl -X POST -H "Authorization: Bearer <admin_token>" \
  https://app.shuttle-scope.com/api/admin/security/revoke_all_tokens

# 全 Match の video_token を一斉再発行
curl -X POST -H "Authorization: Bearer <admin_token>" \
  https://app.shuttle-scope.com/api/admin/security/reissue_all_video_tokens
```
