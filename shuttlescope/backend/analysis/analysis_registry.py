"""
analysis_registry.py — 解析種別メタデータの統合レジストリ

全解析種別について tier / evidence / サンプル閾値 / page / section を
1 か所で管理する。

このモジュールは以前に分散していた情報を集約する:
  - analysis_meta.py    (EVIDENCE_META)
  - analysis_tiers.py   (ANALYSIS_TIERS + TIER_MIN_SAMPLES)
  - promotion_rules.py  (PROMOTION_CRITERIA)
  - analysis_spine.py   (_infer_tier ローカル関数)

提供 API:
  get_analysis_meta(analysis_type)  -> RegistryEntry
  get_tier(analysis_type)           -> str
  list_registry_entries()           -> list[RegistryEntry]
"""
from __future__ import annotations
from typing import TypedDict, Literal, Optional


AnalysisTier = Literal["stable", "advanced", "research"]
# 標本の単位。`sample_size` が何を数えた値なのかは解析ごとに違う。
# D-5: 宣言が無かったので UI の ConfidenceBadge は全部「球」として扱い、
# 試合数を渡していた画面は**永久に★1つ・赤の「参考値」**に固定され、
# しかもツールチップには「球」と出ていた。値も単位も誤りだった。
SampleUnit = Literal["strokes", "rallies", "matches"]
EvidenceLevel = Literal["exploratory", "directional", "practical_candidate", "practical_adopted"]
# 画面上部の絞り込み (結果・大会レベル・期間) がこの解析の母集団に効くか。全エントリで宣言が必須。
#   filtered    : エンドポイントが MatchFilter を受け取り、母集団に掛ける
#   global_only : 設計上、絞り込みを使わない (選手の全試合が母集団)。カードは「絞り込み対象外」を出す
#   not_wired   : 絞り込みの対象にすべきだが、エンドポイントがまだ受け取らない (git grep で確認済みの宣言)
FilterScope = Literal["filtered", "global_only", "not_wired"]
FILTER_SCOPE_FILTERED = "filtered"
FILTER_SCOPES = ("filtered", "global_only", "not_wired")


class RegistryEntry(TypedDict):
    analysis_type: str
    tier: AnalysisTier
    evidence_level: EvidenceLevel
    min_recommended_sample: int
    # `sample_size` が数えている単位。分かっているものだけ宣言する。
    # 推測で埋めると「単位の分からない数字」に戻るので、
    # **エンドポイントが実際に何を渡しているかを読んでから**書くこと。
    sample_unit: Optional[SampleUnit]
    filter_scope: FilterScope
    caution: Optional[str]
    assumptions: Optional[str]
    promotion_criteria: Optional[str]
    page: str     # "dashboard" | "analyst"
    section: str  # "overview" | "advanced" | "research" | "spine_rs1" … "spine_rs5"


# ── Tier 別デフォルトサンプル閾値 ──────────────────────────────────────────
TIER_MIN_SAMPLES: dict[str, int] = {
    "stable":   10,
    "advanced": 30,
    "research": 50,
}

# ── Tier 別出力制御方針 ─────────────────────────────────────────────────────
TIER_OUTPUT_POLICY: dict[str, dict[str, bool]] = {
    "stable": {
        "show_conclusion": True,
        "show_comparison": True,
        "show_suggestion": True,
    },
    "advanced": {
        "show_conclusion": True,
        "show_comparison": True,
        "show_suggestion": True,  # データが十分な場合のみ
    },
    "research": {
        "show_conclusion": False,   # 結論ではなく傾向のみ
        "show_comparison": True,
        "show_suggestion": False,
    },
}

# ── 生定義リスト ─────────────────────────────────────────────────────────────
# 各エントリの min_recommended_sample は TIER_MIN_SAMPLES から自動補完される。
# tier / evidence_level / page / section は全て必須。

_RAW: list[dict] = [

    # =========================================================================
    # stable tier
    # =========================================================================

    {
        "analysis_type": "descriptive",
        "filter_scope": "filtered",
        "tier": "stable",
        "evidence_level": "practical_adopted",
        "caution": None,
        "assumptions": None,
        "promotion_criteria": None,
        "page": "dashboard",
        "section": "overview",
    },
    {
        "analysis_type": "heatmap",
        "filter_scope": "filtered",
        "sample_unit": "strokes",
        "tier": "stable",
        "evidence_level": "practical_adopted",
        "caution": None,
        "assumptions": "打点・着地点はアノテーション精度に依存します。",
        "promotion_criteria": None,
        "page": "dashboard",
        "section": "overview",
    },
    {
        "analysis_type": "score_progression",
        "filter_scope": "not_wired",
        "tier": "stable",
        "evidence_level": "practical_adopted",
        "caution": None,
        "assumptions": None,
        "promotion_criteria": None,
        "page": "dashboard",
        "section": "overview",
    },
    {
        "analysis_type": "pre_win_pre_loss",
        "filter_scope": "filtered",
        "tier": "stable",
        "evidence_level": "practical_candidate",
        "caution": "サンプル数が少ない場合、パターンが不安定になる可能性があります。",
        "assumptions": "直近N打の相関を集計しています。因果関係を示すものではありません。",
        "promotion_criteria": "N≥200ラリー・複数大会にわたる安定性の確認",
        "page": "dashboard",
        "section": "overview",
    },
    {
        "analysis_type": "first_return",
        "filter_scope": "filtered",
        "tier": "stable",
        "evidence_level": "practical_candidate",
        "caution": "ショット種別の粒度はアノテーション入力精度に依存します。",
        "assumptions": None,
        "promotion_criteria": "N≥150ラリーの安定確認",
        "page": "dashboard",
        "section": "overview",
    },
    {
        "analysis_type": "set_summary",
        "filter_scope": "not_wired",
        "tier": "stable",
        "evidence_level": "practical_adopted",
        "caution": None,
        "assumptions": None,
        "promotion_criteria": None,
        "page": "dashboard",
        "section": "overview",
    },

    # =========================================================================
    # advanced tier
    # =========================================================================

    {
        "analysis_type": "pressure",
        "filter_scope": "filtered",
        "tier": "advanced",
        "evidence_level": "practical_candidate",
        "caution": "プレッシャー定義（スコア閾値）は固定値です。実際の心理的プレッシャーとは異なる場合があります。",
        "assumptions": "デュースと、得点後にどちらかが17点以上の終盤を、通常局面と分けて集計します。点差は見ていません。",
        "promotion_criteria": "N≥300試合・プレッシャー定義の校正",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "transition",
        "filter_scope": "filtered",
        "tier": "advanced",
        "evidence_level": "practical_candidate",
        "caution": "遷移確率はサンプル不足で不安定になる可能性があります。",
        "assumptions": "1次マルコフ過程を仮定（前のショットのみ参照）。",
        "promotion_criteria": "N≥500ショット・クロス大会検証",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "temporal",
        "filter_scope": "filtered",
        "tier": "advanced",
        "evidence_level": "directional",
        "caution": "セット内時間帯の効果量は小さい場合があります。過度な解釈を避けてください。",
        "assumptions": "セット内ラリー順番を時間代理として使用。実際の時間は不使用。",
        "promotion_criteria": "N≥300ラリー・大会レベル別再現性確認",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "post_long_rally",
        "filter_scope": "filtered",
        "tier": "advanced",
        "evidence_level": "directional",
        "caution": "ロングラリー後効果のサンプルは少なくなりがちです。",
        "assumptions": "ラリー長10打以上を「ロングラリー」と定義（全カード共通の基準値）。",
        "promotion_criteria": "N≥100ロングラリーの安定確認",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "growth",
        "filter_scope": "filtered",
        "tier": "advanced",
        "evidence_level": "practical_candidate",
        "caution": "成長判定は過去試合の比較です。コンディション・対戦相手の変化を反映しません。",
        "assumptions": "時系列を試合日付順として扱います。同日複数試合は平均化されます。",
        "promotion_criteria": "N≥8試合・季節性コントロールの検討",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "doubles_tactical",
        "filter_scope": "not_wired",
        "tier": "advanced",
        "evidence_level": "directional",
        "caution": "ダブルス分析はダブルス試合のみが対象です。シングルスデータは含みません。",
        "assumptions": "ローテーション判定はラリー構造から推定します。",
        "promotion_criteria": "N≥50ダブルス試合・ポジション精度検証",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "markov",
        "filter_scope": "not_wired",
        "tier": "advanced",
        "evidence_level": "directional",
        "caution": "マルコフモデルは定常性を仮定します。実際の戦術変化は反映されません。",
        "assumptions": "1次マルコフ過程。状態はスコア差・ラリーフェーズ・モメンタムの3次元。",
        "promotion_criteria": "予測の当たり具合（ブライアスコア）の改善・N≥500ラリー",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "shot_quality",
        "filter_scope": "not_wired",
        "tier": "advanced",
        "evidence_level": "directional",
        "caution": "ショット品質スコアはルールベースのヒューリスティックです。",
        "assumptions": "ゾーン・ショット種別・勝率の組み合わせから品質を推定します。",
        "promotion_criteria": "N≥300ショット・コーチ有用性確認",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "movement",
        "filter_scope": "not_wired",
        "tier": "advanced",
        "evidence_level": "directional",
        "caution": "動線解析はアノテーション精度に依存します。",
        "assumptions": "ショット位置系列からの動線推定です。実際の移動経路とは異なります。",
        "promotion_criteria": "N≥300ラリー・トラッキングデータとの照合",
        "page": "dashboard",
        "section": "advanced",
    },

    # =========================================================================
    # research tier — dashboard research cards
    # =========================================================================

    {
        "analysis_type": "counterfactual",
        "filter_scope": "not_wired",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "反事実的比較は仮説的シナリオです。実際に選択されなかった行動の価値は直接観測できません。",
        "assumptions": "文脈一致（前のショット種別・スコア圧力・ラリーフェーズ）による比較。交絡制御は行っていません。",
        "promotion_criteria": "傾向スコアによる交絡制御・ブートストラップ法による信頼区間の導入・N≥500コンテキスト一致",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "recommendation",
        "filter_scope": "not_wired",
        "tier": "research",
        "evidence_level": "directional",
        "caution": "推奨スコアはパターン頻度に基づきます。因果的な有効性を保証するものではありません。",
        "assumptions": "観測された高頻度・高勝率パターンを正の推奨として扱います。",
        "promotion_criteria": "前向き検証・選手フィードバックによる有用性確認",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "opponent_affinity",
        "filter_scope": "filtered",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "対戦相手タイプは、ラリーの長さやドライブ率などの数値を固定のしきい値で区切って分けた分類です。個別の選手特性を正確に反映しない場合があります。",
        "assumptions": "統計的なクラスタリングは使っていません。攻撃型・守備型などのラベルは、しきい値のルールで割り当てています。",
        "promotion_criteria": "分類器の精度検証・外部ラベルとの照合",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "pair_synergy",
        "filter_scope": "filtered",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "ペアシナジースコアはパフォーマンス差から推定します。ポジション役割は考慮されていません。",
        "assumptions": "ダブルス試合での個人成績差を「ペア効果」として推定します。",
        "promotion_criteria": "ロール推定精度の向上・N≥30ペア試合",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "epv",
        "filter_scope": "filtered",
        "tier": "research",
        "evidence_level": "directional",
        "caution": (
            "EPVはマルコフモデルに基づく探索的指標です。定常性仮定・独立ラリー仮定を含みます。"
            "球種ごとの攻撃力の大きさは、このデータから推定した値ではなく、"
            "あらかじめ人が決めた固定の値です。"
            "順序の傾向として読み、数値そのものを根拠にしないでください。"
        ),
        "assumptions": (
            "定常1次マルコフ過程。各ラリーは独立と仮定。"
            "球種の攻撃力は人が決めた固定値 (スマッシュ 0.85 … 守備的ショット 0.25) を使用。"
        ),
        "promotion_criteria": "校正品質改善・状態定義の安定化・N≥500ラリー",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "shot_influence",
        "filter_scope": "not_wired",
        "sample_unit": "rallies",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": (
            "ショット影響度は因果効果ではありません。"
            "「相関ベース」ですらなく、球種の攻撃重みと品質係数は"
            "このデータに当てはめた値ではなく、人が決めた固定値です。"
            "注釈から来るのは球種・品質・勝敗の組合せだけで、大きさは人が決めた値です。"
        ),
        "assumptions": (
            "ラリー内ポジション・攻撃重み・勝敗の積として影響度を定義します。"
            "攻撃重み (スマッシュ 0.85 … 守備的ショット 0.25) と品質係数 (優 1.5 … 不良 0.6) は"
            "人が決めた固定値で、選手やデータに合わせた調整はしていません。"
        ),
        "promotion_criteria": "状態条件付き推定・ブートストラップ法による信頼区間の導入",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "spatial_density",
        "filter_scope": "not_wired",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "空間密度マップは打点・着地点の可視化です。統計的有意性検定は行っていません。",
        "assumptions": "ゾーン区分はコート9分割（3x3）を使用します。",
        "promotion_criteria": "有意差検定（χ²等）の導入・解像度向上",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "peer_comparison",
        "filter_scope": "not_wired",
        "tier": "research",
        "evidence_level": "exploratory",
        "min_recommended_sample": 5,
        "caution": "コミュニティ内の比較は管理者だけが使える試験的な機能です。5 人未満の集団は表示せず、デモデータも除外して個人が特定されないようにしています。",
        "assumptions": "デモ以外の選手全体から比較対象の集団を抽出し、四分位・平均・標準偏差の集計値だけを返します。個別選手の値は返しません。",
        "promotion_criteria": "本人の同意を得て参加する仕組みの実装・比較対象の集団の取り方の妥当性検証",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "bayesian_rt",
        "filter_scope": "not_wired",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "ベイズ反応時間推定は探索段階です。",
        "assumptions": "ラリー内タイミングデータから反応時間を推定します。",
        "promotion_criteria": "反応時間測定との照合・N≥200ラリー",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "exploitability",
        "filter_scope": "filtered",
        "sample_unit": "strokes",
        "tier": "research",
        "evidence_level": "exploratory",
        "min_recommended_sample": 20,
        "caution": (
            "ナッシュ均衡の推定は、仮想対戦を繰り返して求めた近似値です。"
            "サンプルが少ない状態では補正が強く効くため、"
            "推定値の分散が大きくなります。"
        ),
        "assumptions": (
            "各ゲーム状態を 2 人ゼロ和ゲームとして独立に扱います。"
            "状態間の相関・相手の適応的戦術変化は考慮しません。"
            "行動ラベルは 18 ショット種別を 7 バケットに粗化しています。"
        ),
        "promotion_criteria": (
            "状態ごと N≥50 サンプル・ブートストラップ区間の幅 0.1 以内・"
            "クロス大会安定性確認・傾向スコアによる交絡制御導入"
        ),
        "page": "analyst",
        "section": "research",
    },
    {
        "analysis_type": "conformal",
        "filter_scope": "filtered",
        "sample_unit": "rallies",
        "tier": "research",
        "evidence_level": "exploratory",
        "min_recommended_sample": 40,
        "caution": (
            "コンフォーマル予測は全体としての的中率は保証しますが、"
            "グループ別の的中率までは保証しません。"
            "グループ別の勝率は少数でも極端な値にならないよう補正した実績値で、"
            "サンプル数が少ないグループでは不確実性が大きくなります。"
        ),
        "assumptions": (
            "校正用データと検証用データが同じ性質（独立同分布）であることを仮定します。"
            "データは偶数番目を校正用、奇数番目を検証用に半分ずつ分けます。"
            "基準になる予測はグループ別の補正済み勝率です。"
        ),
        "promotion_criteria": (
            "N≥200 ラリー・グループ別条件付き被覆率の検証・"
            "より強力なベーススコアラー（ロジスティック回帰等）との比較・"
            "クロス大会安定性確認"
        ),
        "page": "analyst",
        "section": "research",
    },
    {
        "analysis_type": "policy_eval",
        "filter_scope": "filtered",
        "sample_unit": "strokes",
        "tier": "research",
        "evidence_level": "exploratory",
        "min_recommended_sample": 20,
        "caution": (
            "二重に頑健な方策評価による推定値です。サンプルが少ない状態では "
            "重みのばらつきが大きく、信頼区間が広がります。"
        ),
        "assumptions": (
            "各ラリーを 1 回の選択 (状態・行動・勝敗) として扱います。"
            "評価する方策は、実績の勝率が高い行動へ選択を寄せたものです。"
        ),
        "promotion_criteria": "状態ごと N≥50・信頼区間の幅 0.1 以内・比較する方策の設計の妥当性検証",
        "page": "analyst",
        "section": "research",
    },
    {
        "analysis_type": "style_distance",
        "filter_scope": "filtered",
        "tier": "research",
        "evidence_level": "exploratory",
        "min_recommended_sample": 3,
        "caution": (
            "着地点の分布どうしの距離 (最適輸送) による棋風の比較です。"
            "試合数が少ない選手の分布は不安定なため、比較は試合数の十分な選手に限ります。"
        ),
        "assumptions": (
            "9 ゾーンのコート上の中心位置を使い、ゾーン間の直線距離で測ります。"
            "比較対象は閲覧権限のある選手のみで、他チームの選手は除外します。"
        ),
        "promotion_criteria": "選手ごと N≥10 試合・ゾーン重心の実測校正・複数特徴量への拡張",
        "page": "analyst",
        "section": "research",
    },
    {
        "analysis_type": "matchup_forecast",
        "filter_scope": "filtered",
        "sample_unit": "matches",
        "tier": "research",
        "evidence_level": "exploratory",
        "min_recommended_sample": 5,
        "caution": (
            "階層ベイズ (ブラッドリー・テリーモデル) による対戦勝率の予測です。直接対戦が少ない組では "
            "全体の平均に近づけて推定するため、信頼区間が広くなります (過信を避けるため)。"
        ),
        "assumptions": (
            "各選手の強さが全体の分布から生まれると仮定し、近似計算で推定します。"
            "勝つ確率は 2 人の強さの差から求めます。比較対象は閲覧権限のある選手のみです。"
        ),
        "promotion_criteria": "対戦ごと N≥5・予測の当たり具合の検証・大会やコンディションなどの要因の導入",
        "page": "analyst",
        "section": "research",
    },

    # =========================================================================
    # research tier — analyst spine (RS-1〜RS-5)
    # =========================================================================

    {
        "analysis_type": "epv_state",
        "filter_scope": "filtered",
        "sample_unit": "rallies",
        "tier": "research",
        "evidence_level": "directional",
        "caution": "状態ベースEPVは状態定義の品質に強く依存します。状態数が少ない場合、推定が不安定になります。",
        "assumptions": "スコアフェーズ・セット番号・ラリーバケット・サーブ側の4次元状態を使用します。",
        "promotion_criteria": "状態ごとN≥50・信頼区間の幅0.2以内・クロス大会安定性",
        "page": "analyst",
        "section": "spine_rs1",
    },
    {
        "analysis_type": "state_action",
        "filter_scope": "filtered",
        "sample_unit": "rallies",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "状態-行動価値（Q値）はサンプル不足で高分散になります。少サンプル時は信頼区間の幅が広くなります。",
        "assumptions": "行動＝ショット種別。即時報酬＝ラリー勝率とします（将来割引なし）。",
        "promotion_criteria": "状態×行動ごとN≥30・信頼区間幅0.3以内",
        "page": "analyst",
        "section": "spine_rs2",
    },
    {
        "analysis_type": "hazard_fatigue",
        "filter_scope": "filtered",
        "sample_unit": "rallies",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "ハザード推定はラリー結果の時系列パターンから計算します。実際の疲労と一致しない場合があります。",
        "assumptions": "生存分析（コックス比例ハザード）を簡略化した、ラリーごとの崩れやすさの推定を使います。実際の体力測定は使用しません。",
        "promotion_criteria": "生理指標との相関確認・N≥500ラリーの安定確認",
        "page": "analyst",
        "section": "spine_rs3",
    },
    {
        "analysis_type": "counterfactual_v2",
        "filter_scope": "filtered",
        "sample_unit": "rallies",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "反事実比較の第 1 段階で、ブートストラップ法による信頼区間（不確実性）を含みます。傾向スコアによる偏りの補正は含まれません。",
        "assumptions": "文脈が一致するプレーを多次元で比べ、ブートストラップ法で信頼区間を求めます。比較に使える最低限の重なりの基準があります。",
        "promotion_criteria": "傾向スコアによる重み付け・N≥500コンテキスト・対戦相手のタイプ別の比較",
        "page": "analyst",
        "section": "spine_rs3",
    },
    {
        "analysis_type": "bayes_matchup",
        "filter_scope": "not_wired",
        "sample_unit": "matches",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "経験的ベイズは事前分布をデータから推定します。データ不足時は強く事前に引っ張られます。",
        "assumptions": "勝ち負けの回数から事前の傾向を加味して対戦勝率を推定します（ベータ二項モデル）。利き手・試合形式の情報は考慮します。",
        "promotion_criteria": "予測の当たり具合（ブライアスコア）の改善・N≥50試合・外部データでの検証",
        "page": "analyst",
        "section": "spine_rs4",
    },
    {
        "analysis_type": "opponent_policy",
        "filter_scope": "filtered",
        "sample_unit": "strokes",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "対戦相手ポリシーは観測されたショット選択の統計です。意図的な戦術変化は反映しません。",
        "assumptions": "多軸（スコア・ラリーフェーズ・受けた球の着地ゾーン）条件付きショット分布を使用します。ゾーンは打つ前に分かる直前ストロークの着地点で、予測対象ショット自身の着地点は使いません。",
        "promotion_criteria": "予測精度（交差検証）・N≥100対戦試合",
        "page": "analyst",
        "section": "spine_rs4",
    },
    {
        "analysis_type": "doubles_role",
        "filter_scope": "filtered",
        "sample_unit": "strokes",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "ロール推定（前衛/後衛）はラリー構造のルールベース分類です。実際のポジションとは異なる場合があります。",
        "assumptions": "ショット種別・順番から前衛/後衛ロールをルールで判定します。状態遷移モデルによる推定は未実装です。",
        "promotion_criteria": "トラッキングデータとの照合・状態遷移モデルによる推定への移行",
        "page": "analyst",
        "section": "spine_rs5",
    },
    {
        # 登録が無かったため get_analysis_meta は未知扱いのフォールバック (research / exploratory) を返していた。
        # その値のまま、filter_scope だけを宣言する (tier などの判断はここでは変えない)
        "analysis_type": "opponent_stats",
        "filter_scope": "filtered",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "このモジュールは研究段階です。",
        "assumptions": None,
        "promotion_criteria": None,
        "page": "analyst",
        "section": "research",
    },
    {
        # 選手の全試合から数える共通の素材 (bundle_context の rs_*)。絞り込みは使わない
        "analysis_type": "rally_sequence_patterns",
        "filter_scope": "global_only",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "このモジュールは研究段階です。",
        "assumptions": None,
        "promotion_criteria": None,
        "page": "analyst",
        "section": "research",
    },
    {
        # DB-3。`doubles_role` とは数えているものが違う (試合数)。
        # 同じエントリを借りていたので、**打球数向けの閾値で試合数を judge** して
        # いた。ロール推定そのものとは別の解析として登録する。
        "analysis_type": "doubles_role_stability",
        "filter_scope": "filtered",
        "sample_unit": "matches",
        "tier": "research",
        "evidence_level": "exploratory",
        "min_recommended_sample": 10,
        "caution": "ロール安定性は試合ごとのロール推定を集約したものです。元のロール推定がルールベースである制約をそのまま引き継ぎます。",
        "assumptions": "ダブルスの試合ごとに推定したロールの一貫性を測ります。試合数が少ないと安定性は測れません。",
        "promotion_criteria": "ロール推定自体の精度検証",
        "page": "analyst",
        "section": "spine_rs5",
    },
]

# ── レジストリ構築 ───────────────────────────────────────────────────────────

def _build_registry() -> dict[str, RegistryEntry]:
    reg: dict[str, RegistryEntry] = {}
    for raw in _RAW:
        tier: str = raw["tier"]
        entry: RegistryEntry = {
            "analysis_type": raw["analysis_type"],
            "tier": tier,  # type: ignore[typeddict-item]
            "evidence_level": raw["evidence_level"],  # type: ignore[typeddict-item]
            "min_recommended_sample": raw.get("min_recommended_sample", TIER_MIN_SAMPLES.get(tier, 50)),
            "sample_unit": raw.get("sample_unit"),
            # 必須。書き忘れは KeyError にして、黙って "filtered" 扱いにしない
            "filter_scope": raw["filter_scope"],  # type: ignore[typeddict-item]
            "caution": raw.get("caution"),
            "assumptions": raw.get("assumptions"),
            "promotion_criteria": raw.get("promotion_criteria"),
            "page": raw["page"],
            "section": raw["section"],
        }
        reg[raw["analysis_type"]] = entry
    return reg


ANALYSIS_REGISTRY: dict[str, RegistryEntry] = _build_registry()

_FALLBACK: RegistryEntry = {
    "analysis_type": "unknown",
    "tier": "research",
    "evidence_level": "exploratory",
    "min_recommended_sample": 50,
    "sample_unit": None,
    "filter_scope": "not_wired",
    "caution": "このモジュールは研究段階です。",
    "assumptions": None,
    "promotion_criteria": None,
    "page": "analyst",
    "section": "research",
}


# ── 公開 API ─────────────────────────────────────────────────────────────────

def get_analysis_meta(analysis_type: str) -> RegistryEntry:
    """
    analysis_type の RegistryEntry を返す。

    未知の analysis_type は exploratory / research のフォールバックを返す。
    """
    if analysis_type in ANALYSIS_REGISTRY:
        return ANALYSIS_REGISTRY[analysis_type]
    return {**_FALLBACK, "analysis_type": analysis_type}  # type: ignore[return-value]


def get_filter_scope(analysis_type: str) -> str:
    """analysis_type の filter_scope。未知の analysis_type は 'not_wired'。"""
    return get_analysis_meta(analysis_type)["filter_scope"]


def get_tier(analysis_type: str) -> str:
    """analysis_type の tier を返す。未知の場合は 'research'"""
    return ANALYSIS_REGISTRY.get(analysis_type, _FALLBACK)["tier"]


def list_registry_entries() -> list[RegistryEntry]:
    """全登録済みエントリをリストで返す（API レスポンス用）。"""
    return list(ANALYSIS_REGISTRY.values())


# ── 3rd-review #5 fix: tier-based sample-size enforcement ────────────────────
#
# CLAUDE.md non-negotiable rules:
#   - "New analyses must declare evidence level, minimum sample size, and
#      behavior when the threshold is unmet."
#   - "Promotion ... is governed by promotion_rules.py (do not bypass)"
#
# 旧コードは register したサンプル閾値を **エンドポイント側から自発的に**
# 見るしかなく、analyst が知らずに低 N で叩くと research / advanced 結果が
# warning なしで返っていた。
#
# evaluate_sample(): 非例外。レスポンスに含めるためのデータを返す。
# check_or_raise(): 例外。research / advanced で hard-gate したい時に使う。
#
# 段階導入の指針:
#   - stable tier は引き続き従来挙動 (ConfidenceBadge 依存)。
#   - advanced tier はレスポンスに `sample_diagnostic` を埋めるため
#     evaluate_sample を呼ぶ運用を推奨。
#   - research tier は hard-gate (check_or_raise) が CLAUDE.md の趣旨に最も近い。

class InsufficientSampleError(Exception):
    """サンプル数不足を構造化して上位に伝える例外。

    routers 側で FastAPI HTTPException に変換する。
    本モジュール自体は FastAPI に依存しないため、HTTP レイヤとは結合させない。
    """

    def __init__(
        self,
        analysis_type: str,
        tier: str,
        sample_size: int,
        min_recommended_sample: int,
    ) -> None:
        self.analysis_type = analysis_type
        self.tier = tier
        self.sample_size = sample_size
        self.min_recommended_sample = min_recommended_sample
        super().__init__(
            f"insufficient_sample: analysis_type={analysis_type} tier={tier} "
            f"n={sample_size} < min_recommended={min_recommended_sample}"
        )

    def to_dict(self) -> dict:
        """FastAPI HTTPException(detail=...) に渡せる形に整形。"""
        return {
            "code": "insufficient_sample",
            "analysis_type": self.analysis_type,
            "tier": self.tier,
            "sample_size": self.sample_size,
            "min_recommended_sample": self.min_recommended_sample,
        }


class SampleDiagnostic(TypedDict):
    """レスポンスに埋め込むための診断情報。"""
    analysis_type: str
    tier: str
    sample_size: int
    min_recommended_sample: int
    is_sufficient: bool


def evaluate_sample(analysis_type: str, sample_size: int) -> SampleDiagnostic:
    """
    サンプル数を分類するだけの非例外ヘルパー。

    - 未知 analysis_type は _FALLBACK (research / 50) で評価される。
    - 結果はそのままレスポンスに含めて UI 側の ConfidenceBadge に渡せる。
    """
    meta = get_analysis_meta(analysis_type)
    min_recommended = meta["min_recommended_sample"]
    return {
        "analysis_type": analysis_type,
        "tier": meta["tier"],
        "sample_size": sample_size,
        "min_recommended_sample": min_recommended,
        "is_sufficient": sample_size >= min_recommended,
    }


def check_or_raise(
    analysis_type: str,
    sample_size: int,
    *,
    enforce_tiers: tuple[str, ...] = ("research", "advanced"),
) -> None:
    """
    サンプル数が tier 閾値未満なら InsufficientSampleError を raise する。

    enforce_tiers で「強制したい tier」を指定する。デフォルトは
    research / advanced。stable tier は既定で対象外 (ConfidenceBadge で
    UI 側が処理する)。

    - 未知 analysis_type は research 扱い (フォールバック挙動)。
    - sample_size が負値なら 0 として扱う (defensive)。

    例:
        check_or_raise("opponent_policy", n_rallies)
        # advanced/research で n_rallies < TIER_MIN_SAMPLES[tier] なら raise
    """
    if sample_size is None or sample_size < 0:
        sample_size = 0
    meta = get_analysis_meta(analysis_type)
    tier = meta["tier"]
    if tier not in enforce_tiers:
        return
    min_recommended = meta["min_recommended_sample"]
    if sample_size < min_recommended:
        raise InsufficientSampleError(
            analysis_type=analysis_type,
            tier=tier,
            sample_size=sample_size,
            min_recommended_sample=min_recommended,
        )
