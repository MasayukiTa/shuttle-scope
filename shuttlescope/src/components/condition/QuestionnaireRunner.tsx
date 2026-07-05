import { _useMemo, useRef, _useState } from 'react'
import { useTranslation } from 'react-i18next'
import { QuestionItem, ScaleKind } from '@/hooks/useConditions'
import { trackConditionInput } from '@/utils/analytics'

interface Props {
  items: QuestionItem[]
  responses: Record<string, number>
  onChange: (responses: Record<string, number>) => void
  isLight?: boolean
}

// 共通: 5 択ラジオで質問を縦並びレンダ。進捗表示は親側に委ねる。
export function QuestionnaireRunner({ items, responses, onChange, isLight }: Props) {
  const { t } = useTranslation()
  const panelCls = 'bg-[var(--ss-surface-1)] border-[var(--ss-border)]'
  const labelMuted = 'text-[var(--ss-t2)]'

  // 質問ごとに入力開始時刻と value 変更回数を保持 (テレメトリ用)
  const startedAtRef = useRef<Record<string, number>>({})
  const changeCountRef = useRef<Record<string, number>>({})

  const set = (id: string | number, v: number) => {
    const key = String(id)
    // 初回 tap: 開始時刻記録 / 既存: 変更回数 ++
    if (!startedAtRef.current[key]) {
      startedAtRef.current[key] = performance.now()
      changeCountRef.current[key] = 1
    } else {
      changeCountRef.current[key] = (changeCountRef.current[key] || 0) + 1
    }
    // テレメトリ送出 (PII なし: question_id + elapsed_ms + 変更回数のみ。値は送らない)
    try {
      trackConditionInput(
        key,
        Math.round(performance.now() - startedAtRef.current[key]),
        changeCountRef.current[key] || 1,
      )
    } catch { /* ignore */ }
    onChange({ ...responses, [key]: v })
  }

  return (
    <div className="space-y-3">
      {items.map((q) => {
        const key = String(q.id)
        const current = responses[key]
        const scaleName = t(`condition.scale.${q.scale}.name`)
        const factorLabel = q.factor === 'V' || q.factor === 'AUX' ? q.factor : t(`condition.factor.${q.factor}`)
        return (
          <div key={q.id} className={`border rounded-ss-lg p-3 ${panelCls}`}>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-ss-sm text-[10px] font-mono bg-[var(--ss-brand-tint)] text-[var(--ss-brand)] border border-[var(--ss-brand-border)]">
                {q.factor}
              </span>
              <span className={`text-[10px] ${labelMuted}`}>{factorLabel}</span>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-ss-sm text-[10px] bg-[var(--ss-surface-2)] text-[var(--ss-t2)] border border-[var(--ss-border-strong)]">
                {scaleName}
              </span>
            </div>
            <div className="text-sm mb-2 text-[var(--ss-t1)]">{t(q.text_key)}</div>
            <div className="grid grid-cols-5 gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => set(q.id, n)}
                  className={
                    'text-[11px] py-2 rounded-ss-md border transition-colors duration-fast ease-out ' +
                    (current === n
                      ? 'bg-[var(--ss-brand)] border-[var(--ss-brand)] text-white'
                      : 'bg-[var(--ss-surface-2)] border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]')
                  }
                  title={t(`condition.scale.${q.scale}.${n}` as unknown as string) as string}
                >
                  <div className="font-bold ss-num">{n}</div>
                  <div className="opacity-75 leading-tight line-clamp-2 px-1">
                    {t(`condition.scale.${q.scale}.${n}` as unknown as string)}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export type { ScaleKind }
