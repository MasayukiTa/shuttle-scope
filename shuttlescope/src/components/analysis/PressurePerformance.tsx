// プレッシャー下のパフォーマンスを通常時・終盤・デュース時で比較する3列カード
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { QueryErrorNotice } from '@/components/common/QueryErrorNotice'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { perfColor, lightSafe, WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTranslation } from 'react-i18next'
import { fmtPct } from '@/utils/format'

interface PressurePerformanceProps {
  playerId: number
  filters?: AnalysisFilters
}

interface PressureSegment {
  // 件数 0 の区間は null (0% ではない)
  win_rate: number | null
  // backend (_build_stat) は rally 数を rally_count として返す。
  rally_count: number
  sample_size: number
}

interface PressureResponse {
  data: {
    normal: PressureSegment
    endgame: PressureSegment
    deuce: PressureSegment
  }
  meta: {
    sample_size: number
    confidence: { level: string; stars: string; label: string; warning?: string }
  }
}

function pctStr(v: number | null): string {
  return fmtPct(v)
}

// セグメントが比較可能か。ラリー数 0 の勝率は 0% ではなく「未定義」。
function hasData(seg: PressureSegment | undefined): seg is PressureSegment {
  return !!seg && Number.isFinite(seg.win_rate) && (seg.rally_count ?? seg.sample_size ?? 0) > 0
}

// 単一の圧力セグメントカード
// label は backend が返さないため i18n から供給する (i18n 規約: 表示文言は ja/en.json)。
function SegmentCard({
  segment,
  label,
  highlight,
  isLight,
}: {
  segment: PressureSegment
  label: string
  highlight?: boolean
  isLight: boolean
}) {
  const { t } = useTranslation()

  const empty = !hasData(segment)
  const n = segment.rally_count ?? segment.sample_size ?? 0
  const barWidth = empty ? '0%' : `${Math.min((segment.win_rate ?? 0) * 100, 100).toFixed(1)}%`
  const color = empty ? 'var(--ss-t3)' : lightSafe(perfColor(segment.win_rate ?? 0), !isLight)
  return (
    <div
      className={`rounded-ss-lg p-4 flex flex-col gap-2 bg-[var(--ss-surface-1)] border border-[var(--ss-border)] ${
        highlight ? 'ring-1 ring-[var(--ss-brand)] ring-offset-0' : ''
      }`}
    >
      <p className="text-xs text-[var(--ss-t3)] font-medium">{label}</p>
      <p className="text-2xl font-bold ss-num" style={{ color }}>
        {empty ? t('auto.PressurePerformance.no_data') : pctStr(segment.win_rate)}
      </p>
      {/* 進捗バー */}
      <div className="w-full bg-[var(--ss-surface-2)] rounded-ss-md h-1.5">
        <div
          className="h-1.5 rounded-ss-md duration-base ease-out"
          style={{ width: barWidth, backgroundColor: color }}
        />
      </div>
      <p className="text-xs text-[var(--ss-t3)]">
        {t('auto.PressurePerformance.rally_count_label')} <span className="text-[var(--ss-t2)] ss-num">{n}</span>
      </p>
      {/* 信頼度はセグメント自身のラリー数で判定する (全体の信頼度表示を各セグメントに流用しない) */}
      {!empty && <ConfidenceBadge sampleSize={n} unit="rallies" compact />}
    </div>
  )
}

export function PressurePerformance({ playerId, filters = DEFAULT_FILTERS }: PressurePerformanceProps) {
  const { t } = useTranslation()

  const isLight = useIsLightMode()
  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading, isError, refetch } = useQuery({
    queryKey: ['analysis-pressure-performance', playerId, filters],
    queryFn: () =>
      apiGet<PressureResponse>('/analysis/pressure_performance', {
        player_id: playerId,
        ...fp,
      }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return (
      <div className="text-[var(--ss-t3)] text-sm py-8 text-center">{t('auto.PressurePerformance.k1')}</div>
    )
  }

  if (isError) {
    return <QueryErrorNotice onRetry={() => { void refetch() }} />
  }

  const sampleSize = resp?.meta?.sample_size ?? 0

  if (!resp?.data || sampleSize === 0) {
    return (
      <div className="text-[var(--ss-t3)] text-sm py-4 text-center">
        {t('auto.PressurePerformance.insufficient')}
      </div>
    )
  }

  const { normal, endgame, deuce } = resp.data

  // 通常時と比べた終盤・デュース時の変化を矢印で表示
  function DeltaBadge({ base, target }: { base: PressureSegment; target: PressureSegment }) {
    // どちらかのラリー数が 0 なら差分は定義できない (0% 同士の差を赤い悪化として出さない)
    if (!hasData(base) || !hasData(target)) {
      return <span className="text-xs text-[var(--ss-t3)]">{t('auto.PressurePerformance.no_data')}</span>
    }
    const delta = (target.win_rate ?? 0) - (base.win_rate ?? 0)
    const absPct = Math.abs(delta * 100).toFixed(1)
    if (Math.abs(delta) < 0.005) {
      return <span className="text-xs text-[var(--ss-t3)] ss-num">±0.0%</span>
    }
    return delta > 0 ? (
      <span className="text-xs font-semibold ss-num" style={{ color: lightSafe(WIN, !isLight) }}>+{absPct}%</span>
    ) : (
      <span className="text-xs font-semibold ss-num" style={{ color: lightSafe(LOSS, !isLight) }}>−{absPct}%</span>
    )
  }

  return (
    <div className="space-y-3">
      {/* 信頼度バッジ */}
      <ConfidenceBadge sampleSize={sampleSize} unit="rallies" />

      {/* 3列カード */}
      <div className="grid grid-cols-3 gap-3">
        <SegmentCard segment={normal} label={t('auto.PressurePerformance.label_normal')} isLight={isLight} />
        <SegmentCard segment={endgame} label={t('auto.PressurePerformance.label_endgame')} highlight isLight={isLight} />
        <SegmentCard segment={deuce} label={t('auto.PressurePerformance.label_deuce')} highlight isLight={isLight} />
      </div>

      {/* 通常時からの変化 */}
      <div className="flex gap-3 text-xs">
        <div className="flex-1" />
        <div className="flex-1 flex items-center justify-center gap-1 text-[var(--ss-t3)]">
          {t('auto.PressurePerformance.vs_normal')} <DeltaBadge base={normal} target={endgame} />
        </div>
        <div className="flex-1 flex items-center justify-center gap-1 text-[var(--ss-t3)]">
          {t('auto.PressurePerformance.vs_normal')} <DeltaBadge base={normal} target={deuce} />
        </div>
      </div>
    </div>
  )
}
