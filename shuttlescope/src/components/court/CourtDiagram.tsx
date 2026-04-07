import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { Zone9, ZoneOOB, ZoneNet, LandZone } from '@/types'
import { seqBlue } from '@/styles/colors'

// SVG仕様: viewBox "0 0 300 400"（縦長）
// 上半分（y:0-200）: 相手コート（着地点選択）
// 下半分（y:200-400）: 自コート（打点選択）
// OOB表示時: viewBox "-50 -50 400 490" に拡張（上下左右にOOBフレームを追加）
const SVG_WIDTH = 300
const SVG_HEIGHT = 400
const OOB_MARGIN_TOP = 50     // バックライン外
const OOB_MARGIN_SIDE = 50    // サイドライン外
const OOB_MARGIN_BOTTOM = 40  // ネット前（ショートサービスライン内）

function heatmapTextColor(value: number, max: number): string {
  if (max === 0) return '#374151'
  const ratio = value / max
  return ratio >= 0.65 ? '#ffffff' : '#1e3a5f'
}

interface ZoneRect {
  zone: Zone9
  x: number
  y: number
  w: number
  h: number
}

interface OOBRect {
  zone: ZoneOOB
  x: number
  y: number
  w: number
  h: number
  label: string
}

interface NetRect {
  zone: ZoneNet
  x: number
  y: number
  w: number
  h: number
}

// ネット接触ゾーン: ネットライン（y=200）上に3分割で配置
const NET_ZONE_RECTS: NetRect[] = [
  { zone: 'NET_L', x: 0,   y: 193, w: 100, h: 14 },
  { zone: 'NET_C', x: 100, y: 193, w: 100, h: 14 },
  { zone: 'NET_R', x: 200, y: 193, w: 100, h: 14 },
]

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

// OOBゾーン座標（コート座標系でコート外側）
// modeに応じてコートの上半分/下半分の外側に表示
// mode='land' → 相手コート（上半分）の外側にOOBを表示
// mode='hit'  → 自コート（下半分）の外側にOOBを表示
function buildOOBZones(mode: 'land' | 'hit'): OOBRect[] {
  if (mode === 'land') {
    // 相手コート（上、y:0-200）の外側
    return [
      // バックライン外（上）
      { zone: 'OB_BL', x: 0,   y: -OOB_MARGIN_TOP, w: 100, h: OOB_MARGIN_TOP, label: 'OUT' },
      { zone: 'OB_BC', x: 100, y: -OOB_MARGIN_TOP, w: 100, h: OOB_MARGIN_TOP, label: 'OUT' },
      { zone: 'OB_BR', x: 200, y: -OOB_MARGIN_TOP, w: 100, h: OOB_MARGIN_TOP, label: 'OUT' },
      // 左サイド外
      { zone: 'OB_LL', x: -OOB_MARGIN_SIDE, y: 0,   w: OOB_MARGIN_SIDE, h: 67,  label: 'OUT' },
      { zone: 'OB_LM', x: -OOB_MARGIN_SIDE, y: 67,  w: OOB_MARGIN_SIDE, h: 67,  label: 'OUT' },
      { zone: 'OB_LN', x: -OOB_MARGIN_SIDE, y: 134, w: OOB_MARGIN_SIDE, h: 66,  label: 'OUT' },
      // 右サイド外
      { zone: 'OB_RL', x: SVG_WIDTH, y: 0,   w: OOB_MARGIN_SIDE, h: 67,  label: 'OUT' },
      { zone: 'OB_RM', x: SVG_WIDTH, y: 67,  w: OOB_MARGIN_SIDE, h: 67,  label: 'OUT' },
      { zone: 'OB_RN', x: SVG_WIDTH, y: 134, w: OOB_MARGIN_SIDE, h: 66,  label: 'OUT' },
      // ネット前（下、ショートサービスライン内に落下）
      { zone: 'OB_FL', x: 0,   y: 200, w: 150, h: OOB_MARGIN_BOTTOM, label: 'SHORT' },
      { zone: 'OB_FR', x: 150, y: 200, w: 150, h: OOB_MARGIN_BOTTOM, label: 'SHORT' },
    ]
  } else {
    // 自コート（下、y:200-400）の外側
    return [
      // ネット前（上、ショートサービスライン内に落下）
      { zone: 'OB_FL', x: 0,   y: 200 - OOB_MARGIN_BOTTOM, w: 150, h: OOB_MARGIN_BOTTOM, label: 'SHORT' },
      { zone: 'OB_FR', x: 150, y: 200 - OOB_MARGIN_BOTTOM, w: 150, h: OOB_MARGIN_BOTTOM, label: 'SHORT' },
      // 左サイド外
      { zone: 'OB_LL', x: -OOB_MARGIN_SIDE, y: 200, w: OOB_MARGIN_SIDE, h: 66,  label: 'OUT' },
      { zone: 'OB_LM', x: -OOB_MARGIN_SIDE, y: 266, w: OOB_MARGIN_SIDE, h: 67,  label: 'OUT' },
      { zone: 'OB_LN', x: -OOB_MARGIN_SIDE, y: 333, w: OOB_MARGIN_SIDE, h: 67,  label: 'OUT' },
      // 右サイド外
      { zone: 'OB_RL', x: SVG_WIDTH, y: 200, w: OOB_MARGIN_SIDE, h: 66,  label: 'OUT' },
      { zone: 'OB_RM', x: SVG_WIDTH, y: 266, w: OOB_MARGIN_SIDE, h: 67,  label: 'OUT' },
      { zone: 'OB_RN', x: SVG_WIDTH, y: 333, w: OOB_MARGIN_SIDE, h: 67,  label: 'OUT' },
      // バックライン外（下）
      { zone: 'OB_BL', x: 0,   y: SVG_HEIGHT, w: 100, h: OOB_MARGIN_TOP, label: 'OUT' },
      { zone: 'OB_BC', x: 100, y: SVG_HEIGHT, w: 100, h: OOB_MARGIN_TOP, label: 'OUT' },
      { zone: 'OB_BR', x: 200, y: SVG_HEIGHT, w: 100, h: OOB_MARGIN_TOP, label: 'OUT' },
    ]
  }
}

interface CourtDiagramProps {
  mode: 'hit' | 'land'
  selectedZone: LandZone | null
  onZoneSelect: (zone: LandZone) => void
  heatmapData?: Record<string, number>
  showLabels?: boolean
  interactive?: boolean
  label?: string
  maxWidth?: number
  maxHeight?: number
  /** OOBゾーン（アウト枠）を表示するか — アノテーション落点選択時のみtrue */
  showOOB?: boolean
  playerSides?: { top: 'a' | 'b'; bottom: 'a' | 'b' }
  activePlayer?: 'a' | 'b'
}

function getHeatmapColor(value: number, max: number): string {
  if (max === 0) return seqBlue(0)
  const ratio = Math.max(0, Math.min(value / max, 1))
  return seqBlue(ratio)
}

export function CourtDiagram({
  mode,
  selectedZone,
  onZoneSelect,
  heatmapData,
  showLabels = true,
  interactive = true,
  label,
  maxWidth = 200,
  maxHeight,
  showOOB = false,
  playerSides,
  activePlayer,
}: CourtDiagramProps) {
  const { t } = useTranslation()

  const activeZones = mode === 'land' ? OPPONENT_ZONES : OWN_ZONES
  const inactiveZones = mode === 'land' ? OWN_ZONES : OPPONENT_ZONES

  const heatmapMax = heatmapData
    ? Math.max(...Object.values(heatmapData), 1)
    : 0

  const PLAYER_A_COLOR = 'rgba(59,130,246,0.12)'
  const PLAYER_A_ACTIVE = 'rgba(59,130,246,0.22)'
  const PLAYER_B_COLOR = 'rgba(234,88,12,0.12)'
  const PLAYER_B_ACTIVE = 'rgba(234,88,12,0.22)'

  function halfFill(side: 'top' | 'bottom'): string {
    if (!playerSides) return 'none'
    const who = playerSides[side]
    const isActive = who === activePlayer
    if (who === 'a') return isActive ? PLAYER_A_ACTIVE : PLAYER_A_COLOR
    return isActive ? PLAYER_B_ACTIVE : PLAYER_B_COLOR
  }

  const renderZone = (z: ZoneRect, isActive: boolean) => {
    const isSelected = selectedZone === z.zone && isActive
    const heatValue = heatmapData?.[z.zone] ?? 0

    let fillColor = 'rgba(255,255,255,0.03)'
    if (heatmapData) {
      // ヒートマップ表示時: アクティブ半面のみ密度色、非アクティブ半面は薄グレーで無効表示
      fillColor = isActive
        ? getHeatmapColor(heatValue, heatmapMax)
        : 'rgba(55,65,81,0.5)'
    } else if (isSelected) {
      fillColor = 'rgba(59,130,246,0.6)'
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
          stroke={isSelected ? '#3b82f6' : isActive ? '#4b5563' : '#2d3748'}
          strokeWidth={isSelected ? 2 : 1}
          className={clsx(isActive && interactive && 'cursor-pointer')}
          onClick={isActive && interactive ? () => onZoneSelect(z.zone) : undefined}
        />
        {/* ゾーンラベル: 非アクティブ半面はヒートマップ時に非表示 */}
        {showLabels && (!heatmapData || isActive) && (
          <text
            x={z.x + z.w / 2}
            y={z.y + z.h / 2 + (heatmapData && heatValue > 0 ? 0 : 5)}
            textAnchor="middle"
            fontSize="12"
            fontWeight={heatmapData ? '700' : '400'}
            fill={
              heatmapData
                ? heatmapTextColor(heatValue, heatmapMax)
                : isSelected ? '#fff' : isActive ? '#9ca3af' : '#4b5563'
            }
            fontFamily="monospace"
            pointerEvents="none"
          >
            {z.zone}
          </text>
        )}
        {/* カウント数値: アクティブ半面のみ */}
        {heatmapData && isActive && heatValue > 0 && (
          <text
            x={z.x + z.w / 2}
            y={z.y + z.h / 2 + 16}
            textAnchor="middle"
            fontSize="11"
            fontWeight="600"
            fill={heatmapTextColor(heatValue, heatmapMax)}
            pointerEvents="none"
          >
            {heatValue}
          </text>
        )}
      </g>
    )
  }

  const renderOOBZone = (z: OOBRect) => {
    const isSelected = selectedZone === z.zone
    const isShort = z.zone === 'OB_FL' || z.zone === 'OB_FR'
    const fillColor = isSelected
      ? (isShort ? 'rgba(234,179,8,0.7)' : 'rgba(239,68,68,0.7)')
      : (isShort ? 'rgba(234,179,8,0.15)' : 'rgba(239,68,68,0.15)')
    const strokeColor = isSelected
      ? (isShort ? '#eab308' : '#ef4444')
      : (isShort ? '#ca8a04' : '#dc2626')

    return (
      <g key={z.zone}>
        <rect
          x={z.x + 1}
          y={z.y + 1}
          width={z.w - 2}
          height={z.h - 2}
          fill={fillColor}
          stroke={strokeColor}
          strokeWidth={isSelected ? 2 : 1}
          strokeDasharray={isSelected ? undefined : '3 2'}
          className="cursor-pointer"
          onClick={() => onZoneSelect(z.zone)}
        />
        <text
          x={z.x + z.w / 2}
          y={z.y + z.h / 2 + 4}
          textAnchor="middle"
          fontSize="9"
          fontWeight="600"
          fill={isSelected ? '#fff' : (isShort ? '#fbbf24' : '#f87171')}
          fontFamily="monospace"
          pointerEvents="none"
        >
          {z.label}
        </text>
      </g>
    )
  }

  const renderNetZone = (z: NetRect) => {
    const isSelected = selectedZone === z.zone
    return (
      <g key={z.zone}>
        <rect
          x={z.x + 1}
          y={z.y}
          width={z.w - 2}
          height={z.h}
          fill={isSelected ? 'rgba(251,146,60,0.85)' : 'rgba(251,146,60,0.25)'}
          stroke={isSelected ? '#fb923c' : '#ea580c'}
          strokeWidth={isSelected ? 2 : 1}
          className="cursor-pointer"
          onClick={() => onZoneSelect(z.zone)}
        />
        <text
          x={z.x + z.w / 2}
          y={z.y + z.h / 2 + 3}
          textAnchor="middle"
          fontSize="7"
          fontWeight="700"
          fill={isSelected ? '#fff' : '#fdba74'}
          fontFamily="monospace"
          pointerEvents="none"
        >
          NET
        </text>
      </g>
    )
  }

  // OOB表示時はviewBoxを拡張（上下左右にマージンを追加）
  const oobZones = showOOB ? buildOOBZones(mode) : []
  const vbLeft = showOOB ? -OOB_MARGIN_SIDE : 0
  const vbTop = showOOB ? -OOB_MARGIN_TOP : 0
  const vbWidth = showOOB ? SVG_WIDTH + OOB_MARGIN_SIDE * 2 : SVG_WIDTH
  const vbHeight = showOOB ? SVG_HEIGHT + OOB_MARGIN_TOP + OOB_MARGIN_BOTTOM : SVG_HEIGHT

  // SVGの表示サイズ（アスペクト比を維持）
  const aspectRatio = vbWidth / vbHeight

  return (
    <div className="flex flex-col items-center gap-1">
      {label && (
        <span className="text-xs text-gray-400">{label}</span>
      )}
      {!showOOB && <span className="text-[10px] text-gray-500">相手コート（着地点）</span>}
      <svg
        viewBox={`${vbLeft} ${vbTop} ${vbWidth} ${vbHeight}`}
        style={
          maxHeight
            ? {
                height: maxHeight,
                width: Math.round(maxHeight * aspectRatio),
                maxWidth: '100%',
                display: 'block',
              }
            : {
                width: '100%',
                maxWidth: showOOB ? maxWidth + 40 : maxWidth,
                display: 'block',
              }
        }
        className="select-none"
      >
        {/* OOBゾーン（コート外フレーム） */}
        {oobZones.map(renderOOBZone)}

        {/* 選手コートカラーオーバーレイ */}
        {playerSides && (
          <>
            <rect x={0} y={0} width={SVG_WIDTH} height={200} fill={halfFill('top')} pointerEvents="none" />
            <rect x={0} y={200} width={SVG_WIDTH} height={200} fill={halfFill('bottom')} pointerEvents="none" />
          </>
        )}

        {/* 相手コートゾーン（上半分） */}
        {OPPONENT_ZONES.map((z) => renderZone(z, mode === 'land'))}

        {/* ネットライン */}
        <line
          x1={0} y1={200} x2={SVG_WIDTH} y2={200}
          stroke="#6b7280"
          strokeWidth={3}
          pointerEvents="none"
        />
        <text x={SVG_WIDTH / 2} y={197} textAnchor="middle" fontSize="9" fill="#6b7280" pointerEvents="none">ネット</text>

        {/* 自コートゾーン（下半分） */}
        {OWN_ZONES.map((z) => renderZone(z, mode === 'hit'))}

        {/* ネット接触ゾーン — OWN_ZONES の後に描画してクリックイベントが届くようにする */}
        {showOOB && interactive && NET_ZONE_RECTS.map(renderNetZone)}

        {/* コート外枠 */}
        <rect
          x={0} y={0}
          width={SVG_WIDTH} height={SVG_HEIGHT}
          fill="none"
          stroke="#374151"
          strokeWidth={2}
        />
      </svg>
      {!showOOB && <span className="text-[10px] text-gray-500">自コート（打点）</span>}
    </div>
  )
}
