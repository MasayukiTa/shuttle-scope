"""ベイズリアルタイム解析エンジン"""
import math
from typing import Any

from sqlalchemy.orm import Session


class BayesianRealTimeAnalyzer:
    """ベイズ推定を用いたリアルタイム試合解析クラス"""

    def compute_prior(
        self,
        player_id: int,
        opponent_id: int | None = None,
        db: Session | None = None,
        exclude_match_id: int | None = None,
    ) -> dict[str, float]:
        """過去データからBeta分布のprior(alpha, beta)を計算する

        過去の勝率に基づきBeta分布のパラメータを推定する。
        データがない場合は無情報事前分布 (alpha=1, beta=1) を返す。

        analysis #3 fix: 旧コードは exclude_match_id を受けず、generate_interval_report
        が現在の match_id を除外せずに prior を取り、その上に同じ set_rallies で
        posterior 更新するため二重計上になっていた。posterior mean は対称なら不変
        だが CI が不当に狭まり「セット間速報」の確信度が過大に出ていた。
        opponent_id も docstring にあるのに未使用だった。
        """
        if db is None:
            return {"alpha": 1.0, "beta": 1.0}

        try:
            from backend.db.models import Match, GameSet, Rally

            # 過去の全ラリー勝敗を取得 (現在 match を除外、opponent 指定があれば絞り込む)
            q = db.query(Match).filter(
                (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
            )
            if exclude_match_id is not None:
                q = q.filter(Match.id != exclude_match_id)
            if opponent_id is not None:
                q = q.filter(
                    (Match.player_a_id == opponent_id) | (Match.player_b_id == opponent_id)
                )
            matches = q.all()
            if not matches:
                return {"alpha": 1.0, "beta": 1.0}

            match_ids = [m.id for m in matches]
            role_by_match = {
                m.id: ("player_a" if m.player_a_id == player_id else "player_b")
                for m in matches
            }

            sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
            set_to_match = {s.id: s.match_id for s in sets}
            set_ids = [s.id for s in sets]

            rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

            wins = 0
            total = len(rallies)
            for rally in rallies:
                match_id = set_to_match[rally.set_id]
                role = role_by_match[match_id]
                if rally.winner == role:
                    wins += 1

            # Jeffrey's prior: alpha = wins + 0.5, beta = losses + 0.5
            losses = total - wins
            return {
                "alpha": float(wins) + 0.5,
                "beta": float(losses) + 0.5,
            }
        except Exception:
            return {"alpha": 1.0, "beta": 1.0}

    def update_posterior(
        self,
        prior_alpha: float,
        prior_beta: float,
        wins: int,
        total: int,
    ) -> dict[str, float]:
        """現在のセットデータでBeta分布のposteriorを更新する

        Beta-Binomial共役更新: alpha_post = alpha + wins, beta_post = beta + losses
        """
        losses = total - wins
        posterior_alpha = prior_alpha + wins
        posterior_beta = prior_beta + losses
        return {"alpha": posterior_alpha, "beta": posterior_beta}

    def posterior_mean_and_ci(
        self,
        alpha: float,
        beta: float,
    ) -> dict[str, float]:
        """Beta分布の事後平均値と95%信頼区間を計算する

        Beta(alpha, beta)の平均 = alpha / (alpha + beta)
        95%信頼区間にはBeta分布の累積分布関数の逆関数を使用する。
        """
        mean = alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5

        # scipy が利用可能なら正確なCI、そうでなければ正規近似を使用
        try:
            from scipy.stats import beta as beta_dist
            ci_low = float(beta_dist.ppf(0.025, alpha, beta))
            ci_high = float(beta_dist.ppf(0.975, alpha, beta))
        except ImportError:
            # 正規近似によるCI
            std = math.sqrt(alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1)))
            ci_low = max(0.0, mean - 1.96 * std)
            ci_high = min(1.0, mean + 1.96 * std)

        return {
            "mean": round(mean, 4),
            "ci_low": round(ci_low, 4),
            "ci_high": round(ci_high, 4),
        }

    def generate_interval_report(
        self,
        match_id: int,
        completed_set_num: int,
        db: Session,
    ) -> dict[str, Any]:
        """セット間の速報レポートを生成する

        完了したセット数に基づき、ベイズ更新された現在の勝率推定を生成する。
        """
        try:
            from backend.db.models import Match, GameSet, Rally

            match = db.get(Match, match_id)
            if not match:
                return {"success": False, "error": f"試合ID {match_id} が見つかりません"}

            player_id = match.player_a_id
            role = "player_a"

            # 完了済みセットを取得
            completed_sets = (
                db.query(GameSet)
                .filter(
                    GameSet.match_id == match_id,
                    GameSet.set_num <= completed_set_num,
                )
                .order_by(GameSet.set_num)
                .all()
            )

            if not completed_sets:
                return {
                    "success": True,
                    "data": {
                        "match_id": match_id,
                        "completed_set_num": completed_set_num,
                        "sets": [],
                        "current_win_estimate": None,
                    },
                }

            # prior を計算 (analysis #3 fix: 当該 match を除外して二重計上を防ぐ。
            # opponent も渡して相手特化の baseline を使う)
            opponent_id = match.player_b_id if role == "player_a" else match.player_a_id
            prior = self.compute_prior(
                player_id,
                opponent_id=opponent_id,
                db=db,
                exclude_match_id=match_id,
            )

            # 完了セットごとにベイズ更新
            set_reports = []
            running_alpha = prior["alpha"]
            running_beta = prior["beta"]

            set_ids = [s.id for s in completed_sets]
            rallies_all = (
                db.query(Rally)
                .filter(Rally.set_id.in_(set_ids))
                .order_by(Rally.set_id, Rally.rally_num)
                .all()
            )

            rallies_by_set: dict[int, list] = {}
            for rally in rallies_all:
                if rally.set_id not in rallies_by_set:
                    rallies_by_set[rally.set_id] = []
                rallies_by_set[rally.set_id].append(rally)

            for game_set in completed_sets:
                set_rallies = rallies_by_set.get(game_set.id, [])
                wins_in_set = sum(1 for r in set_rallies if r.winner == role)
                total_in_set = len(set_rallies)

                # posterior更新
                posterior = self.update_posterior(
                    running_alpha, running_beta, wins_in_set, total_in_set
                )
                running_alpha = posterior["alpha"]
                running_beta = posterior["beta"]

                ci = self.posterior_mean_and_ci(running_alpha, running_beta)

                set_reports.append({
                    "set_num": game_set.set_num,
                    "rally_count": total_in_set,
                    "wins": wins_in_set,
                    "win_rate_raw": round(wins_in_set / total_in_set, 3) if total_in_set else 0.0,
                    "posterior_mean": ci["mean"],
                    "ci_low": ci["ci_low"],
                    "ci_high": ci["ci_high"],
                })

            # 最終推定値
            current_ci = self.posterior_mean_and_ci(running_alpha, running_beta)

            return {
                "success": True,
                "data": {
                    "match_id": match_id,
                    "completed_set_num": completed_set_num,
                    "sets": set_reports,
                    "current_win_estimate": current_ci,
                    "prior": {"alpha": round(prior["alpha"], 2), "beta": round(prior["beta"], 2)},
                },
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
