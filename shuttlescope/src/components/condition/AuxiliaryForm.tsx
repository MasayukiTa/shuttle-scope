import { useTranslation } from 'react-i18next'
import { ConditionPayload } from '@/hooks/useConditions'

// 補助情報: 睡眠時間、けがメモ、自由記述。すべて任意。
interface Props {
  value: Partial<ConditionPayload>
  onChange: (patch: Partial<ConditionPayload>) => void
  isLight?: boolean
}

export function AuxiliaryForm({ value, onChange, isLight }: Props) {
  const { t } = useTranslation()
  const inputCls = isLight
    ? 'w-full border border-gray-300 bg-white text-gray-900 rounded px-2 py-1.5'
    : 'w-full border border-gray-600 bg-gray-800 text-white rounded px-2 py-1.5'
  const labelCls = isLight ? 'text-xs text-gray-600' : 'text-xs text-gray-400'

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className={labelCls}>{t('condition.aux.sleep_hours')}</span>
          <input
            type="number"
            step="0.1"
            min={0}
            max={24}
            inputMode="decimal"
            className={inputCls}
            value={value.sleep_hours ?? ''}
            onChange={(e) =>
              onChange({ sleep_hours: e.target.value === '' ? null : Number(e.target.value) })
            }
          />
        </label>
      </div>

      <label className="flex flex-col gap-1">
        <span className={labelCls}>{t('condition.aux.injury_notes')}</span>
        <textarea
          rows={2}
          className={inputCls}
          value={value.injury_notes ?? ''}
          onChange={(e) => onChange({ injury_notes: e.target.value || null })}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className={labelCls}>{t('condition.aux.general_comment')}</span>
        <textarea
          rows={3}
          className={inputCls}
          value={value.general_comment ?? ''}
          onChange={(e) => onChange({ general_comment: e.target.value || null })}
        />
      </label>
    </div>
  )
}
