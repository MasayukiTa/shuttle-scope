/**
 * ZoneMapModal — 有効配球マップ / 被打球弱点マップ の最大化モーダル
 *
 * - 3×3 ゾーングリッドをクリックで詳細表示
 * - type='effective': 自分が飛ばしたゾーン詳細（ショット種別・打点）
 * - type='vulnerability': 相手に食らったゾーン詳細（ショット種別・打点）
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import { apiGet } from '@/api/client'
import { WIN, LOSS } from '@/styles/colors'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'

// ─── 型定義 ─────────────────────────────────────────────────────────────────

export interface ZoneEffectiveness {
  win_count: number
  total_count: number
  win_rate: number
  effectiveness: number
}

export interface ZoneVulnerability {
  loss_count: number
  total_count: number
  loss_rate: number
}

interface EffectiveZoneDetailResponse {
  success: boolean
  data: {
    zone: string
    total_count: number
    win_count: number
    win_rate: number | null
    top_shot_types: { shot_type: string; count: number }[]
    hit_zones: { zone: string; count: number }[]
  }
  meta: { sample_size: number }
}

interface VulnZoneDetailResponse {
  success: boolean
  data: {
    zone: string
    total_count: number
    loss_count: number
    loss_rate: number | null
    top_shot_types: { shot_type: string; count: number }[]
    hit_zones: { zone: string; count: number }[]
  }
  meta: { sample_size: number }
}

interface ZoneMapModalProps {
  type: 'effective' | 'vulnerability'
  playerId: number
  filters: AnalysisFilters
  /** 有効配球マップの場合 */
  effectiveZoneData?: Record<string, ZoneEffectiveness>
  topZones?: string[]
  /** 被打球弱点マップの場合 */
  vulnZoneData?: Record<string, ZoneVulnerability>
  dangerZones?: string[]
  sampleSize: number
  initialZone?: string | null
  onClose: () => void
}

// ─── 定数 ────────────────────────────────────────────────────────────────────

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

// ─── メインコンポーネント ─────────────────────────────────────────────────────

export function ZoneMapModal({
  type,
  playerId,
  filters,
  effectiveZoneData = {},
  topZones = [],
  vulnZoneData = {},
  dangerZones = [],
  sampleSize,
  initialZone = null,
  onClose,
}: ZoneMapModalProps) {
  const { t } = useTranslation()

  const { card, textHeading, textMuted, textFaint, isLight } = useCardTheme()
  const [selectedZone, setSelectedZone] = useState<string | null>(initialZone)

  const accentColor = type === 'effective' ? WIN : LOSS
  const highlightZones = type === 'effective' ? topZones : dangerZones
  const title = type === 'effective' ? '有効配球マップ — ゾーン詳細' : '被打球弱点マップ — ゾーン詳細'
  const courtLabel = type === 'effective' ? '相手コート（着地点）' : '自コート（被打球エリア）'

  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  // ゾーン詳細クエリ（クリック時のみ）
  const { data: effectiveDetail, isLoading: loadingEff } = useQuery({
    queryKey: ['effective-zone-detail', playerId, selectedZone, filters],
    queryFn: () =>
      apiGet<EffectiveZoneDetailResponse>('/analysis/effective_distribution_map/zone_detail', {
        player_id: playerId,
        zone: selectedZone!,
        ...fp,
      }),
    enabled: type === 'effective' && selectedZone != null,
  })

  const { data: vulnDetail, isLoading: loadingVuln } = useQuery({
    queryKey: ['vuln-zone-detail', playerId, selectedZone, filters],
    queryFn: () =>
      apiGet<VulnZoneDetailResponse>('/analysis/received_vulnerability/zone_detail', {
        player_id: playerId,
        zone: selectedZone!,
        ...fp,
      }),
    enabled: type === 'vulnerability' && selectedZone != null,
  })

  const detailData = type === 'effective' ? effectiveDetail?.data : vulnDetail?.data
  const loadingDetail = type === 'effective' ? loadingEff : loadingVuln

  // ゾーンの intensity 計算
  function getIntensity(zone: string): number {
    if (type === 'effective') {
      const d = effectiveZoneData[zone]
      if (!d) return 0
      const maxEff = Math.max(...Object.values(effectiveZoneData).map((z) => z.effectiveness), 0.001)
      return d.effectiveness / maxEff
    } else {
      const d = vulnZoneData[zone]
      if (!d) return 0
      const maxRate = Math.max(...Object.values(vulnZoneData).map((z) => z.loss_rate), 0.001)
      return d.loss_rate / maxRate
    }
  }

  function getZoneBg(zone: string): string {
    const intensity = getIntensity(zone)
    if (intensity === 0) return isLight ? '#f1f5f9' : '#374151'
    const r = parseInt(accentColor.slice(1, 3), 16)
    const g = parseInt(accentColor.slice(3, 5), 16)
    const b = parseInt(accentColor.slice(5, 7), 16)
    return `rgba(${r}, ${g}, ${b}, ${(intensity * 0.65).toFixed(2)})`
  }

  function getZoneLabel(zone: string): React.ReactNode {
    if (type === 'effective') {
      const d = effectiveZoneData[zone]
      if (!d) return <span className="text-[10px]" style={{ color: isLight ? '#94a3b8' : '#6b7280' }}>—</span>
      return (
        <>
          <p className="font-bold text-sm" style={{ color: WIN }}>{(d.win_rate * 100).toFixed(0)}%</p>
          <p className="text-[10px]" style={{ color: isLight ? '#475569' : '#9ca3af' }}>{d.win_count}得点</p>
        </>
      )
    } else {
      const d = vulnZoneData[zone]
      if (!d) return <span className="text-[10px]" style={{ color: isLight ? '#94a3b8' : '#6b7280' }}>—</span>
      return (
        <>
          <p className="font-bold text-sm" style={{ color: LOSS }}>{(d.loss_rate * 100).toFixed(0)}%</p>
          <p className="text-[10px]" style={{ color: isLight ? '#475569' : '#9ca3af' }}>{d.loss_count}失点</p>
        </>
      )
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/85 flex flex-col">
      {/* ヘッダー */}
      <div className={`flex items-center justify-between px-6 py-3 border-b shrink-0 ${isLight ? 'bg-white border-gray-200' : 'bg-gray-900 border-gray-700'}`}>
        <div>
          <span className={`font-semibold text-base ${textHeading}`}>{title}</span>
          <span className={`ml-3 text-xs ${textMuted}`}>N={sampleSize}</span>
        </div>
        <button
          onClick={onClose}
          className={`p-1.5 rounded transition-colors ${isLight ? 'text-gray-500 hover:bg-gray-100 hover:text-gray-700' : 'text-gray-400 hover:bg-gray-700 hover:text-white'}`}
          title={t('auto.ZoneMapModal.k5')}
        >
          <X size={18} />
        </button>
      </div>

      {/* コンテンツ */}
      <div className={`flex-1 overflow-auto ${isLight ? 'bg-gray-50' : 'bg-gray-900'}`}>
        <div className="flex flex-col lg:flex-row gap-6 p-6 min-h-full max-w-4xl mx-auto">

          {/* 左: ゾーングリッド */}
          <div className="flex flex-col items-center gap-3 lg:w-72 shrink-0">
            <p className={`text-xs ${textMuted}`}>{courtLabel}</p>
            <div className="w-full space-y-1.5">
              {ZONE_GRID.map((row, ri) => (
                <div key={ri} className="flex gap-1.5">
                  {row.map((zone) => {
                    const isHighlight = highlightZones.includes(zone)
                    const isSelected = selectedZone === zone
                    return (
                      <button
                        key={zone}
                        onClick={() => setSelectedZone(zone === selectedZone ? null : zone)}
                        className="flex-1 rounded-lg p-2 text-center transition-all cursor-pointer focus:outline-none"
                        style={{
                          backgroundColor: getZoneBg(zone),
                          border: isSelected
                            ? `2px solid ${accentColor}`
                            : isHighlight
                            ? `1.5px solid ${accentColor}`
                            : `1px solid ${isLight ? '#e2e8f0' : 'transparent'}`,
                          minHeight: '72px',
                          boxShadow: isSelected ? `0 0 0 2px ${accentColor}40` : undefined,
                        }}
                      >
                        <p className="text-xs font-semibold mb-1" style={{ color: isLight ? '#1e293b' : '#ffffff' }}>
                          {ZONE_LABELS[zone]}
                        </p>
                        {getZoneLabel(zone)}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
            <p className={`text-[10px] ${textFaint}`}>
              {type === 'effective' ? '← 自コート（打点）' : '← 相手コート（打点）'}
            </p>
            <p className={`text-[10px] ${textFaint}`}>{t('auto.ZoneMapModal.k1')}</p>
          </div>

          {/* 右: ゾーン詳細パネル */}
          <div className="flex-1 min-w-0">
            {selectedZone == null ? (
              <div className={`flex items-center justify-center h-full min-h-[200px] rounded-lg ${isLight ? 'bg-gray-100' : 'bg-gray-800'}`}>
                <p className={`text-sm text-center ${textMuted}`}>
                  左のゾーンをクリックすると<br />詳細が表示されます
                </p>
              </div>
            ) : loadingDetail ? (
              <div className={`flex items-center justify-center h-full min-h-[200px] rounded-lg ${isLight ? 'bg-gray-100' : 'bg-gray-800'}`}>
                <p className={`text-sm ${textMuted}`}>{t('auto.ZoneMapModal.k2')}</p>
              </div>
            ) : detailData ? (
              <ZoneDetailPanel
                type={type}
                data={detailData as any}
                isLight={isLight}
                card={card}
                textHeading={textHeading}
                textMuted={textMuted}
                textFaint={textFaint}
              />
            ) : null}
          </div>

        </div>
      </div>
    </div>
  )
}

// ─── ゾーン詳細パネル ─────────────────────────────────────────────────────────

interface ZoneDetailPanelProps {
  type: 'effective' | 'vulnerability'
  data: {
    zone: string
    total_count: number
    win_count?: number
    loss_count?: number
    win_rate?: number | null
    loss_rate?: number | null
    top_shot_types: { shot_type: string; count: number }[]
    hit_zones: { zone: string; count: number }[]
  }
  isLight: boolean
  card: string
  textHeading: string
  textMuted: string
  textFaint: string
}

function ZoneDetailPanel({ type, data, isLight, card, textHeading, textMuted, textFaint }: ZoneDetailPanelProps) {
  const { t } = useTranslation()
  const zoneName = ZONE_LABELS[data.zone] ?? data.zone
  const accentColor = type === 'effective' ? WIN : LOSS
  const rateValue = type === 'effective' ? data.win_rate : data.loss_rate
  const countValue = type === 'effective' ? data.win_count : data.loss_count
  const rateLabel = type === 'effective' ? '得点率' : '失点率'
  const countLabel = type === 'effective' ? '得点数' : '失点数'
  const shotLabel = type === 'effective' ? 'このゾーンへ配球したショット' : 'このゾーンへの相手ショット'
  const hitZoneLabel = type === 'effective' ? 'このゾーンへ打った打点（自コート）' : 'このゾーンへ打った相手の打点'

  const maxShotCount = data.top_shot_types[0]?.count ?? 1
  const maxHitCount = data.hit_zones[0]?.count ?? 1

  const barBg = isLight ? '#e2e8f0' : '#374151'

  return (
    <div className="space-y-4">
      {/* 基本統計 */}
      <div className={`${card} rounded-lg p-4`}>
        <div className="flex items-baseline gap-2 mb-3">
          <span className={`text-lg font-bold ${textHeading}`}>{zoneName}</span>
          <span className={`text-sm font-mono ${textMuted}`}>({data.zone})</span>
        </div>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div>
            <p className={`text-2xl font-bold ${textHeading}`}>{data.total_count}</p>
            <p className={`text-[11px] ${textMuted}`}>{t('auto.ZoneMapModal.k3')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold" style={{ color: accentColor }}>
              {rateValue != null ? `${(rateValue * 100).toFixed(0)}%` : '—'}
            </p>
            <p className={`text-[11px] ${textMuted}`}>{rateLabel}</p>
          </div>
          <div>
            <p className="text-2xl font-bold" style={{ color: accentColor }}>{countValue ?? 0}</p>
            <p className={`text-[11px] ${textMuted}`}>{countLabel}</p>
          </div>
        </div>
      </div>

      {/* ショット種別分布 */}
      {data.top_shot_types.length > 0 && (
        <div className={`${card} rounded-lg p-4`}>
          <p className={`text-xs font-semibold ${textHeading} mb-3`}>{shotLabel}</p>
          <div className="space-y-2">
            {data.top_shot_types.map(({ shot_type, count }) => {
              const ratio = count / maxShotCount
              const label = t(`shot_types.${shot_type}`, shot_type)
              return (
                <div key={shot_type} className="flex items-center gap-2">
                  <span className={`text-[11px] ${textMuted} w-28 truncate`}>{label}</span>
                  <div className="flex-1 rounded h-3 overflow-hidden" style={{ backgroundColor: barBg }}>
                    <div
                      className="h-full rounded"
                      style={{ width: `${ratio * 100}%`, backgroundColor: accentColor, opacity: 0.75 }}
                    />
                  </div>
                  <span className={`text-[11px] ${textFaint} w-6 text-right`}>{count}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 打点分布（どこから打ったか） */}
      {data.hit_zones.length > 0 && (
        <div className={`${card} rounded-lg p-4`}>
          <p className={`text-xs font-semibold ${textHeading} mb-3`}>{hitZoneLabel}</p>
          <div className="space-y-1.5">
            {data.hit_zones.map(({ zone, count }) => {
              const ratio = count / maxHitCount
              const label = ZONE_LABELS[zone] ?? zone
              return (
                <div key={zone} className="flex items-center gap-2">
                  <span className={`text-[11px] ${textMuted} w-12`}>{label}</span>
                  <span className={`text-[10px] font-mono ${textFaint} w-8`}>({zone})</span>
                  <div className="flex-1 rounded h-3 overflow-hidden" style={{ backgroundColor: barBg }}>
                    <div
                      className="h-full rounded"
                      style={{ width: `${ratio * 100}%`, backgroundColor: isLight ? '#64748b' : '#6b7280' }}
                    />
                  </div>
                  <span className={`text-[11px] ${textFaint} w-6 text-right`}>{count}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {data.total_count === 0 && (
        <p className={`text-sm text-center py-4 ${textMuted}`}>{t('auto.ZoneMapModal.k4')}</p>
      )}
    </div>
  )
}
