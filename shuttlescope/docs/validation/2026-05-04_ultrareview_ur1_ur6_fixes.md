# 2026-05-04 ultrareview UR-1〜UR-6 修正

`/ultrareview 11` (PR #11 = full-repo diff) で検出された 6 件の analysis レイヤー欠陥を修正。

## 修正一覧

### UR-1: hazard_fatigue.py — set/match 境界跨ぎの連鎖計算
- `all_results` に `(match_id, set_id)` boundary tuple を 5 要素目として追加。
- after-long-rally ループ: `prev_b != curr_b` のとき continue。
- `window_trend`: `itertools.groupby` で boundary 単位にグループ化し、各グループ内で `WINDOW_SIZE` 単位に切る。`cumulative_offset` で表示用インデックスを連続化。
- 旧コードは異なる試合・セットを跨いで「ロングラリー後の失点」「直近5ラリーハザード」を計算しており、終盤値が常時バイアスしていた。

### UR-2: condition_analytics.py — best_performance_profile の二重カウント
- L330: `gap = round(t_min - cur, 2)` → `gap = round(t_max - cur, 2)`
- 推奨レンジ上限を超えているのに「下限まであと N」と表示するバグ。

### UR-3: shot_influence_v2.py — 存在しない ORM 属性への getattr フォールバック
- `role_by_match` は `'player_a'/'player_b'` を返すのに `'server'/'receiver'` で分岐していた → 全ラリーが silently 'server' に倒れていた。
- Rally の存在しない属性 `score_before_my` / `score_before_opp` / `won` を getattr デフォルトで参照 → 全ラリーが 0/forced-loss に潰れていた。
- 実 ORM 属性 `score_a_before` / `score_b_before` / `winner` を player_role と照合する形に修正。
- `build_rally_state(server=...)` も `rally.server == player_role` で渡す。

### UR-4: player_context.py — partner_b 視点で勝敗が反転していた
- `player_wins_match()` のパートナー判定が partner_a/partner_b 双方とも `match.result == 'win'` を返していた。
- partner_b 側は B サイドなので `match.result == 'loss'` で勝ちとなる。
- 修正後はダブルスの partner_b 集計勝率が正しく反映される。

### UR-5: opponent_classifier.py — taxonomy 正規化後 0 ヒットだった shot_type
- `_FAST_SHOT_TYPES = {"drive", "push"}` → `{"drive", "push_rush"}`
- `push` は canonical 名称ではないため、 `pace` 軸が事実上 `drive` 単独で判定されていた。

### UR-6: counterfactual_v2.py — 誤称 ipw_win_rate
- 真の IPW 補正には rally 単位 covariate が必要だが、現実装は context 完全一致時の単純集計しかしていない。
- `ipw_win_rate` を `marginal_win_rate` にリネーム（旧キーは deprecated alias として併置）。
- `ipw_correction_active: false` フラグを追加。
- `estimated_lift` は素の `win_rate` ベースで計算するように戻した（誤称値を使った lift 過大評価を防ぐ）。
- 真の IPW 実装は per-rally feature の整備後に再着手。

## 検証

- `python -m py_compile` で 6 ファイル全て構文 OK。
- 既存 pytest スイートは未走（修正対象に直接対応する test が無いため）。プロモーションタイミングで analysis_registry 経由の smoke は走る。

## デプロイ後

- バックエンド再起動が必要（FastAPI プロセスの import cache を切り替えるため）。

## 関連

- PR #11 (`tiny-readme-base ↔ ultrareview-snapshot`) は review 用の commit-tree based 仮想 PR。マージしないこと。レビュー終了後に branch + PR をクローズして良い。
