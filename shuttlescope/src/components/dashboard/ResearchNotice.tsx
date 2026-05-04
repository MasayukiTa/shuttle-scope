// 研究ページ用の注意バナーコンポーネント
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface ResearchNoticeProps {
  assumptions?: string
  caution: string
  reason?: string
  promotionCriteria?: string
  className?: string
}

export function ResearchNotice({
  assumptions,
  caution,
  reason,
  promotionCriteria,
  className = '',
}: ResearchNoticeProps) {
  const isLight = useIsLightMode()

  const containerClass = isLight
    ? 'bg-amber-50 border border-amber-200'
    : 'bg-amber-950/40 border border-amber-700/50'
  const headingClass = isLight ? 'text-amber-700' : 'text-amber-400'
  const cautionClass = isLight ? 'text-amber-800' : 'text-amber-200/80'
  const subClass = isLight ? 'text-gray-600' : 'text-gray-400'
  const faintClass = isLight ? 'text-gray-500' : 'text-gray-500'

  return (
    <div className={`rounded-lg px-4 py-3 space-y-1 ${containerClass} ${className}`}>
      <p className={`text-[11px] font-semibold flex items-center gap-1 ${headingClass}`}>
        ⚠ 研究段階の分析
      </p>
      <p className={`text-[11px] ${cautionClass}`}>{caution}</p>
      {assumptions && (
        <p className={`text-[10px] ${subClass}`}>前提: {assumptions}</p>
      )}
      {reason && (
        <p className={`text-[10px] ${faintClass}`}>探索的理由: {reason}</p>
      )}
      {promotionCriteria && (
        <p className={`text-[10px] ${faintClass}`}>実用移行条件: {promotionCriteria}</p>
      )}
    </div>
  )
}
