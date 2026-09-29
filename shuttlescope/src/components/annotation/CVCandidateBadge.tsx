/**
 * CVCandidateBadge — CV補助状態を示すバッジコンポーネント
 *
 * 表示パターン:
 *   auto_filled    → 緑「自動入力」
 *   suggested      → 青「候補」
 *   review_required → 黄「要確認」
 */
import { clsx } from 'clsx'
import { useTranslation } from 'react-i18next'
import type { CVDecisionMode } from '@/types/cv'

interface Props {
  mode: CVDecisionMode
  className?: string
  /** 小さいサイズで表示する（デフォルト false） */
  compact?: boolean
}

// label は i18n キー (cv_assist.decision_*) で保持し component 内で t() 解決する。
// module-scope で t() を呼ぶと本番 minified バンドルがクラッシュするため CONFIG には
// 文字列キーのみを置く。
const CONFIG: Record<CVDecisionMode, { labelKey: string; cls: string }> = {
  auto_filled: {
    labelKey: 'cv_assist.decision_auto_filled',
    cls: 'bg-[var(--ss-success-tint)] text-[var(--ss-success)] border border-[var(--ss-success-border)]',
  },
  suggested: {
    labelKey: 'cv_assist.decision_suggested',
    cls: 'bg-[var(--ss-brand-tint)] text-[var(--ss-brand)] border border-[var(--ss-brand-border)]',
  },
  review_required: {
    labelKey: 'cv_assist.decision_review_required',
    cls: 'bg-[var(--ss-warn-tint)] text-[var(--ss-warn)] border border-[var(--ss-warning-border)]',
  },
}

export function CVCandidateBadge({ mode, className, compact = false }: Props) {
  const { t } = useTranslation()
  const { labelKey, cls } = CONFIG[mode]
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-ss-sm font-medium leading-none',
        compact ? 'text-[9px] px-1 py-0.5' : 'text-[10px] px-1.5 py-0.5',
        cls,
        className
      )}
    >
      {t(labelKey)}
    </span>
  )
}
