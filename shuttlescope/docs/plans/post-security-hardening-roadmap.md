# Post-Security-Hardening Roadmap (2026-04-23〜)

セキュリティ triage 完了後の品質・機能タスクを段階実行するための計画書。
本番環境が手元に無いため、ローカル検証のみで閉じられる単位に分割する。

## 前提
- `npm run build`（`NODE_OPTIONS=--max-old-space-size=16384` 必須）と `python -m pytest backend/tests` がローカル検証の基本
- UI 変更は build + 目視可能範囲のみ確認、挙動検証はプロダクション pull 後に別途
- 1 バッチ = 1 commit、検証付きで push。大規模一括は行わない

---

## タスク1: TSX ハードコード日本語の i18n 化

### 現状
- JSX テキスト内の日本語リテラル: **508 件 / 85 ファイル**（2026-04-23 計測）
- `src/i18n/ja.json` に集約する CLAUDE.md ルールに違反
- コメント内の日本語は許容（CLAUDE.md ルール準拠）

### 段階計画
| バッチ | ファイル | 件数 | 目安 |
|-------|----------|------|------|
| B1 | `AnnotatorPage.tsx` | 57 | 大 |
| B2 | `SettingsPage.tsx` | 52 | 大 |
| B3 | `MatchListPage.tsx` | 30 | 中 |
| B4 | `UserManagementPage.tsx` + `DashboardOverviewPage.tsx` | 39 | 中 |
| B5 | `DoublesAnalysis.tsx` + `CourtHeatModal.tsx` + その他 analysis 系 TOP10 | ~80 | 中 |
| B6 | annotation components TOP10 | ~60 | 中 |
| B7 | 残りの 45+ ファイル（1-10 件ずつ） | ~190 | 低 |

### 進行方針
- 各バッチで key 命名は既存 `ja.json` 階層を踏襲（`page.annotator.xxx`, `component.settings.xxx` 等）
- 変更後 `npm run build` が通ることのみ確認（UI 目視は不可）
- 1 バッチ完了毎に `docs/validation/i18n-migration-<batch>.md` に一覧記録

### リスク
- i18n key の階層不整合
- 既存 `ja.json` 内の key と衝突

---

## タスク2: バックエンドテスト coverage 底上げ

### 現状
- `pytest-cov` を `backend/.venv` に install 済み
- coverage baseline 未取得

### 段階計画
| バッチ | 作業 |
|-------|------|
| C1 | `pytest --cov=backend --cov-report=term-missing --cov-report=html` で baseline 取得 / TOP 未カバー router を特定 |
| C2 | 最下位 router#1 にユニットテスト追加（happy path + error path + auth 拒否） |
| C3 | 最下位 router#2 にユニットテスト追加 |
| C4 | 最下位 router#3 にユニットテスト追加 |
| C5 | `backend/utils/` / `backend/analysis/` の未カバー関数に unit test |
| C6 | baseline → 結果比較レポートを validation MD に記録 |

### 目標
- 全体 coverage を現状 + 10pt
- 各 router のテストに少なくとも auth 拒否ケースを 1 本含める

### リスク
- DB フィクスチャ / SQLAlchemy session のモック整備コスト
- analysis 系は ML モデル依存でテスト困難 → skip マーク容認

---

## タスク3: Phase B 認証拡張

### 現状 (Phase A 実装済み、`useAuth.ts` / `routers/auth.py`)
- JWT 発行、role / playerId / teamName / displayName / pageAccess を sessionStorage 保持
- TOTP (RFC 6238 SHA1) 対応済み
- login / logout / session 状態復元まで

### Phase B スコープ候補（優先順）
| ID | 機能 | 理由 |
|----|------|------|
| B-1 | Refresh token | JWT 短命化 + 自動再取得でセキュリティ/UX 改善 |
| B-2 | Session timeout（idle detection） | 放置端末のセッション失効 |
| B-3 | Password reset flow | ユーザ運用で必要 |
| B-4 | Failed login rate limit | ブルートフォース対策 |
| B-5 | Audit log | 誰がいつ login/logout/role 変更したか |

### 段階計画
| バッチ | 作業 |
|-------|------|
| A1 | **B-1 設計**: token 有効期限 / refresh endpoint / frontend 自動再取得フロー図を docs/plans に記録 |
| A2 | **B-1 backend**: `POST /api/auth/refresh`、`access_token` TTL 15min、`refresh_token` TTL 7day、DB に refresh token ハッシュ保存 |
| A3 | **B-1 frontend**: `api/client.ts` に 401 時 refresh 自動試行、`useAuth` に refresh 関数追加 |
| A4 | **B-2**: 30min idle で自動 logout、ユーザ操作で reset |
| A5 | **B-4**: IP 単位 5min 5回失敗で 15min ブロック |
| A6 | **B-3**: email が無い POC なので reset 質問 or admin 手動 reset で代替検討 |
| A7 | **B-5**: audit table + 記録関数 + admin ページで閲覧 |

### リスク
- refresh token の漏洩対策（HttpOnly cookie 化は Electron 前提の現行 HTTP API と相性調整必要）
- 本番検証不能なので migration スクリプト / 後方互換は慎重に

---

## 実行順序

1. タスク1 B1（AnnotatorPage）
2. タスク2 C1（coverage baseline）
3. タスク3 A1（B-1 設計 MD）
4. タスク1 B2（SettingsPage）
5. タスク2 C2（router#1 テスト）
6. タスク3 A2（B-1 backend）
7. …以下交互に

各ステップ完了時に commit/push + validation MD 更新。
