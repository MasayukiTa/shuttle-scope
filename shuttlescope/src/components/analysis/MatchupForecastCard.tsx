// 対戦予測カード（RESEARCH ティア · アナリスト・コーチ専用）
//
// 設計原則:
//   - プレイヤーロールには絶対に表示しない (ページレベルで RoleGuard 済み)
//   - CI 幅を必ず可視化する（CI 帯 = 誠実な不確実性開示、非交渉条件）
//   - n_h2h が少ない対戦は CI 幅が広くなることを明示する
//   - 数値・バー・CI 帯のみ。数式・手法説明は表示しない
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchMatchupForecast, MatchupForecastEntry } from '@/api/matchupForecast'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { MIcon } from '@/components/common/MIcon'
import { useCardTheme } from '@/hooks/useCardTheme'

// ── props ────────────────────────────────────────────────────────────────────

interface Props {
  playerId: number
}

// ── ヘルパー ─────────────────────────────────────────────────────────────────

function pct1(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

// ── サブコンポーネント: 対戦行 ───────────────────────────────────────────────

function MatchupRow({
  entry,
  t,
  border,
  textMuted,
  textFaint,
  cardInner,
}: {
  entry: MatchupForecastEntry
  t: ReturnType<typeof useTranslation>['t']
  border: string
  textMuted: string
  textFaint: string
  cardInner: string
}) {
  const pWin = Math.max(0, Math.min(1, entry.p_win))
  const ciLow = Math.max(0, Math.min(1, entry.ci_low))
  const ciHigh = Math.max(0, Math.min(1, entry.ci_high))

  // CI 帯をバーに重ねて表示
  const ciWidth = ciHigh - ciLow
  const barColor = pWin >= 0.55 ? '#34d399' : pWin <= 0.45 ? '#f87171' : '#60a5fa'

  // CI 幅が広い（>30pp）= 疎データ
  const isSparse = ciWidth > 0.3

  return (
    <div className={`rounded-ss-md p-3 space-y-2 border ${border} ${cardInner}`}>
      {/* ─ ヘッダ: 対戦相手名 + p_win + n_h2h ── */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className={`text-[11px] font-medium ${textMuted} truncate max-w-[120px]`}>
          {entry.opponent_name}
        </span>
        <div className="flex items-center gap-3 shrink-0">
          <span
            className="text-base font-bold font-mono ss-num"
            style={{ color: barColor }}
          >
            {pct1(pWin)}
          </span>
          <span className={`text-[10px] ${textFaint} ss-num`}>
            {t('auto.MatchupForecastCard.n_h2h', { n: entry.n_h2h })}
          </span>
        </div>
      </div>

      {/* ─ p_win バー + CI 帯 (真の pill 進捗バーなので rounded-full 維持) ── */}
      <div className="relative h-3 w-full rounded-full bg-gray-700/40 overflow-hidden">
        {/* p_win バー */}
        <div
          className="absolute top-0 left-0 h-full rounded-full"
          style={{ width: `${pWin * 100}%`, backgroundColor: barColor }}
        />
        {/* CI 帯 (半透明オーバーレイ) */}
        <div
          className="absolute top-0 h-full rounded-full"
          style={{
            left: `${ciLow * 100}%`,
            width: `${ciWidth * 100}%`,
            backgroundColor: 'rgba(255,255,255,0.15)',
          }}
        />
        {/* 50% 中央線 */}
        <div
          className="absolute top-0 h-full w-px bg-gray-400/40"
          style={{ left: '50%' }}
        />
      </div>

      {/* ─ CI テキスト ── */}
      <div className="flex items-center justify-between gap-2">
        <p className={`text-[10px] ${textFaint} ss-num`}>
          {t('auto.MatchupForecastCard.ci_range', {
            low: pct1(ciLow),
            high: pct1(ciHigh),
          })}
        </p>
        {/* 疎データ警告（真のバッジ chip なので rounded-full 維持） */}
        {isSparse && (
          <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-400 shrink-0">
            <MIcon name="warning" size={9} />
            {t('auto.MatchupForecastCard.sparse_warning')}
          </span>
        )}
      </div>
    </div>
  )
}

// ── メインコンポーネント ───────────────────────────────────────────────────────

export function MatchupForecastCard({ playerId }: Props) {
  const { t } = useTranslation()
  const {
    card,
    textHeading,
    textMuted,
    textFaint,
    border,
    cardInner,
    loading,
  } = useCardTheme()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['matchupForecast', playerId],
    queryFn: () => fetchMatchupForecast(playerId),
    enabled: !!playerId,
  })

  const forecastData = data?.data
  const meta = data?.meta

  // 対戦リストを p_win 降順にソート
  const sortedMatchups = useMemo<MatchupForecastEntry[]>(() => {
    if (!forecastData?.matchups) return []
    return [...forecastData.matchups].sort((a, b) => b.p_win - a.p_win)
  }, [forecastData])

  const isEmpty = !forecastData || sortedMatchups.length === 0

  return (
    <div className={`${card} rounded-ss-lg shadow-card p-4 space-y-3`}>
      {/* ─ ヘッダ ── */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className={`text-sm font-semibold ${textHeading} flex items-center gap-1.5`}>
          <MIcon name="sports_tennis" size={16} />
          {t('auto.MatchupForecastCard.title')}
        </h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      {/* ─ 研究注意バナー ── */}
      <ResearchNotice
        caution={t('auto.MatchupForecastCard.caution')}
        assumptions={t('auto.MatchupForecastCard.assumptions')}
        promotionCriteria={t('auto.MatchupForecastCard.promotion_criteria')}
      />

      {/* ─ ローディング ── */}
      {isLoading && (
        <p className={`text-sm text-center py-4 ${loading}`}>
          {t('auto.MatchupForecastCard.loading')}
        </p>
      )}

      {/* ─ エラー ── */}
      {isError && !isLoading && (
        <p className="text-sm text-center py-4 text-red-400">
          {t('auto.MatchupForecastCard.error')}
        </p>
      )}

      {/* ─ データあり ── */}
      {!isLoading && !isError && data && (
        <>
          {/* 全体強度推定（strength が null でない場合のみ） */}
          {forecastData?.strength && (
            <div className={`rounded-ss-md p-2.5 border ${border} ${cardInner}`}>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className={`text-[11px] ${textMuted}`}>
                  {t('auto.MatchupForecastCard.strength_label')}
                  <span className="ml-1 font-mono font-semibold text-blue-400 ss-num">
                    {forecastData.strength.value.toFixed(3)}
                  </span>
                </span>
                <span className={`text-[10px] ${textFaint} ss-num`}>
                  {t('auto.MatchupForecastCard.strength_ci', {
                    low: forecastData.strength.ci_low.toFixed(3),
                    high: forecastData.strength.ci_high.toFixed(3),
                  })}
                </span>
                <ConfidenceBadge sampleSize={meta?.sample_size ?? 0} compact />
              </div>
            </div>
          )}

          {/* データなし / 対戦なし → graceful empty state */}
          {isEmpty ? (
            <div className={`rounded-ss-md p-3 border ${border} ${cardInner} opacity-60`}>
              <div className="flex items-center gap-1.5">
                <MIcon name="info" size={14} className="text-amber-400 shrink-0" />
                <p className={`text-[11px] ${textMuted}`}>
                  {t('auto.MatchupForecastCard.empty')}
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <p className={`text-[10px] font-medium uppercase tracking-wider ${textFaint}`}>
                {t('auto.MatchupForecastCard.matchups_header', {
                  n: sortedMatchups.length,
                })}
              </p>
              {/* CI 幅の説明注記 */}
              <p className={`text-[10px] ${textFaint}`}>
                {t('auto.MatchupForecastCard.ci_hint')}
              </p>
              {sortedMatchups.map((entry) => (
                <MatchupRow
                  key={entry.opponent_id}
                  entry={entry}
                  t={t}
                  border={border}
                  textMuted={textMuted}
                  textFaint={textFaint}
                  cardInner={cardInner}
                />
              ))}
            </div>
          )}

          <p className={`text-[10px] ${textFaint}`}>
            {t('auto.MatchupForecastCard.footnote')}
          </p>
        </>
      )}
    </div>
  )
}
