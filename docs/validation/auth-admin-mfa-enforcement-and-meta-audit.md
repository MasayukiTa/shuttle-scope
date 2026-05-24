# auth: admin MFA enforcement + meta-audit on sensitive endpoints

- 検出: 2026-05-24 R281 / R280 で admin token 漏洩時の blast radius を観測。
  admin の単一 access_token 取得で `/api/auth/users` + `/api/auth/audit-logs`
  経由で全 user の username + ip_addr が 1 リクエストで dump できる構造。
- 修正対象: `backend/config.py`, `backend/utils/auth.py`,
  `backend/routers/auth.py`

## 問題

admin role の defense-in-depth が password 1 段のみ:

- access_token の有効期間 15 分 (`ADMIN_TOKEN_EXPIRE_MINUTES=15`) は短いが、
  password 漏洩 = admin 操作完全奪取
- refresh_token (7 日) も保存場所が共通 → 同経路で漏洩
- 漏洩 token を持つ attacker が:
  - `/api/auth/users` → 全 user の username + role + team + display_name
  - `/api/auth/audit-logs` → 全 access event (login IP, action, details)
  を 2 リクエストで dump できる
- 「自分は audit を見ていない」と本人が気づく手がかりが audit log 上に残らない
  (admin 操作 = expected pattern として埋もれる)

## 修正内容

### 1. admin MFA enforcement (`utils/auth.py` `routers/auth.py`)

- `config.py`: `ss_require_admin_mfa: bool = True` を追加。緊急時 env で
  `SS_REQUIRE_ADMIN_MFA=0` 可能。
- `utils/auth.py:require_admin()`: 既存の role check に追加で
  `db.get(User, ctx.user_id).totp_enabled` 検証。false なら 403 +
  `"admin role には MFA enrollment が必須です。/api/auth/mfa/setup → /api/auth/mfa/confirm で設定してください。"`
- `routers/auth.py:_require_admin()`: ローカル変種にも同等の totp_enabled
  検証を追加 (DB 二重検証パスの一貫性確保)。
- `/api/auth/mfa/setup` `/api/auth/mfa/confirm` は `get_auth` のみで gate
  しており require_admin を呼ばないため、未 enroll admin の setup 経路は
  維持される。

attacker が admin password を盗んだだけでは admin endpoint を叩けない
(TOTP device 必須)。漏洩 + TOTP device 物理アクセス両方が必要。

### 2. meta-audit on sensitive admin endpoints (`routers/auth.py`)

- `GET /api/auth/audit-logs` 入口で `log_access(db, "admin_audit_logs_viewed",
  user_id=ctx.user_id, ip_addr=ip, details={"filter_action", "filter_user_id",
  "filter_ip", "filter_since", "limit_requested"})` を追加。
- `GET /api/auth/users` (admin 分岐) 入口で `log_access(db,
  "admin_users_listed", user_id=ctx.user_id, ip_addr=ip)` を追加。
- 失敗しても本処理を止めない (try/except で囲う)。

admin token 漏洩で attacker が一括 dump を実行した場合、本人が後で audit
を見れば「自分が見ていない時刻 / IP からの dump record」を発見可能。

## frontend 影響

- `LoginPage.tsx` は既に `mfa_required: true` を処理する 6 桁入力画面を
  実装済 (commit `eabb9a3` + `cb34a0d`)。
- 未 enroll admin が admin endpoint を叩いた場合の 403 message は frontend
  でそのまま表示される (生 detail string)。専用 UI は今後の課題。

## verify 手順

1. `mfa.py status` で adminTakeuchi_=t, satomin3103n=f を確認
2. deploy 後:
   - `adminTakeuchi_` で login (frontend MFA flow 経由) → access_token 取得 →
     `GET /api/auth/audit-logs` → 200 ✅
   - access_log テーブルに `admin_audit_logs_viewed` event が記録される
3. `satomin3103n` で password login (totp_enabled=f なので即 access_token) →
   `GET /api/auth/audit-logs` → **403 + "MFA enrollment が必須" message**
4. `mfa.py setup satomin3103n` (再生成不要、既に secret あり) → satomin が
   iOS Passwords に登録 → `mfa.py enable satomin3103n` で `totp_enabled=true`
   → 以降は MFA flow を通過すれば admin endpoint 利用可能

## 緊急 disable 手順

- env `SS_REQUIRE_ADMIN_MFA=0` を set → backend restart → MFA enforcement off
- もしくは `mfa.py clear adminTakeuchi_` で totp_enabled=false + secret=NULL
  → このユーザに対してだけ enforcement bypass される
  (※他 admin の totp_enabled が true ならそちらは引き続き MFA 要求される)

## 副作用検討

- 既存 admin (Takeuchi さん, satomin さん) は事前 setup 必要
- audit 容量: meta-audit event は admin 操作頻度に比例 (低頻度想定)
- 既存テストへの影響: `require_admin` シグネチャに `db: Session =
  Depends(get_db)` 追加。FastAPI は nested deps 解決するので呼出側は変更不要
