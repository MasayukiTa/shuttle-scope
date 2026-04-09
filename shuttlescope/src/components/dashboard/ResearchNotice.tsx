// 研究ページ用の注意バナーコンポーネント
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
  return (
    <div className={`bg-amber-950/40 border border-amber-700/50 rounded-lg px-4 py-3 space-y-1 ${className}`}>
      <p className="text-[11px] font-semibold text-amber-400 flex items-center gap-1">
        ⚠ 研究段階の分析
      </p>
      <p className="text-[11px] text-amber-200/80">{caution}</p>
      {assumptions && (
        <p className="text-[10px] text-gray-400">前提: {assumptions}</p>
      )}
      {reason && (
        <p className="text-[10px] text-gray-500">探索的理由: {reason}</p>
      )}
      {promotionCriteria && (
        <p className="text-[10px] text-gray-500">実用移行条件: {promotionCriteria}</p>
      )}
    </div>
  )
}
