import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPost, apiPut } from '@/api/client'

// ─── 型定義 ──────────────────────────────────────────────────────────────────
// 選手ごとの期間タグ（合宿 / 大会前 / ストレス期 など）。
// end_date=null は単発イベント（当日のみ）として扱う。
export interface ConditionTag {
  id: number
  player_id: number
  label: string
  start_date: string          // "YYYY-MM-DD"
  end_date?: string | null
  color: string               // "#RRGGBB"
  created_at?: string
}

export interface ConditionTagCreatePayload {
  player_id: number
  label: string
  start_date: string
  end_date?: string | null
  color?: string
}

export interface ConditionTagUpdatePayload {
  label?: string
  start_date?: string
  end_date?: string | null
  color?: string
}

interface ListResp { success?: boolean; data?: ConditionTag[] }
interface OneResp { success?: boolean; data?: ConditionTag }

// ─── GET list ────────────────────────────────────────────────────────────────
export function useConditionTags(playerId: number | null) {
  return useQuery({
    queryKey: ['condition_tags', playerId],
    queryFn: async () => {
      const resp = await apiGet<ListResp | ConditionTag[]>('/condition_tags', {
        player_id: playerId!,
      })
      if (Array.isArray(resp)) return resp
      return resp.data ?? []
    },
    enabled: !!playerId,
    retry: 0,
  })
}

// ─── POST create ─────────────────────────────────────────────────────────────
export function useCreateConditionTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ConditionTagCreatePayload) => {
      const resp = await apiPost<OneResp | ConditionTag>('/condition_tags', payload)
      if (resp && typeof resp === 'object' && 'data' in (resp as object)) {
        return (resp as OneResp).data!
      }
      return resp as ConditionTag
    },
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ['condition_tags', v.player_id] })
    },
  })
}

// ─── PUT update ──────────────────────────────────────────────────────────────
export function useUpdateConditionTag(playerId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (args: { id: number; payload: ConditionTagUpdatePayload }) => {
      const resp = await apiPut<OneResp | ConditionTag>(
        `/condition_tags/${args.id}`,
        args.payload,
      )
      if (resp && typeof resp === 'object' && 'data' in (resp as object)) {
        return (resp as OneResp).data!
      }
      return resp as ConditionTag
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['condition_tags', playerId] })
    },
  })
}

// ─── DELETE ──────────────────────────────────────────────────────────────────
export function useDeleteConditionTag(playerId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      await apiDelete<{ success?: boolean }>(`/condition_tags/${id}`)
      return id
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['condition_tags', playerId] })
    },
  })
}

// ─── 期間判定ユーティリティ ─────────────────────────────────────────────────
// measured_at がタグ期間内か。end_date=null は単発（start_date と同日のみ）。
export function isDateInTag(measuredAt: string, tag: ConditionTag): boolean {
  if (!measuredAt) return false
  const d = measuredAt.slice(0, 10)
  if (!tag.end_date) return d === tag.start_date
  return d >= tag.start_date && d <= tag.end_date
}
