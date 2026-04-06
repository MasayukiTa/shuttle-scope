import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { Zone9 } from '@/types'

// SVG仕様: viewBox "0 0 300 400"（縦長）
// 上半分（y:0-200）: 相手コート（着地点選択）
// 下半分（y:200-400）: 自コート（打点選択）
const SVG_WIDTH = 300
const SVG_HEIGHT = 400

interface ZoneRect {
  zone: Zone9
  x: number
  y: number
  w: number
  h: number
}

// 相手コート（上半分）のゾーン座標
const OPPONENT_ZONES: ZoneRect[] = [
  { zone: 'BL', x: 0,   y: 0,  w: 100, h: 67 },
  { zone: 'BC', x: 100, y: 0,  w: 100, h: 67 },
  { zone: 'BR', x: 200, y: 0,  w: 100, h: 67 },
  { zone: 'ML', x: 0,   y: 67, w: 100, h: 67 },
  { zone: 'MC', x: 100, y: 67, w: 100, h: 67 },
  { zone: 'MR', x: 200, y: 67, w: 100, h: 67 },
  { zone: 'NL', x: 0,   y: 134, w: 100, h: 66 },
  { zone: 'NC', x: 100, y: 134, w: 100, h: 66 },
  { zone: 'NR', x: 200, y: 134, w: 100, h: 66 },
]

// 自コート（下半分）のゾーン座標（上下反転: Nが上=ネット側）
const OWN_ZONES: ZoneRect[] = [
  { zone: 'NL', x: 0,   y: 200, w: 100, h: 66 },
  { zone: 'NC', x: 100, y: 200, w: 100, h: 66 },
  { zone: 'NR', x: 200, y: 200, w: 100, h: 66 },
  { zone: 'ML', x: 0,   y: 266, w: 100, h: 67 },
  { zone: 'MC', x: 100, y: 266, w: 100, h: 67 },
  { zone: 'MR', x: 200, y: 266, w: 100, h: 67 },
  { zone: 'BL', x: 0,   y: 333, w: 100, h: 67 },
  { zone: 'BC', x: 100, y: 333, w: 100, h: 67 },
  { zone: 'BR', x: 200, y: 333, w: 100, h: 67 },
]

interface CourtDiagramProps {
  mode: 'hit' | 'land'                        // 打点(自コート) or 着地点(相手コート)
  selectedZone: Zone9 | null
  onZoneSelect: (zone: Zone9) => void
  heatmapData?: Record<string, number>         // ゾーン別数値（解析画面用）
  showLabels?: boolean
  interactive?: boolean                         // アノテーション時はtrue
  label?: string                               // コート上部のラベル
}

// matplotlib coolwarm の5制御点（RGB 0-255）
const COOLWARM_STOPS = [
  [59,  76,  192],  // t=0.00  deep blue
  [141, 176, 254],  // t=0.25  light blue
  [221, 221, 221],  // t=0.50  near white
  [243, 138, 100],  // t=0.75  salmon
  [180,   4,  38],  // t=1.00  deep red
]

function getHeatmapColor(value: number, max: number): string {
  if (max === 0 || value < 0) return 'rgba(59,76,192,0.80)'
  // sqrt正規化: 分布の偏りを緩和して中間色（白/サーモン）が適切に出るようにする
  const ratio = Math.sqrt(Math.min(value / max, 1))

  // 4区間から該当区間を選んで線形補間
  const seg = Math.min(Math.floor(ratio * 4), 3)
  const t = ratio * 4 - seg  // 区間内の位置 0→1
  const [r1, g1, b1] = COOLWARM_STOPS[seg]
  const [r2, g2, b2] = COOLWARM_STOPS[seg + 1]
  const r = Math.round(r1 + (r2 - r1) * t)
  const g = Math.round(g1 + (g2 - g1) * t)
  const b = Math.round(b1 + (b2 - b1) * t)
  return `rgba(${r},${g},${b},0.85)`
}

export function CourtDiagram({
  mode,
  selectedZone,
  onZoneSelect,
  heatmapData,
  showLabels = true,
  interactive = true,
  label,
}: CourtDiagramProps) {
  const { t } = useTranslation()

  // modeに応じて表示するゾーン半分を決定
  const activeZones = mode === 'land' ? OPPONENT_ZONES : OWN_ZONES
  const inactiveZones = mode === 'land' ? OWN_ZONES : OPPONENT_ZONES

  const heatmapMax = heatmapData
    ? Math.max(...Object.values(heatmapData), 1)
    : 0

  const renderZone = (z: ZoneRect, isActive: boolean) => {
    const isSelected = selectedZone === z.zone && isActive
    const heatValue = heatmapData?.[z.zone] ?? 0

    let fillColor = 'rgba(255,255,255,0.03)'
    if (heatmapData) {
      fillColor = getHeatmapColor(heatValue, heatmapMax)
    } else if (isSelected) {
      fillColor = 'rgba(59,130,246,0.6)'  // 選択中: 青
    } else if (isActive) {
      fillColor = 'rgba(255,255,255,0.05)'
    }

    return (
      <g key={`${z.zone}-${z.y}`}>
        <rect
          x={z.x + 1}
          y={z.y + 1}
          width={z.w - 2}
          height={z.h - 2}
          fill={fillColor}
          stroke={isSelected ? '#3b82f6' : isActive ? '#4b5563' : '#374151'}
          strokeWidth={isSelected ? 2 : 1}
          className={clsx(isActive && interactive && 'cursor-pointer')}
          onClick={isActive && interactive ? () => onZoneSelect(z.zone) : undefined}
        />
        {showLabels && (
          <text
            x={z.x + z.w / 2}
            y={z.y + z.h / 2 + 5}
            textAnchor="middle"
            fontSize="11"
            fill={isSelected ? '#fff' : isActive ? '#9ca3af' : '#4b5563'}
            fontFamily="monospace"
            pointerEvents="none"
          >
            {z.zone}
          </text>
        )}
        {heatmapData && heatValue > 0 && (
          <text
            x={z.x + z.w / 2}
            y={z.y + z.h / 2 + 18}
            textAnchor="middle"
            fontSize="9"
            fill="rgba(255,255,255,0.7)"
            pointerEvents="none"
          >
            {heatValue}
          </text>
        )}
      </g>
    )
  }

  return (
    <div className="flex flex-col items-center gap-1">
      {label && (
        <span className="text-xs text-gray-400">{label}</span>
      )}
      <svg
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        width="100%"
        style={{ maxWidth: 200 }}
        className="select-none"
      >
        {/* 相手コートゾーン（上半分） */}
        {OPPONENT_ZONES.map((z) => renderZone(z, mode === 'land'))}

        {/* ネットライン */}
        <line
          x1={0} y1={200} x2={SVG_WIDTH} y2={200}
          stroke="#6b7280"
          strokeWidth={3}
        />
        <text x={SVG_WIDTH / 2} y={197} textAnchor="middle" fontSize="9" fill="#6b7280">ネット</text>

        {/* 自コートゾーン（下半分） */}
        {OWN_ZONES.map((z) => renderZone(z, mode === 'hit'))}

        {/* コート外枠 */}
        <rect
          x={0} y={0}
          width={SVG_WIDTH} height={SVG_HEIGHT}
          fill="none"
          stroke="#374151"
          strokeWidth={2}
        />

        {/* コートラベル */}
        <text x={SVG_WIDTH / 2} y={14} textAnchor="middle" fontSize="9" fill="#6b7280">
          相手コート（着地点）
        </text>
        <text x={SVG_WIDTH / 2} y={395} textAnchor="middle" fontSize="9" fill="#6b7280">
          自コート（打点）
        </text>
      </svg>
    </div>
  )
}
