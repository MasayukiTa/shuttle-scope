/**
 * QuickSummaryCard — コーチ向け一言カード (D: セット間・試合中支援)
 *
 * ルールベースのサマリーカードをアコーディオン形式で表示する。
 * FlashAdvicePanel と横に並べるコンパクトな差し込み用途を想定。
 */
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Info, CheckCircle2, RefreshCw } from 'lucide-react'
import { getQuickSummary, SummaryCard } from '@/api/review'
import { useCardTheme } from '@/hooks/useCardTheme'

const LEVEL_CONFIG = {
  warn: {
    icon: AlertTriangle,
    iconColor: 'text-red-400',
    badgeClass: 'bg-red-900/20 border-red-800/40 text-red-300',
    barClass: 'bg-red-500',
  },
  info: {
    icon: Info,
    iconColor: 'text-blue-400',
    badgeClass: 'bg-blue-900/20 border-blue-800/40 text-blue-300',
    barClass: 'bg-blue-500',
  },
  good: {
    icon: CheckCircle2,
    iconColor: 'text-green-400',
    badgeClass: 'bg-green-900/20 border-green-800/40 text-green-300',
    barClass: 'bg-green-500',
  },
}

const LEVEL_CONFIG_LIGHT = {
  warn: {
    icon: AlertTriangle,
    iconColor: 'text-red-500',
    badgeClass: 'bg-red-50 border-red-200 text-red-700',
    barClass: 'bg-red-500',
  },
  info: {
    icon: Info,
    iconColor: 'text-blue-500',
    badgeClass: 'bg-blue-50 border-blue-200 text-blue-700',
    barClass: 'bg-blue-500',
  },
  good: {
    icon: CheckCircle2,
    iconColor: 'text-green-600',
    badgeClass: 'bg-green-50 border-green-200 text-green-700',
    barClass: 'bg-green-500',
  },
}

function CardItem({ card, isLight }: { card: SummaryCard; isLight: boolean }) {
  const cfg = isLight ? LEVEL_CONFIG_LIGHT[card.level] : LEVEL_CONFIG[card.level]
  const Icon = cfg.icon
  return (
    <div className={`rounded border px-3 py-2.5 flex items-start gap-2.5 ${cfg.badgeClass}`}>
      <Icon size={14} className={`shrink-0 mt-0.5 ${cfg.iconColor}`} />
      <div>
        <p className="text-xs font-semibold leading-tight">{card.title}</p>
        <p className="text-[11px] mt-0.5 opacity-80 leading-snug">{card.body}</p>
      </div>
    </div>
  )
}

interface Props {
  matchId: number
  asOfSet: number
  asOfRally?: number
  /** player_a / player_b — 自軍サイド */
  playerSide?: string
}

export function QuickSummaryCard({ matchId, asOfSet, asOfRally, playerSide = 'player_a' }: Props) {
  const { textMuted, border, isLight } = useCardTheme()

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['review', 'quick_summary', matchId, asOfSet, asOfRally, playerSide],
    queryFn: () => getQuickSummary(matchId, asOfSet, { asOfRally, playerSide }),
    enabled: matchId > 0,
    staleTime: 30_000,
  })

  const cards = data?.cards ?? []
  const warnCount = cards.filter((c) => c.level === 'warn').length

  return (
    <div className={`rounded-lg border ${isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'}`}>
      <div className={`flex items-center justify-between px-4 py-2.5 border-b ${border}`}>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold ${isLight ? 'text-gray-700' : 'text-gray-300'}`}>
            コーチ向けサマリー
          </span>
          {warnCount > 0 && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
              isLight ? 'bg-red-100 text-red-700' : 'bg-red-900/40 text-red-300'
            }`}>
              ⚠ {warnCount}
            </span>
          )}
          {data && (
            <span className={`text-[10px] ${textMuted}`}>
              直近 {data.window} ラリー / 計 {data.total_rallies} ラリー
            </span>
          )}
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          title="再取得"
          className={`p-1 rounded transition-colors ${
            isLight ? 'text-gray-400 hover:text-gray-700 hover:bg-gray-100' : 'text-gray-500 hover:text-gray-300 hover:bg-gray-700'
          } disabled:opacity-40`}
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
        </button>
      </div>
      <div className="px-4 py-3 space-y-2">
        {isLoading && (
          <p className={`text-sm text-center py-2 ${textMuted}`}>読み込み中...</p>
        )}
        {!isLoading && cards.map((card, i) => (
          <CardItem key={i} card={card} isLight={isLight} />
        ))}
      </div>
    </div>
  )
}
