# Validation: 途中保存(final=false)の未確定ラリーを確定扱いしない

## 変更日: 2026-11-11

## 対応 PR

- https://github.com/MasayukiTa/shuttle-scope/pull/347
- ブランチ: `fix/in-progress-rally-not-final`
- コミット: `faadb7b5`

## 変更ファイル

- `shuttlescope/backend/routers/strokes.py`
- `shuttlescope/backend/analysis/analysis_population.py`
- `shuttlescope/backend/analysis/router_helpers.py`
- `shuttlescope/backend/tests/test_strokes_batch_in_progress_rally.py` (新規)

---

## 背景 / 不具合

`POST /api/strokes/batch` を `final=false`(途中保存)で送ると、`end_type=in_progress`・`winner=仮(player_a)` の**未確定ラリー**が保存される。この未確定ラリーが確定ラリーと同様に扱われており、次の 2 つの実行時欠陥があった。

1. **誤ブロードキャスト**: 途中保存の時点で共有セッション(観戦/コーチビュー)へブロードキャストされ、仮の勝者・スコアが配信されていた。
2. **集計汚染**: 得点・解析の母集団カウント(`rally_counts_by_match`)に未確定ラリーが数えられ、勝率などの指標が途中値で汚れていた。

---

## 変更内容

### strokes.py

1. `final=true` のときだけ `_broadcast_rally_saved` を呼ぶ。途中保存(`final=false`)ではブロードキャストしない。
2. 既存が `in_progress` のラリーに `final=true` が来たら、`winner` / `end_type` / `score_a_after` / `score_b_after` を確定内容で**必ず上書き**する。打球本数が同じでも上書きする(`_finalize_existing_in_progress_rally` / `_finalize_rally_fields`)。

### analysis_population.py

3. `IN_PROGRESS_END_TYPE` と `active_rally_predicates()` を追加。`rally_counts_by_match` からも `in_progress` を一貫除外する。識別は `end_type` 列のみで判定し、**スキーマ変更なし**。

### router_helpers.py

4. 有効ラリー取得を `active_rally_predicates()` に統一。

---

## テスト

`shuttlescope/backend/tests/test_strokes_batch_in_progress_rally.py` を新規追加。

- `test_in_progress_new_rally_is_not_broadcast` — 途中保存ではブロードキャスト経路に入らない
- `test_in_progress_rally_excluded_from_counts` — `in_progress` は `active_rally_predicates` / `rally_counts_by_match` の双方から除外される
- `test_final_overwrites_winner_end_type_score_same_stroke_count` — 打球本数が同じでも `final=true` で winner/end_type/score が確定値に上書きされ、確定時のみブロードキャスト経路に入る

### 実行結果

```
python -m pytest backend/tests/test_strokes_batch_in_progress_rally.py
3 passed, 116 warnings in 134.20s
```

バックエンド pytest は CI の `python -m pytest`(ci.yml の Backend tests ステップ)で自動収集されるため、テストファイルの追加登録は不要。

---

## 確認事項

- [x] 途中保存(final=false)でブロードキャストされない
- [x] 途中保存ラリーが母集団カウントに含まれない
- [x] 同一打球本数でも final=true で winner/end_type/score が上書きされる
- [x] 確定時のみブロードキャスト経路に入る
- [x] 新規テスト 3 件 PASS

---

## 補足: CI テストマニフェストについて

`shuttlescope/scripts/ci_test_manifest.d/` と `scripts/check_ci_test_manifest.py` は **vitest(フロントエンド)専用**。マニフェストの各エントリは vitest.config.ts の include グロブ `src/**/__tests__/**/*.test.{ts,tsx}` に合致している必要があり、合致しないエントリがあると `check_ci_test_manifest.py` が CI を FAIL させる。

本対応の pytest テストはこのグロブ対象外であり、`ci_test_manifest.d/` には**登録しない**(登録すると include グロブ不一致で CI が壊れる)。バックエンド pytest は ci.yml の `python -m pytest` で自動収集される。
