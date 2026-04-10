/**
 * CVCandidateBadge — CV補助状態を示すバッジコンポーネント
 *
 * 表示パターン:
 *   auto_filled    → 緑「自動入力」
 *   suggested      → 青「候補」
 *   review_required → 黄「要確認」
 */
import { clsx } from 'clsx'
import type { CVDecisionMode } from '@/types/cv'

interface Props {
  mode: CVDecisionMode
  className?: string
  /** 小さいサイズで表示する（デフォルト false） */
  compact?: boolean
}

const CONFIG: Record<CVDecisionMode, { label: string; cls: string }> = {
  auto_filled: {
    label: '自動入力',
    cls: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40',
  },
  suggested: {
    label: '候補',
    cls: 'bg-blue-500/20 text-blue-300 border border-blue-500/40',
  },
  review_required: {
    label: '要確認',
    cls: 'bg-amber-500/20 text-amber-300 border border-amber-500/40',
  },
}

export function CVCandidateBadge({ mode, className, compact = false }: Props) {
  const { label, cls } = CONFIG[mode]
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded font-medium leading-none',
        compact ? 'text-[9px] px-1 py-0.5' : 'text-[10px] px-1.5 py-0.5',
        cls,
        className
      )}
    >
      {label}
    </span>
  )
}
