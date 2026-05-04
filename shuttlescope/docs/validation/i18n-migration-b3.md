# i18n Migration B3: MatchListPage

Date: 2026-04-23

## 目的
`src/pages/MatchListPage.tsx` に残っていたハードコード日本語を `ja.json` の `match.list.*` キーに移行。

## 変更

### src/i18n/ja.json
- `match.list.*` キー群を追加:
  - level_all, only_unfinished
  - quality / quality_720 / quality_best / cookie_none
  - col_level / col_format / col_opponent / col_actions
  - format_singles / format_mens_doubles / format_womens_doubles / format_mixed_doubles
  - result_win / result_loss / result_walkover / result_unfinished
  - video_optional / first_serve / analyst_view
  - tentative / registered / duplicate_hint / existing_team_hint

### src/pages/MatchListPage.tsx
- ~22 件の JSX 内ハードコード日本語を `{t('match.list.*')}` に置換
  - 「全大会レベル」 (×2), 「未完了のみ」 (×2)
  - 画質ラベル・選択肢・Cookie 未設定
  - テーブルヘッダー (レベル / 形式 / 対戦相手 / 操作)
  - 形式オプション (シングルス等)・試合結果オプション (勝ち / 負け / 不戦勝 / 未完了)
  - 動画 URL ラベル・ファーストサーブラベル・アナリスト専用ラベル
  - 「暫定」バッジ (×2)

## 検証
- `NODE_OPTIONS=--max-old-space-size=16384 npm run build` 成功 (11.85s)
- 既存テスト影響なし (UI テキストキーのみ)

## 既知の制約
- 補間文字列 (例: `${count}件` 等) や動的文字列は今回対象外。残りは後続バッチ B4 以降で対応。
- 手動 UI スモークは未実施。ビルド成功のみで判定。

## 今後
- B4: UserManagementPage + DashboardOverviewPage
- B5: DoublesAnalysis + CourtHeatModal + analysis 上位 10
- B6: annotation 関連コンポーネント 上位 10
- B7: 残り 45+ ファイル
