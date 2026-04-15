import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ConditionType, QuestionMaster, QuestionItem, ScaleKind, FactorKey } from '@/hooks/useConditions'

// Phase 2: 質問票マスター取得
// GET /api/conditions/master?condition_type=weekly|pre_match
// backend 未稼働時のフォールバック: weekly=F1-01..F5-08+V-01..V-04, pre_match=P-01..P-10
// 各問いの語尾/内容に合わせて scale を個別指定する（ja.json 側の質問文と整合）。
const WEEKLY_SCALE_MAP: Record<string, { factor: QuestionItem['factor']; scale: ScaleKind }> = {
  // F1 身体的疲労・回復: 事象/感覚の頻度が主、F1-04/05 は肯定状態なので agreement
  'F1-01': { factor: 'F1', scale: 'frequency' },
  'F1-02': { factor: 'F1', scale: 'frequency' },
  'F1-03': { factor: 'F1', scale: 'frequency' },
  'F1-04': { factor: 'F1', scale: 'agreement' },
  'F1-05': { factor: 'F1', scale: 'agreement' },
  'F1-06': { factor: 'F1', scale: 'frequency' },
  'F1-07': { factor: 'F1', scale: 'frequency' },
  'F1-08': { factor: 'F1', scale: 'frequency' },
  // F2 睡眠・休養: 事象系は frequency、質の肯定文は agreement
  'F2-01': { factor: 'F2', scale: 'frequency' },
  'F2-02': { factor: 'F2', scale: 'frequency' },
  'F2-03': { factor: 'F2', scale: 'agreement' },
  'F2-04': { factor: 'F2', scale: 'agreement' },
  'F2-05': { factor: 'F2', scale: 'frequency' },
  'F2-06': { factor: 'F2', scale: 'agreement' },
  'F2-07': { factor: 'F2', scale: 'agreement' },
  'F2-08': { factor: 'F2', scale: 'agreement' },
  // F3 心理: 否定事象は frequency、肯定状態は agreement
  'F3-01': { factor: 'F3', scale: 'frequency' },
  'F3-02': { factor: 'F3', scale: 'frequency' },
  'F3-03': { factor: 'F3', scale: 'frequency' },
  'F3-04': { factor: 'F3', scale: 'agreement' },
  'F3-05': { factor: 'F3', scale: 'frequency' },
  'F3-06': { factor: 'F3', scale: 'frequency' },
  'F3-07': { factor: 'F3', scale: 'agreement' },
  'F3-08': { factor: 'F3', scale: 'frequency' },
  // F4 モチベーション・集中: すべて肯定文 → agreement
  'F4-01': { factor: 'F4', scale: 'agreement' },
  'F4-02': { factor: 'F4', scale: 'agreement' },
  'F4-03': { factor: 'F4', scale: 'agreement' },
  'F4-04': { factor: 'F4', scale: 'agreement' },
  'F4-05': { factor: 'F4', scale: 'agreement' },
  'F4-06': { factor: 'F4', scale: 'agreement' },
  'F4-07': { factor: 'F4', scale: 'agreement' },
  'F4-08': { factor: 'F4', scale: 'agreement' },
  // F5 身体機能: 動きの感覚系は function、その他肯定文は agreement
  'F5-01': { factor: 'F5', scale: 'function' },
  'F5-02': { factor: 'F5', scale: 'function' },
  'F5-03': { factor: 'F5', scale: 'agreement' },
  'F5-04': { factor: 'F5', scale: 'agreement' },
  'F5-05': { factor: 'F5', scale: 'agreement' },
  'F5-06': { factor: 'F5', scale: 'agreement' },
  'F5-07': { factor: 'F5', scale: 'agreement' },
  'F5-08': { factor: 'F5', scale: 'agreement' },
  // V 妥当性: 「〜した/してください」の同意形 → agreement
  'V-01': { factor: 'V', scale: 'agreement' },
  'V-02': { factor: 'V', scale: 'agreement' },
  'V-03': { factor: 'V', scale: 'agreement' },
  'V-04': { factor: 'V', scale: 'agreement' },
}

function fallbackMaster(condition_type: ConditionType): QuestionMaster {
  if (condition_type === 'pre_match') {
    // P-01..P-10: すべて現在の状態を問う肯定文 → agreement
    const items: QuestionItem[] = Array.from({ length: 10 }, (_, i) => {
      const n = String(i + 1).padStart(2, '0')
      const id = `P-${n}`
      return {
        id,
        factor: 'F4' as FactorKey,
        text_key: `condition.q.${id}`,
        scale: 'agreement' as ScaleKind,
      }
    })
    return { items, auxiliary: [] }
  }
  const items: QuestionItem[] = Object.entries(WEEKLY_SCALE_MAP).map(([id, { factor, scale }]) => ({
    id,
    factor,
    text_key: `condition.q.${id}`,
    scale,
  }))
  return { items, auxiliary: [] }
}

export function useConditionMaster(condition_type: ConditionType) {
  return useQuery({
    queryKey: ['condition-master', condition_type],
    queryFn: async (): Promise<QuestionMaster> => {
      try {
        const resp = await apiGet<QuestionMaster | { success?: boolean; data?: QuestionMaster }>(
          '/conditions/master',
          { condition_type },
        )
        if (resp && typeof resp === 'object' && 'items' in resp) {
          return resp as QuestionMaster
        }
        const data = (resp as { data?: QuestionMaster }).data
        if (data && Array.isArray(data.items)) return data
        return fallbackMaster(condition_type)
      } catch {
        // backend 未稼働 / エラー時はフォールバック
        return fallbackMaster(condition_type)
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: 0,
  })
}
