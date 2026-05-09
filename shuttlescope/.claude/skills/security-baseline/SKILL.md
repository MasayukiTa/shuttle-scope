---
name: security-baseline
description: ShuttleScope の汎用セキュリティチェックリスト。新ルータ追加時 / Electron renderer 変更時 / WebSocket 改修時に自動実行する。OWASP / Electron 業界標準の generic patterns のみ。プロジェクト固有の弱点情報は private_docs/skills_internal/ 側に置く。
---

# security-baseline — 公開可能な汎用セキュリティチェック

ShuttleScope の **新規変更が起こるたびに**機械的に走らせる、業界標準のチェックリスト。
新ルータ・新 webview・新 IPC・新 export endpoint を追加したら必ず通すこと。

## 対象範囲

- FastAPI 新ルータ
- Electron `<webview>` / `webPreferences` / IPC
- Frontend (React) — XSS / CSV / PDF export
- WebSocket
- 認証・認可ガード
- 設定ファイル (PM2 / Cloudflared / firewall)

## 自動チェック項目

### A. FastAPI 新ルータ追加時

- [ ] **auth dep**: 各 endpoint に明示的に `_require_admin` / `require_analyst` /
      `_require_auth` 等の Depends を付ける。「middleware 任せ」は禁止
      (round 8 V-1: middleware の loopback 緩和で auth bypass 経験あり)
- [ ] **team scope**: ID 系パス (`/match_id`, `/rally_id` 等) は path に出る場合は
      `_MATCH_ID_PATTERNS` 適用範囲か確認、出ない場合は per-handler で
      `user_can_access_match` / 同等を呼ぶ
- [ ] **team_id=None reject**: coach/analyst で team_id=None なら write を許さない
- [ ] **Pydantic body**: `model_config = {"extra": "forbid"}` を付ける
- [ ] **Soft delete**: DELETE は必ず `obj.deleted_at = utcnow()` を**実際にセット**する
      (round 8 V-3: noop だった事故あり)
- [ ] **Response shape**: 同意書 第5条 sensitive fields (Tier 2/3/4) は role に応じて
      mask する。`_full_dict()` 直接返却禁止
- [ ] **Audit log**: 状態変更系は `log_access(db, "<action>", ...)` を必ず emit

### B. Electron `<webview>` / WebContents

- [ ] `disablewebsecurity`, `allowpopups`, `nodeIntegration`, `enableRemoteModule`
      属性を**書かない**。`will-attach-webview` allowlist で同名 webPreferences も拒否
- [ ] `webContents.setWindowOpenHandler` で全 popup を `shell.openExternal` に逃がす
- [ ] `will-navigate` で `file:` を production 拒否 (`localfile:` は path-jail 経由のみ)
- [ ] `setPermissionRequestHandler` と `setPermissionCheckHandler` の許可リストを揃える
      (round 6 で geolocation 不整合あり)
- [ ] 新 BrowserWindow の `webPreferences` は最低 `nodeIntegration:false`,
      `contextIsolation:true`, `sandbox:true`
- [ ] `webviewTag: true` を有効にした window には mainWindow と同じ
      `will-attach-webview` allowlist を適用 (round 8 R8c F-1)

### C. Electron IPC (`ipcMain.handle/on`)

- [ ] 受け取る引数は型・長さ・文字種を validate (path / URL は jail と scheme allowlist)
- [ ] state 変更系は `senderFrame.parent == null && senderWc.id == mainWindow.webContents.id`
      で trusted frame のみ許可
- [ ] 戻り値に absolute path / 認証 token / DB ID 列挙を**含めない**

### D. CSP / Origin

- [ ] `connect-src` は **wildcard `https:` 禁止**。allowlist に shuttle-scope.com 系 +
      localhost backend のみ
- [ ] WebSocket endpoint は Origin allowlist チェック (`_ws_origin_allowed`)
- [ ] `null` Origin は production で拒否

### E. Frontend XSS / Export

- [ ] `dangerouslySetInnerHTML` の追加は禁止。i18n は `escapeValue: true` を維持
- [ ] CSV export は `_csv_safe()` を**全 cell**に通す。leading-space + `=`/`+`/`-`/`@` も
      検出する版を使う (round 8 P1-3)
- [ ] PDF export は reportlab `Paragraph(...)` に user input を入れる前に
      `xml.sax.saxutils.escape` する (round 8 P1-1)
- [ ] `Content-Disposition` filename は `[A-Za-z0-9_-]` のみ許可。`"`, `;`, CRLF 厳禁
      (round 8 P1-2)

### F. Auth / Token

- [ ] `_require_admin` 後の DB 再 check (role / locked_until / awaiting_admin_approval)
      が走っているか (round 8 F1)
- [ ] `is_loopback_request` / IP 判定は `_normalize_ip()` 経由で IPv4-mapped IPv6 を
      unmap する (round 8 F2)
- [ ] login failure / lockout は SQL atomic UPDATE + `locked_until` 進行ガード
      (round 8 F3)
- [ ] CF-Connecting-IP は loopback 接続 (cloudflared) からのみ信用
      (`backend.utils.client_ip.trusted_client_ip`)
- [ ] Token は `iss=shuttlescope-auth`, `aud=shuttlescope-api`, `token_use=access` を含み、
      verify_token がそれを検証 (round 7)

### G. Middleware path normalization

- [ ] 全 path-prefix 判定は **PathNormalizationMiddleware が先に正規化**した後の
      `request.url.path` を使う (`//+` `/./` `/../` `%2F` `%5C`)
- [ ] OPTIONS preflight は `access-control-request-method` 付きのみ素通し
      (round 8 F4)

### H. Body / Compression

- [ ] `Content-Encoding: gzip|br|deflate` は受け付けない (round 8 F5)
- [ ] `Content-Length` cap: auth path 4KB, 通常 100MB

### I. WebSocket

- [ ] per-session + global connection cap (round 7/8)
- [ ] viewer_id / participant_id 等の dict キーは regex `^[A-Za-z0-9_-]{1,64}$` で validate
- [ ] 切断時に session entry を pop (memory leak 防止)

### J. インフラ設定

- [ ] PM2 ecosystem.config.js の `--host 0.0.0.0` には SS_OPERATOR_TOKEN +
      PUBLIC_MODE/LAN_MODE のガードあり
- [ ] Ray dashboard / firewall は loopback or link-local のみ。`Any` 禁止
- [ ] Cloudflared SSH ingress は `config.ssh.example.yml` から明示的に opt-in
      (Cloudflare Access policy 必須)

## 自動実行スクリプト (推奨 CI integration)

```yaml
# .github/workflows/security-baseline.yml (template)
- name: Electron security
  run: npx @doyensec/electronegativity -i shuttlescope/electron -o electronegativity.json
- name: FastAPI patterns
  run: semgrep --config=p/python --config=p/owasp-top-ten --config=p/fastapi shuttlescope/backend
- name: Python SAST
  run: bandit -r shuttlescope/backend -ll
- name: Dependency CVE
  run: cd shuttlescope/backend && python -m pip_audit
- name: Secret detection
  run: gitleaks detect
```

## チェックリストを skip すべきでない理由

ShuttleScope は実プレーヤーの体組成・健康データ (同意書 第5条 Tier 3/4 PII) を
扱うため、攻撃面の見落としが privacy violation に直結する。
過去 8 ラウンド (R1-R8) で**合計 ~120 件**の P0/P1/P2 issue が見つかっており、
本チェックリストの各項目は実際に踏んだ罠が反映されている。

## 関連ドキュメント

- `private_docs/2026-05-09_security_deep_hole_hunt.md` (gitignored, 内部) — ShuttleScope 固有の弱点ロードマップ
- `private_docs/2026-05-09_codex_findings.md` (gitignored, 内部) — Codex 独立 audit 結果
- `private_docs/skills_internal/` (gitignored, 内部) — プロジェクト固有 audit skill
