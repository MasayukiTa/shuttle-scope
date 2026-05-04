import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { QuestionItem, ScaleKind } from '@/hooks/useConditions'

interface Props {
  items: QuestionItem[]
  responses: Record<string, number>
  onChange: (responses: Record<string, number>) => void
  isLight?: boolean
}

// 共通: 5 択ラジオで質問を縦並びレンダ。進捗表示は親側に委ねる。
export function QuestionnaireRunner({ items, responses, onChange, isLight }: Props) {
  const { t } = useTranslation()
  const panelCls = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'
  const labelMuted = isLight ? 'text-gray-600' : 'text-gray-400'

  const set = (id: string | number, v: number) => {
    onChange({ ...responses, [String(id)]: v })
  }

  return (
    <div className="space-y-3">
      {items.map((q) => {
        const key = String(q.id)
        const current = responses[key]
        const scaleName = t(`condition.scale.${q.scale}.name`)
        const factorLabel = q.factor === 'V' || q.factor === 'AUX' ? q.factor : t(`condition.factor.${q.factor}`)
        return (
          <div key={q.id} className={`border rounded-lg p-3 ${panelCls}`}>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-blue-600/20 text-blue-400 border border-blue-500/30">
                {q.factor}
              </span>
              <span className={`text-[10px] ${labelMuted}`}>{factorLabel}</span>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-purple-600/20 text-purple-400 border border-purple-500/30">
                {scaleName}
              </span>
            </div>
            <div className="text-sm mb-2">{t(q.text_key)}</div>
            <div className="grid grid-cols-5 gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => set(q.id, n)}
                  className={
                    'text-[11px] py-2 rounded border transition-colors ' +
                    (current === n
                      ? 'bg-blue-600 border-blue-600 text-white'
                      : isLight
                      ? 'bg-gray-50 border-gray-300 text-gray-700 hover:bg-gray-100'
                      : 'bg-gray-900 border-gray-600 text-gray-300 hover:bg-gray-700')
                  }
                  title={t(`condition.scale.${q.scale}.${n}` as unknown as string) as string}
                >
                  <div className="font-bold">{n}</div>
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
