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
EvidenceLevel = Literal["exploratory", "directional", "practical_candidate", "practical_adopted"]


class RegistryEntry(TypedDict):
    analysis_type: str
    tier: AnalysisTier
    evidence_level: EvidenceLevel
    min_recommended_sample: int
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
        "tier": "advanced",
        "evidence_level": "practical_candidate",
        "caution": "プレッシャー定義（スコア閾値）は固定値です。実際の心理的プレッシャーとは異なる場合があります。",
        "assumptions": "スコア17点以上・3点差以上を「プレッシャー局面」とします。",
        "promotion_criteria": "N≥300試合・プレッシャー定義の校正",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "transition",
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
        "tier": "advanced",
        "evidence_level": "directional",
        "caution": "ロングラリー後効果のサンプルは少なくなりがちです。",
        "assumptions": "ラリー長8+打を「ロングラリー」と定義。",
        "promotion_criteria": "N≥100ロングラリーの安定確認",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "growth",
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
        "tier": "advanced",
        "evidence_level": "directional",
        "caution": "マルコフモデルは定常性を仮定します。実際の戦術変化は反映されません。",
        "assumptions": "1次マルコフ過程。状態はスコア差・ラリーフェーズ・モメンタムの3次元。",
        "promotion_criteria": "校正品質（Brier score）の改善・N≥500ラリー",
        "page": "dashboard",
        "section": "advanced",
    },
    {
        "analysis_type": "shot_quality",
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
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "反事実的比較は仮説的シナリオです。実際に選択されなかった行動の価値は直接観測できません。",
        "assumptions": "文脈一致（前のショット種別・スコア圧力・ラリーフェーズ）による比較。交絡制御は行っていません。",
        "promotion_criteria": "傾向スコアによる交絡制御・ブートストラップCI導入・N≥500コンテキスト一致",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "recommendation",
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
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "対戦相手タイプ分類は統計的クラスタリングです。個別の選手特性を正確に反映しない場合があります。",
        "assumptions": "スタイルラベル（攻撃型/守備型等）はルールベースで割り当てています。",
        "promotion_criteria": "分類器の精度検証・外部ラベルとの照合",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "pair_synergy",
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
        "tier": "research",
        "evidence_level": "directional",
        "caution": "EPVはマルコフモデルに基づく探索的指標です。定常性仮定・独立ラリー仮定を含みます。",
        "assumptions": "定常1次マルコフ過程。各ラリーは独立と仮定。",
        "promotion_criteria": "校正品質改善・状態定義の安定化・N≥500ラリー",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "shot_influence",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "ショット影響度は因果効果ではなく相関ベースのヒューリスティックです。",
        "assumptions": "ラリー内ポジション・攻撃重み・勝敗の積として影響度を定義します。",
        "promotion_criteria": "状態条件付き推定・BootstrapCIの導入",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "spatial_density",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "空間密度マップは打点・着地点の可視化です。統計的有意性検定は行っていません。",
        "assumptions": "ゾーン区分はコート9分割（3x3）を使用します。",
        "promotion_criteria": "有意差検定（χ²等）の導入・解像度向上",
        "page": "dashboard",
        "section": "research",
    },
    {
        "analysis_type": "bayesian_rt",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "ベイズ反応時間推定は探索段階です。",
        "assumptions": "ラリー内タイミングデータから反応時間を推定します。",
        "promotion_criteria": "反応時間測定との照合・N≥200ラリー",
        "page": "dashboard",
        "section": "research",
    },

    # =========================================================================
    # research tier — analyst spine (RS-1〜RS-5)
    # =========================================================================

    {
        "analysis_type": "epv_state",
        "tier": "research",
        "evidence_level": "directional",
        "caution": "状態ベースEPVは状態定義の品質に強く依存します。状態数が少ない場合、推定が不安定になります。",
        "assumptions": "スコアフェーズ・セット番号・ラリーバケット・サーブ側の4次元状態を使用します。",
        "promotion_criteria": "状態ごとN≥50・CI幅0.2以内・クロス大会安定性",
        "page": "analyst",
        "section": "spine_rs1",
    },
    {
        "analysis_type": "state_action",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "状態-行動価値（Q値）はサンプル不足で高分散になります。少サンプル時はCI幅が広くなります。",
        "assumptions": "行動＝ショット種別。即時報酬＝ラリー勝率とします（将来割引なし）。",
        "promotion_criteria": "状態×行動ごとN≥30・信頼区間幅0.3以内",
        "page": "analyst",
        "section": "spine_rs2",
    },
    {
        "analysis_type": "hazard_fatigue",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "ハザード推定はラリー結果の時系列パターンから計算します。実際の疲労と一致しない場合があります。",
        "assumptions": "Cox比例ハザードを簡略化した離散ハザードを使用します。実際の体力測定は使用しません。",
        "promotion_criteria": "生理指標との相関確認・N≥500ラリーの安定確認",
        "page": "analyst",
        "section": "spine_rs3",
    },
    {
        "analysis_type": "counterfactual_v2",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "CF-1フェーズ: ブートストラップCIによる不確実性推定を含みます。傾向スコア制御はまだ未実装です。",
        "assumptions": "文脈一致（多次元）でのブートストラップCI。重複サポート閾値あり。",
        "promotion_criteria": "傾向スコア重み付け（CF-2）・N≥500コンテキスト・対戦相手条件付き（CF-3）",
        "page": "analyst",
        "section": "spine_rs3",
    },
    {
        "analysis_type": "bayes_matchup",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "経験的ベイズは事前分布をデータから推定します。データ不足時は強く事前に引っ張られます。",
        "assumptions": "Beta-Binomial モデルによる対戦勝率の縮小推定。利き手・フォーマット情報は考慮します。",
        "promotion_criteria": "ブリアスコア改善・N≥50試合・外部検証",
        "page": "analyst",
        "section": "spine_rs4",
    },
    {
        "analysis_type": "opponent_policy",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "対戦相手ポリシーは観測されたショット選択の統計です。意図的な戦術変化は反映しません。",
        "assumptions": "多軸（スコア・ラリーフェーズ・ゾーン）条件付きショット分布を使用します。",
        "promotion_criteria": "予測精度（交差検証）・N≥100対戦試合",
        "page": "analyst",
        "section": "spine_rs4",
    },
    {
        "analysis_type": "doubles_role",
        "tier": "research",
        "evidence_level": "exploratory",
        "caution": "ロール推定（前衛/後衛）はラリー構造のルールベース分類です。実際のポジションとは異なる場合があります。",
        "assumptions": "ショット種別・順番から前衛/後衛ロールをルールで判定します。HMMは未実装です。",
        "promotion_criteria": "トラッキングデータとの照合・HMM移行（DB-2）",
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
            "min_recommended_sample": TIER_MIN_SAMPLES.get(tier, 50),
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
