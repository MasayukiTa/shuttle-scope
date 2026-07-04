// スタイル距離カード（RESEARCH ティア · アナリスト・コーチ専用）
//
// 設計原則:
//   - プレイヤーロールには絶対に表示しない (ページレベルで RoleGuard 済み)
//   - 最近傍選手リスト + 距離バー + 2D スキャタ SVG のみ。数式・手法説明は表示しない
//   - コーホート不足時は graceful empty state を表示する
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchStyleDistance, StyleDistanceEntry, StyleMapEntry } from '@/api/styleDistance'
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

/** 距離を 0..1 の正規化バー幅に変換する (最大値基準) */
function normalizeDistances(entries: StyleDistanceEntry[]): Map<number, number> {
  const result = new Map<number, number>()
  if (entries.length === 0) return result
  const maxDist = Math.max(...entries.map((e) => e.distance), 1e-9)
  for (const e of entries) {
    result.set(e.player_id, e.distance / maxDist)
  }
  return result
}

/** style_map の x/y を SVG 座標系（0..1）に正規化する */
function normalizeStyleMap(
  entries: StyleMapEntry[],
): Map<number, { nx: number; ny: number }> {
  const result = new Map<number, { nx: number; ny: number }>()
  if (entries.length === 0) return result
  const xs = entries.map((e) => e.x)
  const ys = entries.map((e) => e.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const rangeX = maxX - minX || 1
  const rangeY = maxY - minY || 1
  for (const e of entries) {
    result.set(e.player_id, {
      nx: (e.x - minX) / rangeX,
      ny: (e.y - minY) / rangeY,
    })
  }
  return result
}

// ── サブコンポーネント: 距離リスト行 ─────────────────────────────────────────

function DistanceRow({
  entry,
  normalizedWidth,
  isNearest,
  t,
  textMuted,
  textFaint,
  border,
  cardInner,
}: {
  entry: StyleDistanceEntry
  normalizedWidth: number
  isNearest: boolean
  t: ReturnType<typeof useTranslation>['t']
  textMuted: string
  textFaint: string
  border: string
  cardInner: string
}) {
  // 距離が小さい = 類似 → バーは「小さい距離 = 長いバー」に反転
  const barWidth = 1 - normalizedWidth
  return (
    <div className={`rounded-ss-md p-2.5 border ${border} ${cardInner}`}>
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-1.5">
          {isNearest && (
            <MIcon name="person_pin" size={12} className="text-emerald-400 shrink-0" />
          )}
          <span className={`text-[11px] font-medium ${isNearest ? 'text-emerald-400' : textMuted}`}>
            {entry.player_name}
          </span>
        </div>
        <span className={`text-[10px] font-mono ${textFaint}`}>
          {t('auto.StyleDistanceCard.distance_value', {
            d: entry.distance.toFixed(3),
          })}
        </span>
      </div>
      {/* 距離バー (小距離 = 長い類似バー) */}
      <div className="h-1.5 w-full rounded-full bg-[var(--ss-surface-2)] overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{
            width: `${barWidth * 100}%`,
            backgroundColor: isNearest ? '#34d399' : 'var(--ss-brand)',
          }}
        />
      </div>
    </div>
  )
}

// ── サブコンポーネント: 2D スキャタ SVG ────────────────────────────────────

const SVG_W = 260
const SVG_H = 180
const PADDING = 20

function StyleScatterSvg({
  styleMap,
  referenceId,
  nearestIds,
}: {
  styleMap: StyleMapEntry[]
  referenceId: number
  nearestIds: number[]
}) {
  const normalized = useMemo(() => normalizeStyleMap(styleMap), [styleMap])

  if (styleMap.length === 0) return null

  const nearestSet = new Set(nearestIds)
  const innerW = SVG_W - PADDING * 2
  const innerH = SVG_H - PADDING * 2

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="w-full max-w-xs rounded-ss-md"
      aria-hidden="true"
    >
      {/* 背景 */}
      <rect width={SVG_W} height={SVG_H} rx={6} fill="var(--ss-surface-2)" opacity="0.5" />

      {styleMap.map((entry) => {
        const coords = normalized.get(entry.player_id)
        if (!coords) return null
        const cx = PADDING + coords.nx * innerW
        // y は SVG 座標系（上が 0）なので反転
        const cy = PADDING + (1 - coords.ny) * innerH
        const isRef = entry.player_id === referenceId
        const isNear = nearestSet.has(entry.player_id)

        const fill = isRef ? '#fbbf24' : isNear ? '#34d399' : '#60a5fa'
        const r = isRef ? 7 : 4

        return (
          <g key={entry.player_id}>
            <circle cx={cx} cy={cy} r={r} fill={fill} opacity={isRef || isNear ? 1 : 0.55} />
            <text
              x={cx}
              y={cy - r - 2}
              textAnchor="middle"
              fontSize={isRef ? 9 : 7}
              fill={fill}
              fontWeight={isRef ? 'bold' : 'normal'}
            >
              {entry.player_name.length > 8
                ? entry.player_name.slice(0, 7) + '…'
                : entry.player_name}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ── メインコンポーネント ───────────────────────────────────────────────────────

export function StyleDistanceCard({ playerId }: Props) {
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
    queryKey: ['styleDistance', playerId],
    queryFn: () => fetchStyleDistance(playerId),
    enabled: !!playerId,
  })

  const distData = data?.data
  const meta = data?.meta

  // 距離リスト: 昇順（最類似が先頭）
  const sortedDistances = useMemo(() => {
    if (!distData?.distances) return []
    return [...distData.distances].sort((a, b) => a.distance - b.distance)
  }, [distData])

  const nearestSet = useMemo(
    () => new Set(distData?.nearest ?? []),
    [distData],
  )

  const distNormMap = useMemo(
    () => normalizeDistances(sortedDistances),
    [sortedDistances],
  )

  const isEmpty = !distData || distData.cohort_size < 1 || sortedDistances.length === 0

  return (
    <div className={`${card} rounded-ss-lg p-4 space-y-3`}>
      {/* ─ ヘッダ ── */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className={`text-sm font-semibold ${textHeading} flex items-center gap-1.5`}>
          <MIcon name="compare_arrows" size={16} />
          {t('auto.StyleDistanceCard.title')}
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
        caution={t('auto.StyleDistanceCard.caution')}
        assumptions={t('auto.StyleDistanceCard.assumptions')}
        promotionCriteria={t('auto.StyleDistanceCard.promotion_criteria')}
      />

      {/* ─ ローディング ── */}
      {isLoading && (
        <p className={`text-sm text-center py-4 ${loading}`}>
          {t('auto.StyleDistanceCard.loading')}
        </p>
      )}

      {/* ─ エラー ── */}
      {isError && !isLoading && (
        <p className="text-sm text-center py-4 text-[var(--ss-bad)]">
          {t('auto.StyleDistanceCard.error')}
        </p>
      )}

      {/* ─ データあり ── */}
      {!isLoading && !isError && data && (
        <>
          {/* コーホート不足 → graceful empty state */}
          {isEmpty ? (
            <div className={`rounded-ss-md p-3 border ${border} ${cardInner} opacity-60`}>
              <div className="flex items-center gap-1.5">
                <MIcon name="info" size={14} className="text-amber-400 shrink-0" />
                <p className={`text-[11px] ${textMuted}`}>
                  {t('auto.StyleDistanceCard.empty')}
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* サマリ: コーホートサイズ + 信頼度 */}
              <div className={`rounded-ss-md p-2.5 border ${border} ${cardInner}`}>
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className={`text-[11px] ${textMuted}`}>
                    {t('auto.StyleDistanceCard.cohort_summary', {
                      n: distData!.cohort_size,
                    })}
                  </span>
                  <ConfidenceBadge sampleSize={meta?.sample_size ?? 0} compact />
                </div>
              </div>

              {/* 最類似選手の見出し */}
              {nearestSet.size > 0 && (
                <p className={`text-[11px] font-medium text-emerald-400`}>
                  <MIcon name="person_pin" size={12} className="align-middle mr-0.5" />
                  {t('auto.StyleDistanceCard.plays_most_like', {
                    names: sortedDistances
                      .filter((e) => nearestSet.has(e.player_id))
                      .map((e) => e.player_name)
                      .join('、'),
                  })}
                </p>
              )}

              {/* 距離リスト（昇順） */}
              <div className="space-y-1.5">
                <p className={`text-[10px] font-medium uppercase tracking-wider ${textFaint}`}>
                  {t('auto.StyleDistanceCard.distance_list_header', {
                    n: sortedDistances.length,
                  })}
                </p>
                {sortedDistances.map((entry) => (
                  <DistanceRow
                    key={entry.player_id}
                    entry={entry}
                    normalizedWidth={distNormMap.get(entry.player_id) ?? 0}
                    isNearest={nearestSet.has(entry.player_id)}
                    t={t}
                    textMuted={textMuted}
                    textFaint={textFaint}
                    border={border}
                    cardInner={cardInner}
                  />
                ))}
              </div>

              {/* 2D スキャタ（style_map がある場合のみ表示） */}
              {distData!.style_map && distData!.style_map.length > 0 && (
                <div className="space-y-1">
                  <p className={`text-[10px] font-medium uppercase tracking-wider ${textFaint}`}>
                    {t('auto.StyleDistanceCard.scatter_header')}
                  </p>
                  <StyleScatterSvg
                    styleMap={distData!.style_map}
                    referenceId={distData!.reference_player}
                    nearestIds={distData!.nearest}
                  />
                  <p className={`text-[9px] ${textFaint}`}>
                    {t('auto.StyleDistanceCard.scatter_legend')}
                  </p>
                </div>
              )}
            </>
          )}

          <p className={`text-[10px] ${textFaint}`}>
            {t('auto.StyleDistanceCard.footnote')}
          </p>
        </>
      )}
    </div>
  )
}
