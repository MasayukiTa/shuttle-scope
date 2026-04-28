# Game Day 演習スクリプト (Phase C3)

毎月実施する障害注入・復旧演習のスクリプト集。
実環境でいきなり試さず、検証用 DB / 検証用環境変数で先に試すこと。

## シナリオ一覧

| ID | シナリオ | スクリプト | 想定所要時間 |
|----|---------|----------|------------|
| G-1 | DB ファイル損失 → バックアップ復元 | `simulate_db_loss.ps1` | 15 分 |
| G-2 | 全 JWT 失効 → 再ログイン | `simulate_token_compromise.py` | 10 分 |
| G-3 | Export 鍵ローテ → 旧 export 即無効化 | `simulate_export_key_rotation.py` | 10 分 |
| G-4 | video_token 一斉再発行 → 全 UI 再描画 | `simulate_video_token_mass_reissue.py` | 5 分 |

## 実施記録

各演習結果は `docs/incident_response/drills/YYYY-MM_<scenario>.md` に記録する。
記録項目:
- 開始/終了時刻
- 想定 vs 実測 時間差
- 問題が見つかった点
- 改善アクション
