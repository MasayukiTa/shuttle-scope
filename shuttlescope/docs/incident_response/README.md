# Incident Response Runbook (Phase C1)

ShuttleScope のインシデント発生時の初動・封じ込め・復旧手順をまとめる。

## 想定シナリオと runbook

| シナリオ | runbook | 想定対応時間 |
|---------|---------|------------|
| SECRET_KEY / 暗号化鍵漏洩 | [`credential_compromise.md`](credential_compromise.md) | 10 分以内に封じ込め |
| DB ファイル / バックアップ ZIP 漏洩 | [`data_breach.md`](data_breach.md) | 1 時間以内に影響範囲特定 |
| admin パスワード喪失 | [`break_glass.md`](break_glass.md) | 30 分以内に復旧 |
| video_token 大量漏洩 | [`video_token_leak.md`](video_token_leak.md) | 5 分以内に一斉再発行 |

## 共通の初動 3 ステップ

1. **検知**: backend ログ (`pushBackendLog`)、`access_log` テーブル、Cloudflare ダッシュボードを確認
2. **封じ込め**: 該当 runbook の「即時アクション」セクションを実行
3. **記録**: `docs/incident_response/incidents/YYYY-MM-DD_<short_name>.md` に時系列記録

## エスカレーション連絡先

- 第一連絡: 主任分析担当 (admin ロール保有者)
- 第二連絡: クラスタ運用責任者
- 第三連絡: 法務 (個人情報漏洩時)

## 演習計画

- 月次 Game Day 演習: `shuttlescope/scripts/game_day/` の各シナリオを月初に実行
- 結果記録: `docs/incident_response/drills/YYYY-MM_<scenario>.md`
