/**
 * QuickSummaryCard — コーチ向け一言カード (D: セット間・試合中支援)
 *
 * Design Language v1.2 グレースケール先行ビルド (2026-05-19 改訂):
 *   - カード自身に色塗りをしない (= L2 階層、骨格は無彩色)
 *   - 警告 (warn) だけ B_BAD の **左罫線 3px** で強調 (背景塗らない)
 *   - good / info はアイコンと typography だけで識別 (色塗らない)
 *   - 緑背景 + 緑文字、赤背景 + 赤文字 等の同色相重ねは絶対回避
 *     (§2.7 contrast rule)
 *
 * 信頼性原則:
 *   - サーバが ルールベース (review.py) で生成した text をそのまま表示
 *   - フロント側で文章生成・色判定の追加処理はしない
 */
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Info, CheckCircle2, RefreshCw } from 'lucide-react'
import { getQuickSummary, SummaryCard } from '@/api/review'
import { B_BAD, N_GRAY, A_GOOD } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTranslation } from 'react-i18next'

interface Tokens {
  bgPanel: string
  bgRow: string
  border: string
  divider: string
  textStrong: string
  textPrimary: string
  textMuted: string
  textFaint: string
}

function useTokens(): Tokens {
  const isLight = useIsLightMode()
  return isLight
    ? {
        bgPanel: '#ffffff',
        bgRow:   N_GRAY[50],
        border:  N_GRAY[200],
        divider: N_GRAY[200],
        textStrong:  N_GRAY[900],
        textPrimary: N_GRAY[800],
        textMuted:   N_GRAY[500],
        textFaint:   N_GRAY[400],
      }
    : {
        bgPanel: N_GRAY[900],
        bgRow:   N_GRAY[800],
        border:  N_GRAY[700],
        divider: N_GRAY[700],
        textStrong:  N_GRAY[50],
        textPrimary: N_GRAY[100],
        textMuted:   N_GRAY[400],
        textFaint:   N_GRAY[500],
      }
}

/**
 * 各レベルのアイコンと「色を出す権利」のマッピング。
 * - warn  : B_BAD の **左罫線** で意味付け (背景塗りなし、文字は中立色)
 * - good  : A_GOOD の **左罫線**、ただし常に出さない (12.3 G2 ゲートを通った時のみ)
 * - info  : 色なし (アイコンのみで識別)
 */
const LEVEL_META: Record<string, { Icon: typeof AlertTriangle; iconColor?: string; accent?: string }> = {
  warn: { Icon: AlertTriangle, accent: B_BAD },
  info: { Icon: Info },
  good: { Icon: CheckCircle2, accent: A_GOOD },
}

function CardItem({ card, tokens }: { card: SummaryCard; tokens: Tokens }) {
  const meta = LEVEL_META[card.level] ?? LEVEL_META.info
  const Icon = meta.Icon
  // 色を出す権利は accent があるレベルのみ。背景塗りなし。
  // 「左罫線 3px」のみで意味付け (Design Language §13.3)
  return (
    <div
      className="flex items-start gap-2.5 rounded px-3 py-2.5"
      style={{
        backgroundColor: tokens.bgRow,
        borderLeft: meta.accent ? `3px solid ${meta.accent}` : `3px solid transparent`,
      }}
    >
      <Icon
        size={14}
        className="shrink-0 mt-0.5"
        style={{ color: meta.accent ?? tokens.textMuted }}
      />
      <div className="min-w-0">
        <p
          className="text-xs font-semibold leading-tight"
          style={{ color: tokens.textStrong }}
        >
          {card.title}
        </p>
        <p
          className="text-[11px] mt-0.5 leading-snug"
          style={{ color: tokens.textPrimary }}
        >
          {card.body}
        </p>
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
  const { t } = useTranslation()
  const tokens = useTokens()

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['review', 'quick_summary', matchId, asOfSet, asOfRally, playerSide],
    queryFn: () => getQuickSummary(matchId, asOfSet, { asOfRally, playerSide }),
    enabled: matchId > 0,
    staleTime: 30_000,
  })

  const cards = data?.cards ?? []
  const warnCount = cards.filter((c) => c.level === 'warn').length

  return (
    <section
      className="rounded-md border"
      style={{ backgroundColor: tokens.bgPanel, borderColor: tokens.border }}
    >
      {/* ヘッダ */}
      <header
        className="flex items-center justify-between px-4 py-2 border-b"
        style={{ borderColor: tokens.divider }}
      >
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] font-semibold tracking-[0.18em] uppercase"
            style={{ color: tokens.textMuted }}
          >
            コーチ向けサマリー
          </span>
          {/* 警告件数バッジ: 件数だけ示す、色は B_BAD 文字のみ (背景なし) */}
          {warnCount > 0 && (
            <span
              className="text-[10px] font-semibold tabular-nums"
              style={{ color: B_BAD }}
              title="警告件数"
            >
              ⚠ {warnCount}
            </span>
          )}
          {data && (
            <span className="text-[10px]" style={{ color: tokens.textFaint }}>
              直近 {data.window} / 計 {data.total_rallies} ラリー
            </span>
          )}
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          title={t('auto.QuickSummaryCard.k2')}
          className="p-1 rounded disabled:opacity-40"
          style={{ color: tokens.textMuted }}
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
        </button>
      </header>
      <div className="px-3 py-3 space-y-2">
        {isLoading && (
          <p
            className="text-xs text-center py-2"
            style={{ color: tokens.textFaint }}
          >
            {t('auto.QuickSummaryCard.k1')}
          </p>
        )}
        {!isLoading && cards.length === 0 && (
          <p
            className="text-xs text-center py-2"
            style={{ color: tokens.textFaint }}
          >
            観測中…
          </p>
        )}
        {!isLoading && cards.map((card, i) => (
          <CardItem key={i} card={card} tokens={tokens} />
        ))}
      </div>
    </section>
  )
}
