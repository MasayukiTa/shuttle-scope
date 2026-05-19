// 研究ページ用の注意バナーコンポーネント
//
// Design Language v1.2 §12 改訂:
//   - 旧版は bg-amber-50 / bg-amber-950 等の色付き bg を持っており、
//     ダークモードで見ても「明るい色のバー」が浮いて見える原因だった。
//   - 新版: bg は常に N_GRAY (theme に追従)、warning の意味は **左罫線でなく**
//     amber 色の **タイトル文字 + ⚠ アイコン** で示す。
//     左罫線 縦バー方式は禁止 (詐欺サイト感)。
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

  // bg / border は完全に N_GRAY (theme 連動)。
  // warning 意味は タイトル文字色 (amber) で運ぶ。
  const containerClass = isLight
    ? 'bg-white border border-gray-200'
    : 'bg-gray-800 border border-gray-700'
  const headingColor = isLight ? '#b45309' /* amber-700 */ : '#fbbf24' /* amber-400 */
  const cautionColor = isLight ? '#374151' /* gray-700 */ : '#e2e8f0' /* gray-200 */
  const subColor = isLight ? '#64748b' /* gray-500 */ : '#94a3b8' /* gray-400 */
  const faintColor = isLight ? '#94a3b8' /* gray-400 */ : '#64748b' /* gray-500 */

  return (
    <div className={`rounded-lg px-4 py-3 space-y-1 ${containerClass} ${className}`}>
      <p className="text-[11px] font-semibold flex items-center gap-1" style={{ color: headingColor }}>
        ⚠ 研究段階の分析
      </p>
      <p className="text-[11px]" style={{ color: cautionColor }}>{caution}</p>
      {assumptions && (
        <p className="text-[10px]" style={{ color: subColor }}>前提: {assumptions}</p>
      )}
      {reason && (
        <p className="text-[10px]" style={{ color: faintColor }}>探索的理由: {reason}</p>
      )}
      {promotionCriteria && (
        <p className="text-[10px]" style={{ color: faintColor }}>実用移行条件: {promotionCriteria}</p>
      )}
    </div>
  )
}
