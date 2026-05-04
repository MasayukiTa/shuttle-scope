/**
 * CourtHeatModal — コートヒートマップ全画面モーダル
 *
 * - 打点 / 着地点の切り替え
 * - 期間プリセット（直近N試合）と試合個別選択
 * - ゾーンクリック → ゾーン詳細パネル（API on-demand）
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { X, LayoutDashboard, AlertTriangle } from 'lucide-react'
import { CourtDiagram } from '@/components/court/CourtDiagram'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { apiGet } from '@/api/client'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import type { LandZone } from '@/types'

interface MatchSummary {
  match_id: number
  opponent: string
  date: string | null
  result: 'win' | 'loss' | string | null
}

interface CourtHeatModalProps {
  playerId: number
  matches: MatchSummary[]
  initialMatchId: number | null
  initialLastN: number | null
  initialTab: 'hit' | 'land' | 'composite'
  onClose: () => void
}

interface HeatmapResponse {
  success: boolean
  data: Record<string, number>
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

interface CompositeZoneData {
  count: number
  rate: number
  source?: string
}

interface CompositeHeatmapResponse {
  success: boolean
  data: {
    hit: Record<string, CompositeZoneData>
    land_rotated: Record<string, CompositeZoneData>
    total_strokes: number
    note: string
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

interface ZoneDetailResponse {
  success: boolean
  data: {
    zone: string
    type: string
    count: number
    wins: number
    win_rate: number | null
    top_shot_types: { shot_type: string; count: number }[]
    transitions: { zone: string; count: number }[]
  }
  meta: { sample_size: number }
}

const ZONE_KEYS = ['BL', 'BC', 'BR', 'ML', 'MC', 'MR', 'NL', 'NC', 'NR'] as const

export function CourtHeatModal({
  playerId,
  matches,
  initialMatchId,
  initialLastN,
  initialTab,
  onClose,
}: CourtHeatModalProps) {
  const { t } = useTranslation()

  const [mode, setMode] = useState<'hit' | 'land' | 'composite'>(initialTab)
  const [matchId, setMatchId] = useState<number | null>(initialMatchId)
  const [lastN, setLastN] = useState<number | null>(initialLastN)
  const [selectedZone, setSelectedZone] = useState<LandZone | null>(null)

  // ESCキーで閉じる
  // （ChartModal と同じパターン — useEffect は DashboardPage 側で済み）

  // フィルターパラメータを計算（直近N試合はmatch_ids指定で正確に絞り込む）
  const apiParams = (() => {
    if (matchId != null) return { match_id: matchId }
    if (lastN != null) {
      const recent = [...matches]
        .sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))
        .slice(0, lastN)
      const ids = recent.map((m) => m.match_id).join(',')
      return ids ? { match_ids: ids } : {}
    }
    return {}
  })()

  // ヒートマップデータ（通常モード: hit / land）
  // mode === 'composite' の場合はenabled=falseなので type に 'composite' が届かない
  const heatmapType = (mode === 'composite' ? 'hit' : mode) as 'hit' | 'land'
  const { data: heatResp, isLoading: loadingHeat } = useQuery({
    queryKey: ['court-heat-modal', playerId, mode, matchId, lastN],
    queryFn: () =>
      apiGet<HeatmapResponse>('/analysis/heatmap', {
        player_id: playerId,
        type: heatmapType,
        ...apiParams,
      }),
    enabled: mode !== 'composite',
  })

  // 合成モードデータ
  const { data: compositeResp, isLoading: loadingComposite } = useQuery({
    queryKey: ['court-heat-composite', playerId, matchId, lastN],
    queryFn: () =>
      apiGet<CompositeHeatmapResponse>('/analysis/heatmap/composite', {
        player_id: playerId,
        ...apiParams,
      }),
    enabled: mode === 'composite',
  })

  const heatmapData: Record<string, number> = heatResp?.data ?? {}
  const sampleSize = mode === 'composite'
    ? (compositeResp?.data?.total_strokes ?? 0)
    : (heatResp?.meta?.sample_size ?? 0)
  const loadingCurrent = mode === 'composite' ? loadingComposite : loadingHeat

  // 合成モード用データ
  const compositeHitData = compositeResp?.data?.hit
    ? Object.fromEntries(Object.entries(compositeResp.data.hit).map(([k, v]) => [k, v.count]))
    : undefined
  const compositeLandData = compositeResp?.data?.land_rotated
    ? Object.fromEntries(Object.entries(compositeResp.data.land_rotated).map(([k, v]) => [k, v.count]))
    : undefined
  const compositeHitMax = compositeHitData ? Math.max(...Object.values(compositeHitData), 1) : 1
  const compositeLandMax = compositeLandData ? Math.max(...Object.values(compositeLandData), 1) : 1

  // ゾーン詳細（クリック時のみ取得）— 打点 or 合成の打点側
  const { data: detailResp, isLoading: loadingDetail } = useQuery({
    queryKey: ['court-heat-zone-detail', playerId, mode, selectedZone, matchId, lastN],
    queryFn: () =>
      apiGet<ZoneDetailResponse>('/analysis/heatmap_zone_detail', {
        player_id: playerId,
        type: heatmapType,
        zone: selectedZone!,
        ...apiParams,
      }),
    enabled: selectedZone != null,
  })

  // 合成モード専用: 着地点ゾーン詳細
  const { data: detailLandResp, isLoading: loadingDetailLand } = useQuery({
    queryKey: ['court-heat-zone-detail-land', playerId, selectedZone, matchId, lastN],
    queryFn: () =>
      apiGet<ZoneDetailResponse>('/analysis/heatmap_zone_detail', {
        player_id: playerId,
        type: 'land',
        zone: selectedZone!,
        ...apiParams,
      }),
    enabled: selectedZone != null && mode === 'composite',
  })

  const detail = detailResp?.data
  const detailLand = detailLandResp?.data
  const isLight = useIsLightMode()

  const filterBarClass = (active: boolean) =>
    `text-[11px] px-2 py-0.5 rounded border transition-colors ${
      active
        ? 'bg-gray-500 border-gray-400 text-white'
        : 'bg-gray-700 border-gray-600 text-gray-400 hover:bg-gray-600'
    }`

  return (
    <div className="fixed inset-0 z-50 bg-black/85 flex flex-col">
      {/* ヘッダー */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-700 bg-gray-900 shrink-0">
        <span className="text-white font-semibold text-base">{t('court_heat_modal.title')}</span>
        <div className="flex items-center gap-3">
          <button
            onClick={onClose}
            className="flex items-center gap-1.5 text-xs text-gray-300 hover:text-white bg-gray-700 hover:bg-gray-600 transition-colors px-3 py-1.5 rounded"
          >
            <LayoutDashboard size={13} />
            {t('court_heat_modal.back_to_dashboard')}
          </button>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors p-1 rounded hover:bg-gray-700"
            title={t('court_heat_modal.close_esc')}
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* コンテンツ */}
      <div className="flex-1 overflow-auto bg-gray-900">
        <div className="flex flex-col lg:flex-row gap-6 p-6 min-h-full">

          {/* 左：コート図 + フィルター */}
          <div className="flex flex-col items-center gap-4 lg:w-auto">
            {/* 打点 / 着地点 / 合成切替 */}
            <div className="flex gap-1.5 flex-wrap">
              {([
                { key: 'hit', labelKey: 'court_heat_modal.tab_hit' },
                { key: 'land', labelKey: 'court_heat_modal.tab_land' },
                { key: 'composite', labelKey: 'court_heat_modal.tab_composite' },
              ] as const).map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => { setMode(tab.key); setSelectedZone(null) }}
                  className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
                    mode === tab.key
                      ? 'bg-gray-600 text-white'
                      : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                  }`}
                >
                  {t(tab.labelKey)}
                </button>
              ))}
            </div>

            {/* 合成モード注意書き */}
            {mode === 'composite' && (
              <div className="flex items-start gap-2 p-3 bg-amber-950/60 border border-amber-700/50 rounded-lg text-xs max-w-xs">
                <AlertTriangle size={13} className="text-amber-400 mt-0.5 shrink-0" />
                <div className="text-amber-300/80">
                  {t('court_heat_modal.composite_note')}
                </div>
              </div>
            )}

            {/* 期間・試合フィルター */}
            <div className="space-y-2 w-full max-w-xs">
              <div className="flex gap-1 flex-wrap justify-center">
                {([null, 3, 5, 10] as const).map((n) => (
                  <button
                    key={n ?? 'all'}
                    onClick={() => { setLastN(n); setMatchId(null); setSelectedZone(null) }}
                    disabled={matchId != null}
                    className={filterBarClass(matchId == null && lastN === n)}
                  >
                    {n == null ? t('court_heat_modal.period_all') : t('court_heat_modal.period_last_n', { n })}
                  </button>
                ))}
              </div>
              {matches.length > 0 && (
                <SearchableSelect
                  options={[...matches]
                    .sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))
                    .map((m) => ({
                      value: m.match_id,
                      label: `${m.date ?? t('court_heat_modal.match_date_unknown')} ${m.opponent}`,
                      suffix: m.result === 'win' ? t('court_heat_modal.result_win_short') : t('court_heat_modal.result_loss_short'),
                      searchText: `${m.date} ${m.opponent}`,
                    }))}
                  value={matchId}
                  onChange={(v) => {
                    setMatchId(v != null ? Number(v) : null)
                    if (v != null) setLastN(null)
                    setSelectedZone(null)
                  }}
                  emptyLabel={t('court_heat_modal.match_select_empty')}
                  placeholder={t('court_heat_modal.match_select_placeholder')}
                />
              )}
            </div>

            {/* サンプルサイズ */}
            <div className="flex items-center gap-2">
              {sampleSize > 0 && <ConfidenceBadge sampleSize={sampleSize} />}
              <span className="text-[11px] text-gray-500">
                {t('court_heat_modal.stroke_count', { n: sampleSize })}
              </span>
            </div>

            {/* コート図（インタラクティブ） */}
            {loadingCurrent ? (
              <div className="text-gray-500 text-sm py-8">{t('court_heat_modal.loading')}</div>
            ) : sampleSize === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <p className="text-gray-500 text-sm">{t('court_heat_modal.no_data')}</p>
                <p className="text-gray-600 text-xs mt-1">{t('court_heat_modal.no_data_hint')}</p>
              </div>
            ) : (
              <CourtDiagram
                mode={mode}
                heatmapData={mode !== 'composite' ? heatmapData : undefined}
                compositeHitData={compositeHitData}
                compositeHitMax={compositeHitMax}
                compositeLandRotatedData={compositeLandData}
                compositeLandMax={compositeLandMax}
                selectedZone={selectedZone}
                onZoneSelect={(z) => setSelectedZone(z === selectedZone ? null : z)}
                interactive={true}
                showOOB={false}
                maxHeight={Math.max(300, (typeof window !== 'undefined' ? window.innerHeight : 600) - 280)}
              />
            )}

            {/* 合成モード凡例 */}
            {mode === 'composite' && sampleSize > 0 && (
              <div className="flex items-center gap-4 text-xs text-gray-400">
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-3 rounded" style={{ backgroundColor: 'rgba(59,130,246,0.85)' }} />
                  {t('court_heat_modal.legend_hit')}
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-3 rounded" style={{ backgroundColor: 'rgba(249,115,22,0.70)' }} />
                  {t('court_heat_modal.legend_land_transformed')}
                </div>
              </div>
            )}

            <p className="text-[10px] text-gray-600">
              {t('court_heat_modal.click_zone_hint')}
            </p>
          </div>

          {/* 右：ゾーン詳細パネル */}
          <div className="flex-1 min-w-0">
            {selectedZone == null ? (
              <div className="flex items-center justify-center h-full min-h-[200px]">
                <p className="text-gray-600 text-sm text-center whitespace-pre-line">
                  {t('court_heat_modal.click_zone_detail')}
                </p>
              </div>
            ) : (loadingDetail || (mode === 'composite' && loadingDetailLand)) ? (
              <div className="flex items-center justify-center h-full min-h-[200px]">
                <div className="text-gray-500 text-sm">{t('court_heat_modal.loading')}</div>
              </div>
            ) : mode === 'composite' ? (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                {detail && (
                  <div>
                    <p className="text-[11px] font-semibold text-blue-400 mb-2 px-1">{t('court_heat_modal.header_hit')}</p>
                    <ZoneDetailPanel detail={detail} mode="hit" t={t} isLight={isLight} />
                  </div>
                )}
                {detailLand && (
                  <div>
                    <p className="text-[11px] font-semibold text-orange-400 mb-2 px-1">{t('court_heat_modal.header_land_transformed')}</p>
                    <ZoneDetailPanel detail={detailLand} mode="land" t={t} isLight={isLight} />
                  </div>
                )}
              </div>
            ) : detail ? (
              <ZoneDetailPanel detail={detail} mode={heatmapType} t={t} isLight={isLight} />
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── ゾーン詳細パネル ───────────────────────────────────────────────────────

function ZoneDetailPanel({
  detail,
  mode,
  t,
  isLight,
}: {
  detail: ZoneDetailResponse['data']
  mode: 'hit' | 'land'
  t: ReturnType<typeof useTranslation>['t']
  isLight: boolean
}) {
  const zoneName = ZONE_KEYS.includes(detail.zone as typeof ZONE_KEYS[number])
    ? t(`court_heat_modal.zones.${detail.zone}`)
    : detail.zone
  const maxShotCount = detail.top_shot_types[0]?.count ?? 1
  const maxTransCount = detail.transitions[0]?.count ?? 1

  // 良い=青(WIN) / 悪い=赤(LOSS) / 中立=標準テキスト色
  const neutralText = isLight ? '#1e293b' : '#e2e8f0'
  const winRateColor = detail.win_rate == null
    ? neutralText
    : detail.win_rate >= 0.55 ? WIN
    : detail.win_rate <= 0.45 ? LOSS
    : neutralText

  return (
    <div className="space-y-5 max-w-sm">
      {/* ゾーン名・基本統計 */}
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="flex items-baseline gap-2 mb-3">
          <span className="text-lg font-bold text-gray-100">{zoneName}</span>
          <span className="text-sm text-gray-500 font-mono">({detail.zone})</span>
          <span className="text-xs text-gray-500 ml-auto">
            {mode === 'hit' ? t('court_heat_modal.zone_mode_hit') : t('court_heat_modal.zone_mode_land')}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-3 text-center">
          <div>
            <p className="text-2xl font-bold text-gray-100">{detail.count}</p>
            <p className="text-[11px] text-gray-500">{t('court_heat_modal.stat_strokes')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold" style={{ color: winRateColor }}>
              {detail.win_rate != null ? `${(detail.win_rate * 100).toFixed(0)}%` : '—'}
            </p>
            <p className="text-[11px] text-gray-500">{t('court_heat_modal.stat_win_rate')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-gray-100">{detail.wins}</p>
            <p className="text-[11px] text-gray-500">{t('court_heat_modal.stat_wins')}</p>
          </div>
        </div>
      </div>

      {/* ショットタイプ分布 */}
      {detail.top_shot_types.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-xs font-semibold text-gray-300 mb-3">
            {mode === 'hit' ? t('court_heat_modal.section_shots_from') : t('court_heat_modal.section_shots_into')}
          </p>
          <div className="space-y-2">
            {detail.top_shot_types.map(({ shot_type, count }) => {
              const ratio = count / maxShotCount
              const label = t(`shot_types.${shot_type}`, shot_type)
              return (
                <div key={shot_type} className="flex items-center gap-2">
                  <span className="text-[11px] text-gray-400 w-24 truncate">{label}</span>
                  <div className="flex-1 bg-gray-700 rounded h-3 overflow-hidden">
                    <div
                      className="h-full rounded"
                      style={{ width: `${ratio * 100}%`, backgroundColor: '#6b7280' }}
                    />
                  </div>
                  <span className="text-[11px] text-gray-400 w-6 text-right">{count}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 着地点分布（mode=hit のみ） */}
      {mode === 'hit' && detail.transitions.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-xs font-semibold text-gray-300 mb-3">
            {t('court_heat_modal.section_transitions')}
          </p>
          <div className="space-y-2">
            {detail.transitions.map(({ zone, count }) => {
              const ratio = count / maxTransCount
              const label = ZONE_KEYS.includes(zone as typeof ZONE_KEYS[number])
                ? t(`court_heat_modal.zones.${zone}`)
                : zone
              return (
                <div key={zone} className="flex items-center gap-2">
                  <span className="text-[11px] text-gray-400 w-20">{label}</span>
                  <span className="text-[10px] text-gray-600 font-mono w-6">({zone})</span>
                  <div className="flex-1 bg-gray-700 rounded h-3 overflow-hidden">
                    <div
                      className="h-full rounded"
                      style={{ width: `${ratio * 100}%`, backgroundColor: '#6b7280' }}
                    />
                  </div>
                  <span className="text-[11px] text-gray-400 w-6 text-right">{count}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {detail.count === 0 && (
        <p className="text-gray-600 text-sm text-center py-4">
          {t('court_heat_modal.zone_empty')}
        </p>
      )}
    </div>
  )
}
