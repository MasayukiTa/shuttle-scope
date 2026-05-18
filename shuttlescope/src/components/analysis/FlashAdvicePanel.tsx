// R-006: 速報パネル（flash_advice: 5〜7カード）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface FlashAdvicePanelProps {
  matchId: number
  asOfSet: number
  asOfRallyNum?: number
  playerId: number
}

interface AdviceItem {
  category: 'danger' | 'opportunity' | 'pattern' | 'opponent' | 'next_action' | 'trend' | 'fatigue_signal'
  title: string
  body: string
  priority: number
}

interface FlashAdviceResponse {
  success: boolean
  data: {
    items: AdviceItem[]
    item_count: number
    extended_items_included: boolean
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

// カテゴリ別スタイル定義
const CATEGORY_STYLE: Record<string, { border: string; bg: string; badge: string; lightBorder: string; lightBg: string }> = {
  danger:       { border: '#ef4444', bg: 'rgba(239,68,68,0.08)',   badge: '#ef4444', lightBorder: '#dc2626', lightBg: 'rgba(239,68,68,0.06)' },
  opportunity:  { border: '#3b82f6', bg: 'rgba(59,130,246,0.08)', badge: '#3b82f6', lightBorder: '#2563eb', lightBg: 'rgba(59,130,246,0.06)' },
  pattern:      { border: '#8b5cf6', bg: 'rgba(139,92,246,0.08)', badge: '#8b5cf6', lightBorder: '#7c3aed', lightBg: 'rgba(139,92,246,0.06)' },
  opponent:     { border: '#f59e0b', bg: 'rgba(245,158,11,0.08)', badge: '#f59e0b', lightBorder: '#d97706', lightBg: 'rgba(245,158,11,0.06)' },
  next_action:  { border: '#eab308', bg: 'rgba(234,179,8,0.10)',  badge: '#eab308', lightBorder: '#ca8a04', lightBg: 'rgba(234,179,8,0.08)' },
  trend:        { border: '#06b6d4', bg: 'rgba(6,182,212,0.08)',  badge: '#06b6d4', lightBorder: '#0891b2', lightBg: 'rgba(6,182,212,0.06)' },
  fatigue_signal: { border: '#ec4899', bg: 'rgba(236,72,153,0.08)', badge: '#ec4899', lightBorder: '#db2777', lightBg: 'rgba(236,72,153,0.06)' },
}

// playerロールに見せるカテゴリ（next_action + opportunity のみ）
const PLAYER_VISIBLE_CATEGORIES = new Set(['next_action', 'opportunity'])

function AdviceCard({ item, isLight }: { item: AdviceItem; isLight: boolean }) {
  const style = CATEGORY_STYLE[item.category] ?? CATEGORY_STYLE.pattern
  const isNextAction = item.category === 'next_action'

  return (
    <div
      className="rounded-lg p-3 space-y-1"
      style={{
        border: `${isNextAction ? '2px' : '1.5px'} solid ${isLight ? style.lightBorder : style.border}`,
        backgroundColor: isLight ? style.lightBg : style.bg,
      }}
    >
      <div className="flex items-center gap-2">
        <span
          className="text-[10px] font-bold px-1.5 py-0.5 rounded"
          style={{
            color: '#ffffff',
            backgroundColor: isLight ? style.lightBorder : style.badge,
          }}
        >
          {item.priority}
        </span>
        <span
          className="text-xs font-semibold"
          style={{ color: isLight ? style.lightBorder : style.border }}
        >
          {item.title}
        </span>
      </div>
      <p
        className={`text-sm leading-relaxed ${isNextAction ? 'font-medium' : ''}`}
        style={{ color: isLight ? '#1e293b' : '#e2e8f0' }}
      >
        {item.body}
      </p>
    </div>
  )
}

export function FlashAdvicePanel({ matchId, asOfSet, asOfRallyNum, playerId }: FlashAdvicePanelProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const params: Record<string, string | number | boolean | null | undefined> = {
    match_id: matchId,
    as_of_set: asOfSet,
    player_id: playerId,
  }
  if (asOfRallyNum != null) {
    params.as_of_rally_num = asOfRallyNum
  }

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-flash-advice', matchId, asOfSet, asOfRallyNum, playerId],
    queryFn: () => apiGet<FlashAdviceResponse>('/analysis/flash_advice', params),
    enabled: !!matchId && !!asOfSet && !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const items = resp?.data?.items ?? []
  const extended = resp?.data?.extended_items_included ?? false

  if (sampleSize === 0 || items.length === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={1} unit="ラリー" />
  }

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {extended && (
        <div className="text-[10px] text-gray-400 text-right">
          {t('analysis.flash.extended_label')}
        </div>
      )}

      {/* analyst / coach: 全カード表示 */}
      <RoleGuard
        allowedRoles={['analyst', 'coach']}
        fallback={
          <div className="space-y-2">
            {items
              .filter((item) => PLAYER_VISIBLE_CATEGORIES.has(item.category))
              .map((item) => (
                <AdviceCard key={item.category} item={item} isLight={isLight} />
              ))}
          </div>
        }
      >
        <div className="space-y-2">
          {items.map((item) => (
            <AdviceCard key={item.category} item={item} isLight={isLight} />
          ))}
        </div>
      </RoleGuard>
    </div>
  )
}
