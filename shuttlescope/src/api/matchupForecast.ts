// 対戦予測（階層ベイズ）API クライアント
import { apiGet } from '@/api/client'

// ── 型定義 ──────────────────────────────────────────────────────────────────

export interface MatchupForecastEntry {
  opponent_id: number
  opponent_name: string
  /** 直接対戦試合数 */
  n_h2h: number
  /** 勝利予測確率 (0..1) */
  p_win: number
  ci_low: number
  ci_high: number
}

export interface MatchupForecastData {
  player_id: number
  /** 全体強度推定（CI 付き / null = データ不足） */
  strength: { value: number; ci_low: number; ci_high: number } | null
  matchups: MatchupForecastEntry[]
  n_players: number
  n_matches: number
}

export interface MatchupForecastMeta {
  sample_size: number
  confidence: Record<string, unknown>
  analysis_type: 'matchup_forecast'
  tier: string
  evidence_level: string
}

export interface MatchupForecastResponse {
  success: boolean
  data: MatchupForecastData
  meta: MatchupForecastMeta
}

// ── API 関数 ─────────────────────────────────────────────────────────────────

/**
 * 対戦予測（階層ベイズ）分析を取得する。
 *
 * @param playerId - 対象選手 ID
 */
export function fetchMatchupForecast(
  playerId: number,
): Promise<MatchupForecastResponse> {
  return apiGet<MatchupForecastResponse>('/analysis/matchup_forecast', {
    player_id: playerId,
  })
}
