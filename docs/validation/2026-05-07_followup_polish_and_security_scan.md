# 2026-05-07 アノテーション仕上げ followup + NVML race + GitHub code scanning

このドキュメントは前 PR (`2026-05-07_3rd_review_medium_priority_fixes.md`) の
follow-up として、ユーザ確認の上で進めた以下を記録する。

1. アノテーション関連の 3 follow-up 項目
2. NVML cross-process race (3rd review で TODO 明記だった項目)
3. GitHub code scanning オープン警告のうち重要なものの解消

## 1. アノテーション follow-up

### 1.1 `useCallback` deps audit (handleConfirmRally の stale closure 修正)

`AnnotatorPage.tsx` の `handleConfirmRally` 内で:

- `isBasicMode` が deps に無く、ユーザがアノテーション中に基本/詳細モードを
  切り替えると次の 1 ラリーが切替前の値で保存される (annotation_mode と
  source_method 誤分類)。
- `midGameShown` を直接読んでおり、handleSkipRally と一致しない経路だった。

修正:
- deps に `isBasicMode` と `autoSaveKey` を追加。
- `midGameShown` 直読み → `midGameShownRef.current` 経由 (handleSkipRally の
  既存パターンに揃え、stale 値の問題と無駄な callback 再生成の両方を回避)。

### 1.2 `buildSkippedRallyPayload` 新設 + 3 経路統合

`/strokes/batch` の skipped ラリー保存は 3 箇所でインライン構築されていた:

- `handleSkipRally` (見逃しラリー)
- `handleScoreCorrection` (スコア補正で複数 skipped ラリーを連投)
- `handleForceSetEnd` (セット強制終了)

これらを `src/utils/annotationPayload.ts` の `buildSkippedRallyPayload` に
集約し、`annotation_mode` (basic→`manual_record` / detailed→`assisted_record`) を
**一貫して保存**するよう修正。

### fine-tune データセット作成 / 性能評価への効果
- DB レベルで「アノテートされたラリー」と「補完ラリー」の区別が確実に取れる
- `annotation_mode` が常に入るため、basic / detailed 別の分類精度や
  サンプル質をオフライン評価で計算可能
- 新フィールド追加時は builder 1 箇所更新だけでよい (取りこぼし防止)

deps 配列にも `isBasicMode` を追加 (1.1 と同じ stale closure 防止)。

### 1.3 StrokeHistory override-bridge レンダリングテスト

`hit_zone_source === 'manual'` かつ `hit_zone_cv_original !== hit_zone` の
場合に「手動打点」バッジが履歴行に出ることを契約として固定。

カバー項目:
- CV 一致時はバッジなし
- 値が違う manual ストロークはバッジあり
- source=manual でも値が同じならバッジなし (CV を確認しただけのケース)
- `hit_zone_cv_original` が null/undefined のときバッジなし
- 複数ストロークで override 1 件だけにバッジ
- tooltip に CV 値と選択値が含まれる

副次変更: i18next の interpolation 構文が `{{var}}` (二重波括弧) のため、
新規 i18n キー `annotator.hit_zone_manual_tooltip` を `{{cv}}` / `{{picked}}`
に修正。

## 2. NVML cross-process race fix

3rd review の `pipeline/cluster/gpu` 領域 #8 で TODO 明記済だった項目。

`backend/services/gpu_health.py:probe()` は API process と pipeline worker
process の両方から呼ばれる。NVIDIA driver は同時 nvmlInit/Shutdown を
複数プロセスから受けると undefined behavior を起こす場合があり、
`probe()` が偶発的に `nvmlInit failed: NVML_ERROR_UNINITIALIZED` を返す事象
の素因だった。

### 修正
- 既存の in-process `_NVML_LOCK` に加え、ファイルベースの advisory lock を
  追加 (`_nvml_cross_process_lock` context manager)。
- Windows: `msvcrt.locking(LK_NBLCK)` を 50ms 間隔でリトライ
- POSIX: `fcntl.flock(LOCK_EX | LOCK_NB)` を 50ms 間隔でリトライ
- タイムアウト 5 秒。取得失敗時は best-effort で probe を続行 (ログに warn)
- ロックファイル: `<tempdir>/shuttlescope_nvml.lock`

NVML probe 自体は通常 100ms 未満なので、5 秒タイムアウトで実用上十分。

smoke 検証: pynvml なしの環境でも `_nvml_cross_process_lock` が正しく
acquire/release/re-acquire できることを確認。

## 3. GitHub code scanning 対応

`gh api repos/.../code-scanning/alerts?state=open` で取得した open alerts を
トリアージ。重大なもの (security_severity = high / medium、CVE warning)
を解消。

### 3.1 [HIGH] #1991 `py/clear-text-logging-sensitive-data` (remote_tasks.py:1305)

**実態**: `dispatch_hardware_detect` が SSH 失敗時に `result["error"]` を
warning ログに流していた。`result["error"]` は paramiko 例外メッセージや
"JSON 出力なし: <stdout の末尾 300 char>" を含み得る。直接的な password
漏洩経路は現状ないが、CodeQL の data-flow が `password` 引数を受け取る関数
からの戻り値を保守的に tainted と判定。

**修正**: ログを redact。`err_text.split(":", 1)[0][:64]` で error の prefix
だけ抽出し、`worker_ip` と一緒に出すように変更。詳細メッセージは戻り値から
呼び出し元が必要に応じて取り出せる。

### 3.2 [WARN] CVE-2026-42561 python-multipart 0.0.26 → 0.0.27

`backend/requirements.txt` を `python-multipart==0.0.27` に bump。
multipart header parser DoS の修正版。コメントに CVE 番号を明記。

### 3.3 [WARN] CVE-2026-42338 ip-address (transitive: socks → ip-address@10.1.0)

XSS (Address6.group / link が HTML エスケープしない問題)。
本リポジトリは ip-address を直接使わず、build-time の electron-builder 系
チェーン経由の transitive dep。runtime 影響なし。

`package.json` に `"overrides": { "ip-address": "^10.2.0" }` を追加して
強制 bump。`npm ls ip-address` で `10.2.0` に解決されることを確認。
`npm audit` で 0 vulnerabilities。

### 3.4 [WARN] #1892 SQL injection in `rotate_field_key.py:115`

**False positive**:
- table/column は `TARGETS` (line 35-) のハードコード allow-list 由来で、
  ユーザ入力は流入しない
- 値はバインドパラメータ `{"v": new_ct, "id": rid}` 経由
- 既に `# nosec B608` annotation 済み

コード変更なし。

### 3.5 上記以外の note 級

`Do not leave debug code in production` (DS162092) や `Suspicious comment`
(DS176209)、`Review setTimeout for untrusted data` (DS172411)、
`Hard-coded SSL/TLS Protocol` (test_tls_headers.py 内、テスト目的) などは
note レベルで実害無し。本 PR では対応しない (個別棚卸しで dismiss 予定)。

## 検証

### Frontend
- `npx vitest run`: 13 ファイル / **129 / 129 PASS**
  - 新規: StrokeHistory override-badge 6 ケース、buildSkippedRallyPayload 4 ケース
  - 既存 buildBatchPayload 11 ケースは仕様変更なし (skipped variant は別 describe)
- `npm run build`: ✅ (`NODE_OPTIONS=--max-old-space-size=16384`)
- `npm install`: 0 vulnerabilities (ip-address override 適用後)

### Backend
- `gpu_health._nvml_cross_process_lock` smoke: acquire / release / re-acquire OK
- pytest 全体起動は config Settings の env validation エラーで起動できない
  (PROD_ENV_SPEC.md にある通り、本環境は `extra="ignore"` 未同期。私の変更と無関係)
- 個別実行で前 PR の registry / camera owner テストは PASS 済み

### 本番影響
- DB schema 変更ゼロ
- 本番への SSH / DB 操作ゼロ
- python-multipart の bump は本番反映時に `pip install -r requirements.txt`
  で適用 (互換性破壊なし、minor patch)
- ip-address override は build-time のみ影響、runtime 影響なし

## 残タスク (out of scope)

- Mobile UI 設計 (`private_docs` 内の implementation plan)
- iOS フォント縮小時のタイル崩れ (CLAUDE.md の `font-size: 16px !important` 規約と関連)
- 上記 note 級コード scanning 警告の棚卸し / dismiss
- analysis_registry `check_or_raise` の各 router への wiring (前 PR で計画済)
