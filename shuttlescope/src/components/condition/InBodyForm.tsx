import { useTranslation } from 'react-i18next'
import { ConditionPayload } from '@/hooks/useConditions'

// InBody 測定項目の入力フォーム。全て任意。
// 親コンポーネントが state を管理する制御コンポーネントとして実装。
type InBodyKey =
  | 'weight_kg'
  | 'muscle_mass_kg'
  | 'body_fat_pct'
  | 'body_fat_mass_kg'
  | 'lean_mass_kg'
  | 'ecw_ratio'
  | 'arm_l_muscle_kg'
  | 'arm_r_muscle_kg'
  | 'leg_l_muscle_kg'
  | 'leg_r_muscle_kg'
  | 'trunk_muscle_kg'
  | 'bmr_kcal'

const FIELDS: InBodyKey[] = [
  'weight_kg',
  'muscle_mass_kg',
  'body_fat_pct',
  'body_fat_mass_kg',
  'lean_mass_kg',
  'ecw_ratio',
  'arm_l_muscle_kg',
  'arm_r_muscle_kg',
  'leg_l_muscle_kg',
  'leg_r_muscle_kg',
  'trunk_muscle_kg',
  'bmr_kcal',
]

interface Props {
  value: Partial<ConditionPayload>
  onChange: (patch: Partial<ConditionPayload>) => void
  isLight?: boolean
}

export function InBodyForm({ value, onChange, isLight }: Props) {
  const { t } = useTranslation()
  const inputCls = 'w-full border border-[var(--ss-border-strong)] bg-[var(--ss-surface-1)] text-[var(--ss-t1)] rounded-ss-md px-2 py-1.5'
  const labelCls = 'text-xs text-[var(--ss-t2)]'

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
      {FIELDS.map((k) => {
        const v = value[k] as number | null | undefined
        return (
          <label key={k} className="flex flex-col gap-1">
            <span className={labelCls}>{t(`condition.inbody.${k}`)}</span>
            <input
              type="number"
              step="0.1"
              inputMode="decimal"
              className={inputCls}
              value={v ?? ''}
              onChange={(e) => {
                const raw = e.target.value
                onChange({ [k]: raw === '' ? null : Number(raw) } as Partial<ConditionPayload>)
              }}
            />
          </label>
        )
      })}
    </div>
  )
}
