import { useCallback } from 'react'
import { useAnnotationStore } from '@/store/annotationStore'
import { apiPost } from '@/api/client'

/**
 * アノテーション保存フック
 * ラリー確定時にAPIへバッチ保存する
 */
export function useAnnotation(matchId: number | null, setId: number | null) {
  const store = useAnnotationStore()

  const saveRally = useCallback(
    async (winner: 'player_a' | 'player_b', endType: string) => {
      if (!setId) throw new Error('セットIDが未設定です')

      const strokes = store.confirmRally(winner, endType)
      const { currentRallyNum: rallyNum, scoreA, scoreB } = store

      // ラリー確定前のラリー番号（confirmRallyで+1されているため-1）
      const savedRallyNum = rallyNum - 1

      const body = {
        rally: {
          set_id: setId,
          rally_num: savedRallyNum,
          server: 'player_a',  // TODO: サーバー管理
          winner,
          end_type: endType,
          rally_length: strokes.length,
          score_a_after: winner === 'player_a' ? scoreA : scoreA - 0,
          score_b_after: winner === 'player_b' ? scoreB : scoreB - 0,
          is_deuce: false,
        },
        strokes: strokes.map((s) => ({
          stroke_num: s.stroke_num,
          player: s.player,
          shot_type: s.shot_type,
          hit_zone: s.hit_zone,
          land_zone: s.land_zone,
          is_backhand: s.is_backhand,
          is_around_head: s.is_around_head,
          above_net: s.above_net,
          timestamp_sec: s.timestamp_sec,
        })),
      }

      return apiPost('/strokes/batch', body)
    },
    [store, setId]
  )

  return { saveRally }
}
