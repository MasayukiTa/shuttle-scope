/**
 * /strokes/batch リクエストボディの組み立て。
 *
 * AnnotatorPage の保存経路から純関数として切り出している。
 * 目的:
 *   - Phase A (CV 推定の override トラッキング) と
 *     G2 (移動系エンリッチメント) と
 *     annotation_mode / source_method (基本/詳細) を
 *     取りこぼさず DB まで届けることをユニットテストで担保する。
 *   - 過去に dead な hooks/useAnnotation.ts が古い不完全 payload を持っており
 *     誤って import されると Phase A/G2 を黙って捨てる罠があった。
 *     payload 構築が増えるたびにここを更新し、コール側はそれを使うこと。
 */
import type { StrokeInput } from '@/types'

export interface BuildBatchPayloadArgs {
  setId: number
  rallyNum: number
  winner: 'player_a' | 'player_b'
  endType: string
  strokes: StrokeInput[]
  scoreAAfter: number
  scoreBAfter: number
  rallyStartTimestamp: number | null
  /** true = 基本 (manual_record / manual)、false = 詳細 (assisted_record / assisted) */
  isBasicMode: boolean
}

export interface BatchStrokePayload {
  stroke_num: number
  player: string
  shot_type: string
  hit_zone?: string | number
  hit_zone_source?: 'cv' | 'manual'
  hit_zone_cv_original?: string | number | null
  land_zone?: string
  is_backhand: boolean
  is_around_head: boolean
  above_net?: boolean
  timestamp_sec?: number
  return_quality?: string
  contact_height?: string
  contact_zone?: string
  movement_burden?: string
  movement_direction?: string
  source_method: 'manual' | 'assisted'
}

export interface BatchRallyPayload {
  set_id: number
  rally_num: number
  server: string
  winner: 'player_a' | 'player_b'
  end_type: string
  rally_length: number
  score_a_after: number
  score_b_after: number
  is_deuce: boolean
  video_timestamp_start?: number
  annotation_mode: 'manual_record' | 'assisted_record'
}

export interface BatchPayload {
  rally: BatchRallyPayload
  strokes: BatchStrokePayload[]
}

// ─── スキップラリー / スコア補正用バリアント ─────────────────────────────────
//
// スキップラリー (見逃し / スコア補正 / セット強制終了) は strokes = []、
// rally_length = 0、is_skipped = true で保存する。従来は AnnotatorPage 内に
// インラインで 3 箇所同一の payload を組み立てており、annotation_mode などの
// 新フィールドを足したいときに 3 つ揃えて修正する必要があった。
//
// fine-tune データセット作成 / 性能評価の用途:
//   - skipped を分離できると「実際にアノテートされたラリー数」が正しく算出できる
//   - annotation_mode (basic / detailed) が一貫して保存されるため
//     人手のラベル品質を mode 別に評価可能
//   - source_method はストローク側の概念なので skipped では不要

export interface BuildSkippedRallyPayloadArgs {
  setId: number
  rallyNum: number
  server: 'player_a' | 'player_b'
  winner: 'player_a' | 'player_b'
  scoreAAfter: number
  scoreBAfter: number
  isBasicMode: boolean
}

export function buildSkippedRallyPayload(args: BuildSkippedRallyPayloadArgs): BatchPayload {
  const {
    setId,
    rallyNum,
    server,
    winner,
    scoreAAfter,
    scoreBAfter,
    isBasicMode,
  } = args
  return {
    rally: {
      set_id: setId,
      rally_num: rallyNum,
      server,
      winner,
      end_type: 'skipped',
      rally_length: 0,
      score_a_after: scoreAAfter,
      score_b_after: scoreBAfter,
      is_deuce: scoreAAfter >= 20 && scoreBAfter >= 20,
      annotation_mode: isBasicMode ? 'manual_record' : 'assisted_record',
      // is_skipped はバックエンド側で受理する追加フィールド
      is_skipped: true,
    } as BatchRallyPayload & { is_skipped: true },
    strokes: [],
  }
}

export function buildBatchPayload(args: BuildBatchPayloadArgs): BatchPayload {
  const {
    setId,
    rallyNum,
    winner,
    endType,
    strokes,
    scoreAAfter,
    scoreBAfter,
    rallyStartTimestamp,
    isBasicMode,
  } = args

  return {
    rally: {
      set_id: setId,
      rally_num: rallyNum,
      server: strokes[0]?.player ?? 'player_a',
      winner,
      end_type: endType,
      rally_length: strokes.length,
      score_a_after: scoreAAfter,
      score_b_after: scoreBAfter,
      is_deuce: scoreAAfter >= 20 && scoreBAfter >= 20,
      video_timestamp_start: rallyStartTimestamp ?? undefined,
      annotation_mode: isBasicMode ? 'manual_record' : 'assisted_record',
    },
    strokes: strokes.map((st) => ({
      stroke_num: st.stroke_num,
      player: st.player,
      shot_type: st.shot_type,
      hit_zone: st.hit_zone,
      // Phase A: 打点ソース + CV 元値
      hit_zone_source: st.hit_zone_source,
      hit_zone_cv_original: st.hit_zone_cv_original,
      land_zone: st.land_zone,
      is_backhand: st.is_backhand,
      is_around_head: st.is_around_head,
      above_net: st.above_net,
      timestamp_sec: st.timestamp_sec,
      // G2+ 移動系: オプションエンリッチメント
      return_quality: st.return_quality,
      contact_height: st.contact_height,
      contact_zone: st.contact_zone,
      movement_burden: st.movement_burden,
      movement_direction: st.movement_direction,
      source_method: isBasicMode ? 'manual' : 'assisted',
    })),
  }
}
