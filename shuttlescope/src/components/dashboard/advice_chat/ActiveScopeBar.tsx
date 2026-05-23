/**
 * ActiveScopeBar — 会話駆動スコープの "適用中のフィルタ" 表示。
 *
 * 各スロット (period / shot_type / zone) のチップを並べ、[✕] で個別クリア、
 * 「全部クリア」リンクで全スロットクリアを送信する (次メッセージで反映)。
 */
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

export interface AppliedScope {
  period: { date_from: string | null; date_to: string | null; label?: string } | null
  shot_type: { code: string; label?: string } | null
  zone: { code: string; label?: string } | null
}

interface Props {
  scope: AppliedScope | null
  /** スロット名 ("period" | "shot_type" | "zone") を受け取り、それを clearSlots に積むよう要求 */
  onClearSlot: (slot: 'period' | 'shot_type' | 'zone') => void
  onClearAll: () => void
}

export function ActiveScopeBar({ scope, onClearSlot, onClearAll }: Props) {
  const { t } = useTranslation()
  if (!scope) return null
  const hasAny =
    (scope.period && (scope.period.date_from || scope.period.date_to)) ||
    scope.shot_type ||
    scope.zone
  if (!hasAny) return null

  const periodLabel =
    scope.period
      ? scope.period.label ||
        `${scope.period.date_from ?? '…'} → ${scope.period.date_to ?? t('auto.AdviceChat.period.today')}`
      : null

  return (
    <div
      className="flex items-center flex-wrap gap-1.5 text-[11px] mb-1.5"
      aria-label={t('auto.AdviceChat.scope.bar.title')}
    >
      <span className="text-gray-600 dark:text-gray-300 font-medium">
        {t('auto.AdviceChat.scope.bar.title')}:
      </span>
      {scope.period && (scope.period.date_from || scope.period.date_to) && (
        <ScopeChip
          icon="event"
          label={periodLabel ?? ''}
          ariaLabel={t('auto.AdviceChat.scope.slot.period')}
          onClear={() => onClearSlot('period')}
        />
      )}
      {scope.shot_type && (
        <ScopeChip
          icon="sports_tennis"
          label={scope.shot_type.label || scope.shot_type.code}
          ariaLabel={t('auto.AdviceChat.scope.slot.shotType')}
          onClear={() => onClearSlot('shot_type')}
        />
      )}
      {scope.zone && (
        <ScopeChip
          icon="place"
          label={scope.zone.label || scope.zone.code}
          ariaLabel={t('auto.AdviceChat.scope.slot.zone')}
          onClear={() => onClearSlot('zone')}
        />
      )}
      <button
        type="button"
        onClick={onClearAll}
        className="text-indigo-700 dark:text-indigo-300 hover:underline ml-1"
      >
        {t('auto.AdviceChat.scope.clearAll')}
      </button>
    </div>
  )
}

function ScopeChip({
  icon,
  label,
  ariaLabel,
  onClear,
}: {
  icon: string
  label: string
  ariaLabel: string
  onClear: () => void
}) {
  return (
    <span
      className="inline-flex items-center gap-1 bg-indigo-50 dark:bg-indigo-900/40 border border-indigo-200 dark:border-indigo-700 text-indigo-900 dark:text-indigo-100 px-2 py-0.5 rounded-full"
      aria-label={ariaLabel}
    >
      <MIcon name={icon} size={12} ariaHidden className="text-indigo-700 dark:text-indigo-200" />
      <span>{label}</span>
      <button
        type="button"
        onClick={onClear}
        aria-label={`${ariaLabel} clear`}
        className="text-indigo-700 dark:text-indigo-200 hover:text-red-600"
      >
        <MIcon name="close" size={12} ariaHidden />
      </button>
    </span>
  )
}
