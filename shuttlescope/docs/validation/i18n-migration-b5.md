# i18n Migration B5: CourtHeatModal + DoublesAnalysis

Date: 2026-04-23

## 目的
分析系の主要 2 コンポーネントのハードコード日本語を i18n キーに移行。

## 変更

### src/i18n/ja.json
- `court_heat_modal.*` 約 30 キー (ヘッダー / タブ / フィルター / 凡例 / ゾーン詳細パネル / zones サブツリー)
- `doubles_analysis.*` 約 30 キー (セクション名 / パートナー / サーブレシーブ / バランス / レーダー)

### src/components/analysis/CourtHeatModal.tsx
- `ZONE_LABELS` 定数を `ZONE_KEYS` 配列 (ガード用) に変更し `t(\`court_heat_modal.zones.\${zone}\`)` で解決
- モーダルヘッダー・タブラベル・合成モード注意書き・期間プリセット・試合選択・凡例・詳細パネル見出しを全て `{t(...)}` に置換
- 補間対応: `period_last_n`, `stroke_count`, `click_zone_detail` (改行は `whitespace-pre-line` + `\n` で表現)

### src/components/analysis/DoublesAnalysis.tsx
- `useTranslation` を 5 箇所 (PartnerComparison / ServeReceiveStats / StrokeSharing / CourtCoverage / DoublesAnalysis) で呼び出し
- 勝率 / 相乗効果 / 平均打数 / サーブ種別 / レシーブゾーン勝率 / バランススコア / レーダーのエリア名を翻訳
- NoDataMessage の unit prop も `t('doubles_analysis.unit_doubles_match')` に切替
- 試合選択の suffix (勝/敗) / emptyLabel / placeholder も翻訳

## 検証
- `NODE_OPTIONS=--max-old-space-size=16384 npm run build` 成功 (9.65s)
- 既存テストは UI テキスト変更のみで影響なし

## 既知の制約
- Recharts の Tooltip formatter は関数内で `t` を呼ぶため、チャート描画時にロケール切替で即時反映されない可能性あり。POC のため許容。
- 手動 UI スモークは未実施。

## 今後
- B6: annotation 関連コンポーネント 上位 10
- B7: 残り 45+ ファイル
