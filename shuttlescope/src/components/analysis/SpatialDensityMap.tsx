// コート密度ヒートマップ — ガウシアンカーネル連続化ゾーン密度をSVGで表示
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { seqBlue } from '@/styles/colors'
import { useTranslation } from 'react-i18next'

interface SpatialDensityMapProps {
  playerId: number
}

interface Response {
  success: boolean
  data: {
    grid: number[][]
    grid_width: number
    grid_height: number
    zone_counts: Record<string, number>
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

// SVG描画サイズ
const SVG_W = 180
const SVG_H = 360

export function SpatialDensityMap({ playerId }: SpatialDensityMapProps) {
  const { t } = useTranslation()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-spatial-density', playerId],
    queryFn: () => apiGet<Response>('/analysis/spatial_density', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">{t('auto.SpatialDensityMap.k1')}</h3>
        <div className="text-gray-500 text-sm py-4 text-center">{t('auto.SpatialDensityMap.k2')}</div>
      </div>
    )
  }

  const d = resp?.data
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (!d || sampleSize === 0) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">{t('auto.SpatialDensityMap.k1')}</h3>
        <NoDataMessage sampleSize={sampleSize} minRequired={5} unit="ストローク" />
      </div>
    )
  }

  const { grid, grid_width: gw, grid_height: gh, zone_counts } = d
  const cellW = SVG_W / gw
  const cellH = SVG_H / gh

  // グリッドセルをSVGパスに変換（密度0のセルはスキップ）
  const cells: { x: number; y: number; w: number; h: number; v: number }[] = []
  for (let row = 0; row < gh; row++) {
    for (let col = 0; col < gw; col++) {
      const v = grid[row]?.[col] ?? 0
      if (v < 0.01) continue
      cells.push({ x: col * cellW, y: row * cellH, w: cellW, h: cellH, v })
    }
  }

  // ゾーン総数
  const totalZoneCount = Object.values(zone_counts).reduce((a, b) => a + b, 0)

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-200 mb-3">{t('auto.SpatialDensityMap.k1')}</h3>
      <ConfidenceBadge sampleSize={sampleSize} />

      <div className="mt-3 flex gap-4 items-start">
        {/* SVGコート */}
        <div className="shrink-0">
          <svg
            width={SVG_W}
            height={SVG_H}
            viewBox={`0 0 ${SVG_W} ${SVG_H}`}
            className="rounded border border-gray-600"
          >
            {/* コート背景 */}
            <rect width={SVG_W} height={SVG_H} fill="#1a2533" />

            {/* 密度セル */}
            {cells.map((c, i) => (
              <rect
                key={i}
                x={c.x}
                y={c.y}
                width={c.w}
                height={c.h}
                fill={seqBlue(c.v)}
                opacity={0.85}
              />
            ))}

            {/* コートライン */}
            <rect x={0} y={0} width={SVG_W} height={SVG_H} fill="none" stroke="#4b5563" strokeWidth={1} />
            {/* ネット */}
            <line x1={0} y1={SVG_H / 2} x2={SVG_W} y2={SVG_H / 2} stroke="#9ca3af" strokeWidth={1.5} />
            {/* 1/3ライン */}
            <line x1={0} y1={SVG_H / 3} x2={SVG_W} y2={SVG_H / 3} stroke="#374151" strokeWidth={0.5} strokeDasharray="4,4" />
            <line x1={0} y1={SVG_H * 2 / 3} x2={SVG_W} y2={SVG_H * 2 / 3} stroke="#374151" strokeWidth={0.5} strokeDasharray="4,4" />
            {/* 縦分割 */}
            <line x1={SVG_W / 3} y1={0} x2={SVG_W / 3} y2={SVG_H} stroke="#374151" strokeWidth={0.5} strokeDasharray="4,4" />
            <line x1={SVG_W * 2 / 3} y1={0} x2={SVG_W * 2 / 3} y2={SVG_H} stroke="#374151" strokeWidth={0.5} strokeDasharray="4,4" />

            {/* ラベル */}
            <text x={SVG_W / 2} y={SVG_H / 4} textAnchor="middle" fill="#6b7280" fontSize={9}>{t('auto.SpatialDensityMap.k3')}</text>
            <text x={SVG_W / 2} y={SVG_H * 3 / 4} textAnchor="middle" fill="#6b7280" fontSize={9}>{t('auto.SpatialDensityMap.k4')}</text>
          </svg>
        </div>

        {/* ゾーン別カウント */}
        <div className="flex-1 min-w-0">
          <p className="text-xs text-gray-400 mb-2">{t('auto.SpatialDensityMap.k5')}</p>
          <div className="space-y-1">
            {Object.entries(zone_counts)
              .sort(([, a], [, b]) => b - a)
              .map(([zone, count]) => {
                const ratio = totalZoneCount > 0 ? count / totalZoneCount : 0
                return (
                  <div key={zone} className="flex items-center gap-2 text-xs">
                    <span className="w-8 text-gray-400 font-mono">{zone}</span>
                    <div className="flex-1 bg-gray-700 rounded h-3 overflow-hidden">
                      <div
                        className="h-full rounded"
                        style={{ width: `${ratio * 100}%`, backgroundColor: seqBlue(ratio * 3) }}
                      />
                    </div>
                    <span className="text-gray-400 w-6 text-right">{count}</span>
                  </div>
                )
              })}
          </div>
        </div>
      </div>

      {/* カラースケール凡例 */}
      <div className="mt-3 flex items-center gap-2">
        <span className="text-xs text-gray-500">{t('auto.SpatialDensityMap.k6')}</span>
        <div
          className="flex-1 h-2 rounded"
          style={{
            background: `linear-gradient(to right, ${seqBlue(0)}, ${seqBlue(0.5)}, ${seqBlue(1)})`,
          }}
        />
        <span className="text-xs text-gray-500">{t('auto.SpatialDensityMap.k7')}</span>
      </div>
    </div>
  )
}
