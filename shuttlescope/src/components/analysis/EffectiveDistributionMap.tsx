// R-004: 有効配球マップ（得点に繋がったショットの落点ゾーン可視化）
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Maximize2 } from 'lucide-react'
import { apiGet } from '@/api/client'
import { useReviewBundleSlice } from '@/contexts/ReviewBundleContext'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'
import { WIN } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { ZoneMapModal, ZoneEffectiveness } from './ZoneMapModal'

interface EffectiveDistributionMapProps {
  playerId: number
  filters?: AnalysisFilters
}

interface EffectiveMapResponse {
  success: boolean
  data: {
    zone_effectiveness: Record<string, ZoneEffectiveness>
    top_zones: string[]
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

const ZONE_GRID: string[][] = [
  ['BL', 'BC', 'BR'],
  ['ML', 'MC', 'MR'],
  ['NL', 'NC', 'NR'],
]

const ZONE_LABELS: Record<string, string> = {
  BL: '奥左', BC: '奥中', BR: '奥右',
  ML: '中左', MC: '中央', MR: '中右',
  NL: '前左', NC: '前中', NR: '前右',
}

export function EffectiveDistributionMap({ playerId, filters = DEFAULT_FILTERS }: EffectiveDistributionMapProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const [modalOpen, setModalOpen] = useState(false)
  const [initialZone, setInitialZone] = useState<string | null>(null)

  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  // 振り返りタブ bundle 提供時はスライスを利用する
  const { slice: bundled, loading: bundleLoading, provided } = useReviewBundleSlice<EffectiveMapResponse>('effective_distribution_map')
  const indiv = useQuery({
    queryKey: ['analysis-effective-distribution-map', playerId, filters],
    queryFn: () =>
      apiGet<EffectiveMapResponse>('/analysis/effective_distribution_map', { player_id: playerId, ...fp }),
    enabled: !!playerId && !provided && !bundleLoading,
  })
  const resp = bundled ?? indiv.data
  const isLoading = provided ? bundleLoading : indiv.isLoading

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const zoneData = resp?.data?.zone_effectiveness ?? {}
  const topZones = resp?.data?.top_zones ?? []

  if (sampleSize === 0 || Object.keys(zoneData).length === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  const maxEffectiveness = Math.max(...Object.values(zoneData).map((z) => z.effectiveness), 0.001)

  function handleZoneClick(zone: string) {
    setInitialZone(zone)
    setModalOpen(true)
  }

  return (
    <>
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <ConfidenceBadge sampleSize={sampleSize} />
          <button
            onClick={() => { setInitialZone(null); setModalOpen(true) }}
            title={t('auto.EffectiveDistributionMap.k4')}
            className={`p-1 rounded transition-colors ${isLight ? 'text-gray-400 hover:bg-gray-100 hover:text-gray-600' : 'text-gray-500 hover:bg-gray-700 hover:text-gray-300'}`}
          >
            <Maximize2 size={14} />
          </button>
        </div>

        {topZones.length > 0 && (
          <div className="text-xs text-gray-400">
            {t('analysis.review.top_zone_label')}:
            <span className="ml-1 font-semibold" style={{ color: WIN }}>
              {topZones.map((z) => ZONE_LABELS[z] ?? z).join('・')}
            </span>
          </div>
        )}

        {/* ゾーングリッド（クリック可能） */}
        <div className="space-y-0.5">
          <p className="text-[10px] text-gray-500 text-center mb-1">{t('auto.EffectiveDistributionMap.k1')}</p>
          {ZONE_GRID.map((row, ri) => (
            <div key={ri} className="flex gap-0.5">
              {row.map((zone) => {
                const d = zoneData[zone]
                const intensity = d ? d.effectiveness / maxEffectiveness : 0
                const isTop = topZones.includes(zone)
                const bgColor = d
                  ? `rgba(${parseInt(WIN.slice(1, 3), 16)}, ${parseInt(WIN.slice(3, 5), 16)}, ${parseInt(WIN.slice(5, 7), 16)}, ${(intensity * 0.7).toFixed(2)})`
                  : (isLight ? '#f1f5f9' : '#374151')

                return (
                  <button
                    key={zone}
                    onClick={() => handleZoneClick(zone)}
                    className="flex-1 rounded p-1.5 text-center text-xs transition-all cursor-pointer focus:outline-none hover:ring-2 hover:ring-offset-0"
                    style={{
                      backgroundColor: bgColor,
                      border: isTop ? `1.5px solid ${WIN}` : `1px solid ${isLight ? '#e2e8f0' : 'transparent'}`,
                      minHeight: '48px',
                      // @ts-ignore
                      '--tw-ring-color': WIN,
                    }}
                  >
                    <p className="text-[10px] font-medium" style={{ color: isLight ? '#1e293b' : '#ffffff' }}>
                      {ZONE_LABELS[zone]}
                    </p>
                    {d ? (
                      <>
                        <p className="font-bold text-xs" style={{ color: WIN }}>
                          {(d.win_rate * 100).toFixed(0)}%
                        </p>
                        <p className="text-[9px]" style={{ color: isLight ? '#475569' : '#9ca3af' }}>
                          {d.win_count}得点
                        </p>
                      </>
                    ) : (
                      <p className="text-[10px]" style={{ color: isLight ? '#94a3b8' : '#6b7280' }}>—</p>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
          <p className="text-[10px] text-gray-500 text-center mt-1">
            自コート（打点）　<span className="opacity-60">{t('auto.EffectiveDistributionMap.k2')}</span>
          </p>
        </div>

        {/* 上位ゾーン詳細テーブル */}
        {topZones.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 border-b border-gray-700">
                  <th className="text-left py-1.5 pr-3">{t('analysis.effective_map.zone')}</th>
                  <th className="text-center py-1.5 pr-3">{t('auto.EffectiveDistributionMap.k3')}</th>
                  <th className="text-center py-1.5 pr-3">{t('analysis.effective_map.win_rate')}</th>
                  <th className="text-right py-1.5">{t('analysis.effective_map.effectiveness')}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(zoneData)
                  .sort((a, b) => b[1].effectiveness - a[1].effectiveness)
                  .slice(0, 5)
                  .map(([zone, d]) => (
                    <tr
                      key={zone}
                      className="border-b border-gray-700/40 hover:bg-gray-700/20 cursor-pointer"
                      onClick={() => handleZoneClick(zone)}
                    >
                      <td className="py-1.5 pr-3 font-semibold" style={{ color: topZones.includes(zone) ? WIN : undefined }}>
                        {ZONE_LABELS[zone] ?? zone}
                        {topZones.includes(zone) && <span className="ml-1 text-[9px]">★</span>}
                      </td>
                      <td className="py-1.5 pr-3 text-center text-gray-300">{d.win_count}</td>
                      <td className="py-1.5 pr-3 text-center">
                        <span className="font-semibold" style={{ color: WIN }}>{(d.win_rate * 100).toFixed(1)}%</span>
                      </td>
                      <td className="py-1.5 text-right text-gray-400">{(d.effectiveness * 100).toFixed(1)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modalOpen && (
        <ZoneMapModal
          type="effective"
          playerId={playerId}
          filters={filters}
          effectiveZoneData={zoneData}
          topZones={topZones}
          sampleSize={sampleSize}
          initialZone={initialZone}
          onClose={() => setModalOpen(false)}
        />
      )}
    </>
  )
}
