// 簡易分析「打球の高さ差」API クライアント（要望8 / SD-08）
//
// 細かい分析（style_distance 等）とは別オプションの軽い «簡易分析»。
// バックエンドの /analysis/simple/height_diff を薄く呼ぶだけ。
import { apiGet } from '@/api/client'

/** 差が大きかったラリー 1 件（最大差の降順で並ぶ） */
export interface SimpleHeightDiffTopRally {
  /** ゲーム番号（1 始まり）。不明なら null */
  set_num: number | null
  /** ラリー番号（ゲーム内 1 始まり）。不明なら null */
  rally_num: number | null
  /** そのラリーの最大高さ差（0〜3） */
  max_diff: number
  /** そのラリーで測れた返球関係の組数 */
  pairs: number
}

export interface SimpleHeightDiffData {
  match_id: number
  /** 測れた返球関係（連続する別チームの 2 球で両方の高さが入力済み）の組数 */
  pairs: number
  /** 高さ差（0〜3）の平均。組が無ければ null */
  mean_diff: number | null
  /** 差の値ごとの件数 {"0":.., "1":.., "2":.., "3":..} */
  distribution: Record<string, number>
  /** 差が大きかったラリーの一覧（最大差の降順、上位数件）。無ければ空配列 */
  top_rallies: SimpleHeightDiffTopRally[]
}

export interface SimpleHeightDiffResponse {
  success: boolean
  data: SimpleHeightDiffData
  error?: string
}

/**
 * 試合全体の «打球の高さ差» の簡易集計を取得する。
 *
 * @param matchId - 対象試合 ID
 */
export function fetchSimpleHeightDiff(matchId: number): Promise<SimpleHeightDiffResponse> {
  return apiGet<SimpleHeightDiffResponse>('/analysis/simple/height_diff', {
    match_id: matchId,
  })
}
