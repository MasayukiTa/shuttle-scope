"""
analysis_meta.py — 解析種別ごとの evidence メタデータ定義

各解析エンドポイントについて:
  - evidence_level: 証拠水準
  - caution: 表示時の注意文
  - assumptions: モデル前提
  - promotion_criteria: 上位 tier 移行に必要な条件
"""
from __future__ import annotations
from typing import Literal

EvidenceLevel = Literal["exploratory", "directional", "practical_candidate", "practical_adopted"]

EVIDENCE_META: dict[str, dict] = {
    # ── stable tier ──────────────────────────────────────────────────────────
    "descriptive": {
        "evidence_level": "practical_adopted",
        "caution": None,
        "assumptions": None,
        "promotion_criteria": None,
    },
    "heatmap": {
        "evidence_level": "practical_adopted",
        "caution": None,
        "assumptions": "打点・着地点はアノテーション精度に依存します。",
        "promotion_criteria": None,
    },
    "score_progression": {
        "evidence_level": "practical_adopted",
        "caution": None,
        "assumptions": None,
        "promotion_criteria": None,
    },
    "pre_win_pre_loss": {
        "evidence_level": "practical_candidate",
        "caution": "サンプル数が少ない場合、パターンが不安定になる可能性があります。",
        "assumptions": "直近N打の相関を集計しています。因果関係を示すものではありません。",
        "promotion_criteria": "N≥200ラリー・複数大会にわたる安定性の確認",
    },
    "first_return": {
        "evidence_level": "practical_candidate",
        "caution": "ショット種別の粒度はアノテーション入力精度に依存します。",
        "assumptions": None,
        "promotion_criteria": "N≥150ラリーの安定確認",
    },
    "set_summary": {
        "evidence_level": "practical_adopted",
        "caution": None,
        "assumptions": None,
        "promotion_criteria": None,
    },

    # ── advanced tier ─────────────────────────────────────────────────────────
    "pressure": {
        "evidence_level": "practical_candidate",
        "caution": "プレッシャー定義（スコア閾値）は固定値です。実際の心理的プレッシャーとは異なる場合があります。",
        "assumptions": "スコア17点以上・3点差以上を「プレッシャー局面」とします。",
        "promotion_criteria": "N≥300試合・プレッシャー定義の校正",
    },
    "transition": {
        "evidence_level": "practical_candidate",
        "caution": "遷移確率はサンプル不足で不安定になる可能性があります。",
        "assumptions": "1次マルコフ過程を仮定（前のショットのみ参照）。",
        "promotion_criteria": "N≥500ショット・クロス大会検証",
    },
    "temporal": {
        "evidence_level": "directional",
        "caution": "セット内時間帯の効果量は小さい場合があります。過度な解釈を避けてください。",
        "assumptions": "セット内ラリー順番を時間代理として使用。実際の時間は不使用。",
        "promotion_criteria": "N≥300ラリー・大会レベル別再現性確認",
    },
    "post_long_rally": {
        "evidence_level": "directional",
        "caution": "ロングラリー後効果のサンプルは少なくなりがちです。",
        "assumptions": "ラリー長8+打を「ロングラリー」と定義。",
        "promotion_criteria": "N≥100ロングラリーの安定確認",
    },
    "growth": {
        "evidence_level": "practical_candidate",
        "caution": "成長判定は過去試合の比較です。コンディション・対戦相手の変化を反映しません。",
        "assumptions": "時系列を試合日付順として扱います。同日複数試合は平均化されます。",
        "promotion_criteria": "N≥8試合・季節性コントロールの検討",
    },
    "doubles_tactical": {
        "evidence_level": "directional",
        "caution": "ダブルス分析はダブルス試合のみが対象です。シングルスデータは含みません。",
        "assumptions": "ローテーション判定はラリー構造から推定します。",
        "promotion_criteria": "N≥50ダブルス試合・ポジション精度検証",
    },
    "markov": {
        "evidence_level": "directional",
        "caution": "マルコフモデルは定常性を仮定します。実際の戦術変化は反映されません。",
        "assumptions": "1次マルコフ過程。状態はスコア差・ラリーフェーズ・モメンタムの3次元。",
        "promotion_criteria": "校正品質（Brier score）の改善・N≥500ラリー",
    },

    # ── research tier ─────────────────────────────────────────────────────────
    "counterfactual": {
        "evidence_level": "exploratory",
        "caution": "反事実的比較は仮説的シナリオです。実際に選択されなかった行動の価値は直接観測できません。",
        "assumptions": "文脈一致（前のショット種別・スコア圧力・ラリーフェーズ）による比較。交絡制御は行っていません。",
        "promotion_criteria": "傾向スコアによる交絡制御・ブートストラップCI導入・N≥500コンテキスト一致",
    },
    "recommendation": {
        "evidence_level": "directional",
        "caution": "推奨スコアはパターン頻度に基づきます。因果的な有効性を保証するものではありません。",
        "assumptions": "観測された高頻度・高勝率パターンを正の推奨として扱います。",
        "promotion_criteria": "前向き検証・選手フィードバックによる有用性確認",
    },
    "opponent_affinity": {
        "evidence_level": "exploratory",
        "caution": "対戦相手タイプ分類は統計的クラスタリングです。個別の選手特性を正確に反映しない場合があります。",
        "assumptions": "スタイルラベル（攻撃型/守備型等）はルールベースで割り当てています。",
        "promotion_criteria": "分類器の精度検証・外部ラベルとの照合",
    },
    "pair_synergy": {
        "evidence_level": "exploratory",
        "caution": "ペアシナジースコアはパフォーマンス差から推定します。ポジション役割は考慮されていません。",
        "assumptions": "ダブルス試合での個人成績差を「ペア効果」として推定します。",
        "promotion_criteria": "ロール推定精度の向上・N≥30ペア試合",
    },
    "epv": {
        "evidence_level": "directional",
        "caution": "EPVはマルコフモデルに基づく探索的指標です。定常性仮定・独立ラリー仮定を含みます。",
        "assumptions": "定常1次マルコフ過程。各ラリーは独立と仮定。",
        "promotion_criteria": "校正品質改善・状態定義の安定化・N≥500ラリー",
    },
    "shot_influence": {
        "evidence_level": "exploratory",
        "caution": "ショット影響度は因果効果ではなく相関ベースのヒューリスティックです。",
        "assumptions": "ラリー内ポジション・攻撃重み・勝敗の積として影響度を定義します。",
        "promotion_criteria": "状態条件付き推定・BootstrapCIの導入",
    },
    "spatial_density": {
        "evidence_level": "exploratory",
        "caution": "空間密度マップは打点・着地点の可視化です。統計的有意性検定は行っていません。",
        "assumptions": "ゾーン区分はコート9分割（3x3）を使用します。",
        "promotion_criteria": "有意差検定（χ²等）の導入・解像度向上",
    },
    # research spine
    "epv_state": {
        "evidence_level": "directional",
        "caution": "状態ベースEPVは状態定義の品質に強く依存します。状態数が少ない場合、推定が不安定になります。",
        "assumptions": "スコアフェーズ・セット番号・ラリーバケット・サーブ側の4次元状態を使用します。",
        "promotion_criteria": "状態ごとN≥50・CI幅0.2以内・クロス大会安定性",
    },
    "state_action": {
        "evidence_level": "exploratory",
        "caution": "状態-行動価値（Q値）はサンプル不足で高分散になります。少サンプル時はCI幅が広くなります。",
        "assumptions": "行動＝ショット種別。即時報酬＝ラリー勝率とします（将来割引なし）。",
        "promotion_criteria": "状態×行動ごとN≥30・信頼区間幅0.3以内",
    },
    "hazard_fatigue": {
        "evidence_level": "exploratory",
        "caution": "ハザード推定はラリー結果の時系列パターンから計算します。実際の疲労と一致しない場合があります。",
        "assumptions": "Cox比例ハザードを簡略化した離散ハザードを使用します。実際の体力測定は使用しません。",
        "promotion_criteria": "生理指標との相関確認・N≥500ラリーの安定確認",
    },
    "counterfactual_v2": {
        "evidence_level": "exploratory",
        "caution": "CF-1フェーズ: ブートストラップCIによる不確実性推定を含みます。傾向スコア制御はまだ未実装です。",
        "assumptions": "文脈一致（多次元）でのブートストラップCI。重複サポート閾値あり。",
        "promotion_criteria": "傾向スコア重み付け（CF-2）・N≥500コンテキスト・対戦相手条件付き（CF-3）",
    },
    "bayes_matchup": {
        "evidence_level": "exploratory",
        "caution": "経験的ベイズは事前分布をデータから推定します。データ不足時は強く事前に引っ張られます。",
        "assumptions": "Beta-Binomial モデルによる対戦勝率の縮小推定。利き手・フォーマット情報は考慮します。",
        "promotion_criteria": "ブリアスコア改善・N≥50試合・外部検証",
    },
    "opponent_policy": {
        "evidence_level": "exploratory",
        "caution": "対戦相手ポリシーは観測されたショット選択の統計です。意図的な戦術変化は反映しません。",
        "assumptions": "多軸（スコア・ラリーフェーズ・ゾーン）条件付きショット分布を使用します。",
        "promotion_criteria": "予測精度（交差検証）・N≥100対戦試合",
    },
    "doubles_role": {
        "evidence_level": "exploratory",
        "caution": "ロール推定（前衛/後衛）はラリー構造のルールベース分類です。実際のポジションとは異なる場合があります。",
        "assumptions": "ショット種別・順番から前衛/後衛ロールをルールで判定します。HMMは未実装です。",
        "promotion_criteria": "トラッキングデータとの照合・HMM移行（DB-2）",
    },
}


def get_evidence_meta(analysis_type: str) -> dict:
    """analysis_type の evidence メタを返す。未知の場合は exploratory を返す。"""
    return EVIDENCE_META.get(analysis_type, {
        "evidence_level": "exploratory",
        "caution": "このモジュールは研究段階です。",
        "assumptions": None,
        "promotion_criteria": None,
    })
