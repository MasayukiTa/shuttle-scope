# ShuttleScope B〜J 実装バリデーションレポート

実施日: 2026-04-06

## 1. 新規バックエンドエンドポイント一覧

### Phase 1: 解析エンドポイント（`backend/routers/analysis.py`）

| ID | エンドポイント | 説明 |
|----|--------------|------|
| B-001 | `GET /analysis/score_progression?match_id=N` | ラリーごとのスコア推移（ラインチャート用） |
| B-004 | `GET /analysis/win_loss_comparison?player_id=N` | 勝ち試合 vs 課題のある試合の主要統計比較 |
| B-006 | `GET /analysis/tournament_level_comparison?player_id=N` | 大会レベル別（IC/SJL/国内等）の勝率比較 |
| C-002 | `GET /analysis/pre_loss_patterns?player_id=N` | 失点前1/2/3球のショットパターン集計 |
| C-003 | `GET /analysis/first_return_analysis?player_id=N` | ファーストリターン（stroke_num=2）のゾーン別勝率 |
| C-004 | `GET /analysis/zone_detail?player_id=N&zone=X&type=hit` | 指定ゾーンのショット内訳と勝率 |
| D-002 | `GET /analysis/temporal_performance?player_id=N` | 序盤(0-7点)/中盤(8-14点)/終盤(15点以降)の勝率 |
| D-003 | `GET /analysis/post_long_rally_stats?player_id=N&threshold=10` | 長ラリー後の次ラリー勝率（通常時との比較） |
| E-001 | `GET /analysis/opponent_stats?player_id=N` | 対戦相手ごとの勝率・ラリー長集計 |
| E-002 | `GET /analysis/opponent_vulnerability?opponent_id=N` | 相手選手の失点ゾーン分析 |
| E-003 | `GET /analysis/opponent_card?opponent_id=N` | 相手選手カード（主要ショット・サーブスタイル） |
| F-001 | `GET /analysis/court_coverage_split?match_id=N` | コート前後エリアカバレッジ（シングルス/ダブルス対応） |
| F-002 | `GET /analysis/partner_comparison?player_id=N` | ダブルスパートナー別勝率・相乗効果スコア |
| F-003 | `GET /analysis/doubles_serve_receive?player_id=N` | ダブルスのサーブ/レシーブ別勝率 |
| F-004 | `GET /analysis/stroke_sharing?player_id=N` | ダブルスのストローク分担バランス分析 |
| G-001 | `GET /analysis/epv?player_id=N` | マルコフ連鎖EPV（上位/下位パターン） |
| G-002 | `GET /analysis/shot_influence?match_id=N` | ショット影響度スコア（アナリスト・コーチ向け） |
| H-001 | `GET /analysis/interval_report?match_id=N&completed_set_num=K` | セット間速報ベイズ推定レポート |

### Phase 3: レポートエンドポイント（`backend/routers/reports.py`）

| ID | エンドポイント | 説明 |
|----|--------------|------|
| I-001 | `GET /reports/scouting?player_id=N` | スカウティングレポート（PDF or JSON） |
| I-002 | `GET /reports/player_growth?player_id=N` | 選手成長レポート（禁止ワードサニタイズ済み） |
| I-003 | `GET /reports/interval_flash?match_id=N&completed_set_num=K` | セット間速報JSONレポート（<30秒） |

## 2. 新規フロントエンドコンポーネント一覧

### `src/components/analysis/`

| ファイル | コンポーネント | 説明 |
|---------|--------------|------|
| `ScoreProgression.tsx` | `ScoreProgression` | スコア推移ラインチャート（セットセレクター付き） |
| `WinLossComparison.tsx` | `WinLossComparison` | 勝ち/課題のある試合比較（RoleGuard: analyst/coach） |
| `TournamentComparison.tsx` | `TournamentComparison` | 大会レベル別棒グラフ+テーブル |
| `PreLossPatterns.tsx` | `PreLossPatterns` | 失点前パターンタブ（選手向けは成長エリアフレーミング） |
| `FirstReturnAnalysis.tsx` | `FirstReturnAnalysis` | ファーストリターンゾーン別テーブル |
| `TemporalPerformance.tsx` | `TemporalPerformance` | スコアフェーズ別3段棒グラフ |
| `PostLongRallyStats.tsx` | `PostLongRallyStats` | 長ラリー後比較カード |
| `OpponentStats.tsx` | `OpponentStats` | 対戦相手一覧テーブル（RoleGuard: analyst/coach） |
| `MarkovEPV.tsx` | `MarkovEPV` | EPVカード（下位パターンはanalyst/coachのみ） |
| `IntervalReport.tsx` | `IntervalReport` | セット間速報ベイズ推定表示 |

### `src/pages/DashboardPage.tsx` 更新内容

- 新規タブ: `b_detail`, `c_spatial`, `d_time`, `e_opponent`, `f_doubles`, `g_markov`
- J-001 フィルターパネル追加（試合結果/大会レベルフィルター）
- 概要タブ: 試合クリックでScoreProgression表示
- 概要タブ: IntervalReport統合
- 全タブにRoleGuard適用（アナリスト/コーチ限定コンテンツ）

## 3. 新規解析エンジン

| ファイル | クラス | 説明 |
|---------|-------|------|
| `backend/analysis/markov.py` | `MarkovAnalyzer` | マルコフ連鎖+EPV計算（numpy使用、ラプラス平滑化、ブートストラップCI） |
| `backend/analysis/shot_influence.py` | `ShotInfluenceAnalyzer` | ショット影響度（ヒューリスティック、sklearnがあれば回帰） |
| `backend/analysis/bayesian_rt.py` | `BayesianRealTimeAnalyzer` | ベイズリアルタイム解析（Beta-Binomial共役更新、95%CI） |

## 4. テストデータ生成

- スクリプト: `scripts/generate_test_data.py`
- 生成内容: 5試合、417ラリー、3059ストローク
- 選手: 山田太郎(解析対象)、佐藤次郎、鈴木三郎、田中四郎
- 試合形式: シングルス×4、混合ダブルス×1
- 大会レベル: IC×3、SJL×1、国内×1

## 5. テスト結果

```
78 passed, 1 warning in 3.69s
```

### 新規テストファイル

| ファイル | テスト数 | 内容 |
|---------|---------|------|
| `test_markov.py` | 7 | EPV範囲、ゼロ除算、行列正規化、CIカバレッジ |
| `test_bayesian_rt.py` | 6 | 事後分布、CI幅、応答時間(<30秒) |
| `test_reports.py` | 8 | 禁止ワードサニタイズ、免責事項テキスト |
| `test_analysis_endpoints.py` | 17 | 全新規エンドポイントの200応答、空データ処理 |

### フロントエンドビルド

```
✓ 2850 modules transformed.
✓ built in 12.35s
```

## 6. アーキテクチャルール準拠確認

| ルール | 確認状況 |
|--------|---------|
| 日本語文字列はja.jsonに定義 | ✅ 新規キー追加済み |
| 全解析ビューにConfidenceBadge表示 | ✅ 全コンポーネントで実装 |
| "弱点"等の禁止ワード不使用 | ✅ sanitize_player_text で全置換 |
| RoleGuardでアナリスト/コーチ限定 | ✅ WinLossComparison, OpponentStats等で適用 |
| バックエンドは meta: {sample_size, confidence} を返す | ✅ 全エンドポイントで実装 |
| コメントは日本語 | ✅ 全ファイルで遵守 |

## 7. 既知の制限事項

- **F-001〜F-004 (ダブルス)**: フロントエンドの`f_doubles`タブはプレースホルダー表示。バックエンドエンドポイントは実装済み。
- **G-002 (ShotInfluence)**: sklearnがvenv未インストールのためヒューリスティックモード動作。
- **I-001 (PDF生成)**: reportlab利用可能なら日本語PDFを生成するが、フォント環境依存。Windowsフォント(meiryo.ttc)がなければJSON形式にフォールバック。
- **EPV計算**: サンプル数が少ない場合（<50ラリー）は統計的信頼性が低い旨をConfidenceBadgeで表示。
- **フィルターパネル**: フィルター状態は保持されるが、各解析APIへのクエリパラメータ伝搬は未実装（UIのみ）。
