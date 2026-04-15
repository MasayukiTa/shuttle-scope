import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/api/client'

// ─── 型定義 ──────────────────────────────────────────────────────────────────
// backend /api/conditions の契約に合わせる。サーバが hooper_index と session_load を自動計算して返す。
export type ConditionType = 'weekly' | 'pre_match'
export type FactorKey = 'F1' | 'F2' | 'F3' | 'F4' | 'F5'
export type ScaleKind = 'frequency' | 'recovery' | 'function' | 'agreement' | 'absolute'
export type ResultLabel = 'good' | 'caution' | 'concern'

export interface QuestionItem {
  id: string
  factor: FactorKey | 'V' | 'AUX'
  text_key: string
  scale: ScaleKind
  reversed?: boolean
}

export interface AuxiliaryItem {
  id: number
  key: string
  text_key: string
  type: 'number' | 'text'
}

export interface QuestionMaster {
  items: QuestionItem[]
  auxiliary: AuxiliaryItem[]
}

export interface QuestionnairePayload {
  player_id: number
  measured_at: string
  condition_type: ConditionType
  responses: Record<string, number>
  match_id?: number | null
  auxiliary?: Record<string, number | string | null>
}

export interface FactorResult {
  factor: FactorKey
  label: ResultLabel
  z_score?: number | null
  raw?: number | null
}

export interface ConditionResult {
  id?: number
  player_id?: number
  measured_at?: string
  condition_type?: ConditionType
  ccs?: number | null
  personal_range_low?: number | null
  personal_range_high?: number | null
  delta_28ma?: number | null
  factors?: FactorResult[]
  // coach+
  f1?: number | null
  f2?: number | null
  f3?: number | null
  f4?: number | null
  f5?: number | null
  total_score?: number | null
  validity_flag?: boolean | null
  // analyst only
  validity_score?: number | null
  flags_list?: string[] | null
  questionnaire_json?: Record<string, number> | null
  history_count?: number | null
}

export interface ConditionPayload {
  player_id: number
  measured_at: string // "YYYY-MM-DD"
  condition_type: ConditionType
  // InBody
  weight_kg?: number | null
  muscle_mass_kg?: number | null
  body_fat_pct?: number | null
  body_fat_mass_kg?: number | null
  lean_mass_kg?: number | null
  ecw_ratio?: number | null
  arm_l_muscle_kg?: number | null
  arm_r_muscle_kg?: number | null
  leg_l_muscle_kg?: number | null
  leg_r_muscle_kg?: number | null
  trunk_muscle_kg?: number | null
  bmr_kcal?: number | null
  // Hooper / RPE
  hooper_sleep?: number | null
  hooper_soreness?: number | null
  hooper_stress?: number | null
  hooper_fatigue?: number | null
  session_rpe?: number | null
  session_duration_min?: number | null
  // 補助
  sleep_hours?: number | null
  injury_notes?: string | null
  general_comment?: string | null
}

export interface ConditionRecord extends ConditionPayload {
  id: number
  hooper_index?: number | null
  session_load?: number | null
  // 派生スコア (backend が質問票経由で算出、/conditions list から analyst/coach には返る)
  ccs?: number | null
  ccs_score?: number | null
  f1?: number | null
  f2?: number | null
  f3?: number | null
  f4?: number | null
  f5?: number | null
  f1_physical?: number | null
  f2_stress?: number | null
  f3_mood?: number | null
  f4_motivation?: number | null
  f5_sleep_life?: number | null
  total_score?: number | null
  validity_flag?: boolean | null
  validity_score?: number | null
  validity_flags_json?: string[] | string | null
  delta_prev?: number | null
  delta_3ma?: number | null
  delta_28ma?: number | null
  z_score?: number | null
  questionnaire_json?: Record<string, number> | string | null
  match_id?: number | null
  created_at?: string
  updated_at?: string
}

interface ConditionListResp {
  success?: boolean
  data?: ConditionRecord[]
}

interface ConditionResp {
  success?: boolean
  data?: ConditionRecord
}

// ─── GET list ────────────────────────────────────────────────────────────────
export function useConditions(
  playerId: number | null,
  opts?: { limit?: number; since?: string },
) {
  return useQuery({
    queryKey: ['conditions', playerId, opts?.limit, opts?.since],
    queryFn: async () => {
      const params: Record<string, string | number> = { player_id: playerId! }
      if (opts?.limit) params.limit = opts.limit
      if (opts?.since) params.since = opts.since
      const resp = await apiGet<ConditionListResp | ConditionRecord[]>(
        '/conditions',
        params,
      )
      // backend が { success, data } or 生 array のどちらでも吸収
      const rows = Array.isArray(resp) ? resp : (resp.data ?? [])
      // backend キー → フロント期待キーへの正規化
      // backend: ccs_score / f1_physical / f2_stress / f3_mood / f4_motivation / f5_sleep_life
      // frontend 既存コンポ: ccs / f1 / f2 / f3 / f4 / f5
      return rows.map((r) => {
        const rec = r as Record<string, unknown>
        return {
          ...(r as ConditionRecord),
          ccs: (rec.ccs ?? rec.ccs_score) as number | null | undefined,
          f1: (rec.f1 ?? rec.f1_physical) as number | null | undefined,
          f2: (rec.f2 ?? rec.f2_stress) as number | null | undefined,
          f3: (rec.f3 ?? rec.f3_mood) as number | null | undefined,
          f4: (rec.f4 ?? rec.f4_motivation) as number | null | undefined,
          f5: (rec.f5 ?? rec.f5_sleep_life) as number | null | undefined,
        } as ConditionRecord
      })
    },
    enabled: !!playerId,
    retry: 0,
  })
}

// ─── POST create ─────────────────────────────────────────────────────────────
export function useCreateCondition() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ConditionPayload) => {
      const resp = await apiPost<ConditionResp | ConditionRecord>(
        '/conditions',
        payload,
      )
      if ('data' in (resp as object)) return (resp as ConditionResp).data!
      return resp as ConditionRecord
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['conditions', variables.player_id] })
    },
  })
}

// ─── POST questionnaire (Phase 2) ───────────────────────────────────────────
export function useSubmitQuestionnaire() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: QuestionnairePayload) => {
      const resp = await apiPost<{ success?: boolean; data?: ConditionResult } | ConditionResult>(
        '/conditions/questionnaire',
        payload,
      )
      if (resp && typeof resp === 'object' && 'data' in (resp as object)) {
        return (resp as { data?: ConditionResult }).data ?? (resp as ConditionResult)
      }
      return resp as ConditionResult
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['conditions', variables.player_id] })
    },
  })
}
