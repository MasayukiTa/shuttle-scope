/**
 * PlayerMovementCard
 *
 * 選手識別トラック + コートキャリブレーションから算出した
 * コート上の移動距離・速度・方向・ゾーン分布を表示するカード。
 *
 * 表示内容:
 *   - 総移動距離 / 平均速度 / 最大瞬間速度
 *   - 方向内訳（横方向 / 斜め / 前後）のスタックバー
 *   - 累積距離の時系列 SVG チャート（全選手重ねて表示）
 *   - ミニコートヒートマップ（ゾーン別滞在頻度）
 */
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useCardTheme } from '@/hooks/useCardTheme'

// ─── 型定義 ───────────────────────────────────────────────────────────────────

interface DirectionBreakdown {
  lateral_m: number
  depth_m: number
  diagonal_m: number
  lateral_pct: number
  depth_pct: number
  diagonal_pct: number
}

interface TimePoint {
  t: number
  dist_m: number
}

interface PlayerStats {
  total_distance_m: number
  frames_tracked: number
  duration_sec: number
  avg_speed_m_per_s: number
  max_speed_m_per_s: number
  direction_breakdown: DirectionBreakdown
  zone_visits: Record<string, number>
  time_series: TimePoint[]
}

interface MovementStatsData {
  available: boolean
  reason?: string
  has_calibration: boolean
  court_width_m: number
  court_length_m: number
  players: Record<string, PlayerStats>
  confidence: {
    level: 'low' | 'medium' | 'high'
    reason: string
    has_calibration: boolean
  }
}

interface Props {
  matchId: number
  /** 'singles' | 'doubles' | 'mixed_doubles' */
  matchFormat: string
  /** player_key → 表示名 マップ */
  playerNames: Record<string, string>
  isLight: boolean
}

// ─── 定数 ─────────────────────────────────────────────────────────────────────

const PLAYER_COLORS: Record<string, { line: string; bg: string; text: string }> = {
  player_a:  { line: '#3b82f6', bg: 'bg-blue-500',   text: 'text-blue-400' },
  partner_a: { line: '#06b6d4', bg: 'bg-cyan-500',   text: 'text-cyan-400' },
  player_b:  { line: '#f59e0b', bg: 'bg-amber-500',  text: 'text-amber-400' },
  partner_b: { line: '#ec4899', bg: 'bg-pink-500',   text: 'text-pink-400' },
}

const DIR_COLORS = {
  lateral:  { bar: 'bg-teal-500',   label: '横方向' },
  diagonal: { bar: 'bg-purple-500', label: '斜め' },
  depth:    { bar: 'bg-blue-500',   label: '前後' },
}

const CONF_COLORS = {
  high:   'text-green-400',
  medium: 'text-yellow-400',
  low:    'text-red-400',
}

// コートゾーン定義（行 × 列 = 6 × 3）
const ZONE_ROWS = ['front', 'mid', 'back'] as const
const ZONE_COLS = ['left', 'center', 'right'] as const
const SIDES = ['A', 'B'] as const

function fmt1(v: number) { return v.toFixed(1) }
function fmt2(v: number) { return v.toFixed(2) }

function speedKmh(mps: number) { return (mps * 3.6).toFixed(1) }

// ─── ミニコートヒートマップ ────────────────────────────────────────────────────

function MiniCourtHeatmap({
  zoneVisits,
  playerKey,
  isLight,
}: {
  zoneVisits: Record<string, number>
  playerKey: string
  isLight: boolean
}) {
  const maxVisit = Math.max(1, ...Object.values(zoneVisits))
  const color = PLAYER_COLORS[playerKey]?.line ?? '#6b7280'

  // コートを縦向きに描画: A側(上) → ネット → B側(下)
  // 各ゾーン: side × depth × col = 2 × 3 × 3 = 18
  const cellH = 16
  const cellW = 20
  const netH  = 4
  const totalH = cellH * 6 + netH
  const totalW = cellW * 3

  return (
    <svg
      width={totalW}
      height={totalH}
      style={{ display: 'block' }}
      title="ゾーン別滞在頻度（濃いほど多い）"
    >
      {/* コート外枠 */}
      <rect x={0} y={0} width={totalW} height={totalH}
        fill="none" stroke={isLight ? '#d1d5db' : '#374151'} strokeWidth={1} />

      {/* ゾーンセル */}
      {SIDES.flatMap((side, si) =>
        ZONE_ROWS.map((depth, di) =>
          ZONE_COLS.map((col, ci) => {
            const zoneName = `${side}_${depth}_${col}`
            const count = zoneVisits[zoneName] ?? 0
            const intensity = count / maxVisit
            // 行インデックス: A_front=0, A_mid=1, A_back=2, B_front=3, B_mid=4, B_back=5
            const rowIdx = si * 3 + di
            const y = rowIdx < 3
              ? rowIdx * cellH
              : rowIdx * cellH + netH
            return (
              <g key={zoneName}>
                <rect
                  x={ci * cellW}
                  y={y}
                  width={cellW}
                  height={cellH}
                  fill={color}
                  fillOpacity={intensity * 0.85 + (intensity > 0 ? 0.05 : 0)}
                  stroke={isLight ? '#e5e7eb' : '#1f2937'}
                  strokeWidth={0.5}
                />
                {count > 0 && (
                  <text
                    x={ci * cellW + cellW / 2}
                    y={y + cellH / 2 + 4}
                    textAnchor="middle"
                    fontSize={8}
                    fill={intensity > 0.5 ? '#fff' : (isLight ? '#374151' : '#d1d5db')}
                  >
                    {count}
                  </text>
                )}
              </g>
            )
          })
        )
      )}

      {/* ネットライン */}
      <rect
        x={0} y={cellH * 3}
        width={totalW} height={netH}
        fill={isLight ? '#9ca3af' : '#4b5563'}
      />
      <text
        x={totalW / 2} y={cellH * 3 + netH / 2 + 3}
        textAnchor="middle" fontSize={7}
        fill={isLight ? '#f9fafb' : '#e5e7eb'}
      >
        NET
      </text>

      {/* サイドラベル */}
      <text x={2} y={cellH * 1.5} fontSize={7} fill={isLight ? '#6b7280' : '#9ca3af'}>A</text>
      <text x={2} y={cellH * 4.5 + netH} fontSize={7} fill={isLight ? '#6b7280' : '#9ca3af'}>B</text>
    </svg>
  )
}

// ─── 累積距離 SVG チャート ────────────────────────────────────────────────────

function CumulativeDistanceChart({
  playerStats,
  playerNames,
  isLight,
}: {
  playerStats: Record<string, PlayerStats>
  playerNames: Record<string, string>
  isLight: boolean
}) {
  const W = 280
  const H = 80
  const PAD = { t: 8, r: 8, b: 20, l: 40 }
  const innerW = W - PAD.l - PAD.r
  const innerH = H - PAD.t - PAD.b

  // 全選手の最大時刻・距離を求める
  let maxT = 0
  let maxD = 0
  for (const stats of Object.values(playerStats)) {
    for (const pt of stats.time_series) {
      if (pt.t > maxT) maxT = pt.t
      if (pt.dist_m > maxD) maxD = pt.dist_m
    }
  }
  if (maxT === 0 || maxD === 0) return null

  function toSvgX(t: number) { return PAD.l + (t / maxT) * innerW }
  function toSvgY(d: number) { return PAD.t + innerH - (d / maxD) * innerH }

  // 軸目盛り
  const timeTickCount = 5
  const distTickCount = 4

  return (
    <svg width={W} height={H} style={{ overflow: 'visible' }}>
      {/* グリッドライン */}
      {Array.from({ length: distTickCount + 1 }, (_, i) => {
        const d = (maxD / distTickCount) * i
        const y = toSvgY(d)
        return (
          <g key={i}>
            <line x1={PAD.l} y1={y} x2={PAD.l + innerW} y2={y}
              stroke={isLight ? '#e5e7eb' : '#374151'} strokeWidth={0.5} strokeDasharray="2 2" />
            <text x={PAD.l - 3} y={y + 3} textAnchor="end" fontSize={8}
              fill={isLight ? '#9ca3af' : '#6b7280'}>
              {d >= 1000 ? `${(d / 1000).toFixed(1)}k` : Math.round(d)}
            </text>
          </g>
        )
      })}

      {/* 時間軸 */}
      {Array.from({ length: timeTickCount + 1 }, (_, i) => {
        const t = (maxT / timeTickCount) * i
        const x = toSvgX(t)
        return (
          <g key={i}>
            <text x={x} y={H - 3} textAnchor="middle" fontSize={8}
              fill={isLight ? '#9ca3af' : '#6b7280'}>
              {t >= 60 ? `${Math.round(t / 60)}m` : `${Math.round(t)}s`}
            </text>
          </g>
        )
      })}

      {/* 軸 */}
      <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={PAD.t + innerH}
        stroke={isLight ? '#d1d5db' : '#4b5563'} strokeWidth={1} />
      <line x1={PAD.l} y1={PAD.t + innerH} x2={PAD.l + innerW} y2={PAD.t + innerH}
        stroke={isLight ? '#d1d5db' : '#4b5563'} strokeWidth={1} />

      {/* Y軸ラベル */}
      <text
        x={8} y={PAD.t + innerH / 2}
        textAnchor="middle" fontSize={8}
        fill={isLight ? '#9ca3af' : '#6b7280'}
        transform={`rotate(-90, 8, ${PAD.t + innerH / 2})`}
      >
        m
      </text>

      {/* 選手ごとの折れ線 */}
      {Object.entries(playerStats).map(([key, stats]) => {
        const color = PLAYER_COLORS[key]?.line ?? '#6b7280'
        const pts = stats.time_series
        if (pts.length < 2) return null
        const d = pts
          .map((pt, i) => `${i === 0 ? 'M' : 'L'}${toSvgX(pt.t).toFixed(1)},${toSvgY(pt.dist_m).toFixed(1)}`)
          .join(' ')
        return (
          <path key={key} d={d}
            fill="none" stroke={color} strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" />
        )
      })}
    </svg>
  )
}

// ─── メインコンポーネント ──────────────────────────────────────────────────────

export function PlayerMovementCard({ matchId, matchFormat: _matchFormat, playerNames, isLight }: Props) {
  const { card, cardInner, textHeading, textSecondary, textMuted, textFaint } = useCardTheme()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['movement-stats', matchId],
    queryFn: () => apiGet<{ success: boolean; data: MovementStatsData }>(`/yolo/movement_stats/${matchId}`),
    staleTime: 5_000,   // 識別確定直後にカードが表示されても古いキャッシュを返さない
  })

  const stats = resp?.data

  // ── ローディング ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className={`${card} rounded-lg p-4`}>
        <div className={`text-xs ${textMuted} animate-pulse`}>移動距離を計算中…</div>
      </div>
    )
  }

  // ── データなし ───────────────────────────────────────────────────────────
  if (!stats?.available) {
    return (
      <div className={`${card} rounded-lg p-4 space-y-1`}>
        <h3 className={`text-sm font-semibold ${textHeading}`}>選手移動距離</h3>
        <p className={`text-xs ${textMuted}`}>
          {stats?.reason ?? '選手識別トラックがありません。「+ 識別」でトラッキングを実行してください。'}
        </p>
      </div>
    )
  }

  const players = stats.players
  const playerKeys = Object.keys(players)
  const conf = stats.confidence

  return (
    <div className={`${card} rounded-lg p-4 space-y-4`}>
      {/* ── ヘッダー ─────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className={`text-sm font-semibold ${textHeading}`}>選手移動距離</h3>
          <p className={`text-[10px] ${textFaint}`}>
            コート: {stats.court_length_m}m × {stats.court_width_m}m
            {!stats.has_calibration && ' ※キャリブ未設定・相対値'}
          </p>
        </div>
        <span className={`text-[10px] font-medium ${CONF_COLORS[conf.level]}`}>
          {conf.level === 'high' ? '高' : conf.level === 'medium' ? '中' : '低'}信頼度
        </span>
      </div>

      {/* キャリブ未設定の警告 */}
      {!stats.has_calibration && (
        <p className={`text-[10px] ${textMuted} bg-yellow-500/10 border border-yellow-500/30 rounded px-2 py-1`}>
          コートキャリブレーションが未設定のため、実メートル値ではなく画像座標の相対値です。
          グリッドを設定するとメートル換算されます。
        </p>
      )}

      {/* ── 選手ごとの統計 ───────────────────────────────────────────────── */}
      <div className="space-y-3">
        {playerKeys.map((key) => {
          const p = players[key]
          const name = playerNames[key] ?? key
          const col = PLAYER_COLORS[key] ?? { line: '#6b7280', bg: 'bg-gray-500', text: 'text-gray-400' }
          const dir = p.direction_breakdown

          return (
            <div key={key} className={`${cardInner} rounded p-3 space-y-2`}>
              {/* 名前 + 主要数値 */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${col.bg}`} />
                  <span className={`text-xs font-semibold ${textHeading}`}>{name}</span>
                </div>
                <span className={`text-[10px] ${textFaint}`}>{p.frames_tracked}フレーム</span>
              </div>

              {/* 3指標グリッド */}
              <div className="grid grid-cols-3 gap-1">
                {[
                  { label: '総移動距離', value: p.total_distance_m >= 1000
                      ? `${(p.total_distance_m / 1000).toFixed(2)}km`
                      : `${fmt1(p.total_distance_m)}m` },
                  { label: '平均速度', value: `${speedKmh(p.avg_speed_m_per_s)}km/h` },
                  { label: '最大瞬間速度', value: `${speedKmh(p.max_speed_m_per_s)}km/h` },
                ].map(({ label, value }) => (
                  <div key={label} className={`${isLight ? 'bg-gray-100' : 'bg-gray-800'} rounded p-1.5 text-center`}>
                    <div className={`text-[9px] ${textFaint} leading-none mb-0.5`}>{label}</div>
                    <div className={`text-xs font-bold ${col.text}`}>{value}</div>
                  </div>
                ))}
              </div>

              {/* 方向内訳バー */}
              <div>
                <div className={`text-[9px] ${textFaint} mb-1`}>方向内訳</div>
                <div className="flex h-2 w-full rounded overflow-hidden gap-px">
                  {dir.lateral_pct > 0 && (
                    <div
                      className={DIR_COLORS.lateral.bar}
                      style={{ width: `${dir.lateral_pct}%` }}
                      title={`横方向: ${fmt2(dir.lateral_m)}m (${fmt1(dir.lateral_pct)}%)`}
                    />
                  )}
                  {dir.diagonal_pct > 0 && (
                    <div
                      className={DIR_COLORS.diagonal.bar}
                      style={{ width: `${dir.diagonal_pct}%` }}
                      title={`斜め: ${fmt2(dir.diagonal_m)}m (${fmt1(dir.diagonal_pct)}%)`}
                    />
                  )}
                  {dir.depth_pct > 0 && (
                    <div
                      className={DIR_COLORS.depth.bar}
                      style={{ width: `${dir.depth_pct}%` }}
                      title={`前後: ${fmt2(dir.depth_m)}m (${fmt1(dir.depth_pct)}%)`}
                    />
                  )}
                </div>
                <div className={`flex gap-3 mt-0.5 text-[9px] ${textFaint}`}>
                  <span><span className="text-teal-400">■</span> 横 {fmt1(dir.lateral_pct)}%</span>
                  <span><span className="text-purple-400">■</span> 斜 {fmt1(dir.diagonal_pct)}%</span>
                  <span><span className="text-blue-400">■</span> 前後 {fmt1(dir.depth_pct)}%</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* ── 累積距離チャート ─────────────────────────────────────────────── */}
      {playerKeys.length > 0 && (
        <div className={`${cardInner} rounded p-3 space-y-2`}>
          <div className="flex items-center justify-between">
            <span className={`text-xs font-medium ${textSecondary}`}>累積移動距離（時系列）</span>
            <div className="flex gap-2">
              {playerKeys.map((key) => (
                <span key={key} className={`text-[10px] ${textFaint} flex items-center gap-1`}>
                  <span
                    className="inline-block w-3 h-1 rounded"
                    style={{ backgroundColor: PLAYER_COLORS[key]?.line ?? '#6b7280' }}
                  />
                  {playerNames[key] ?? key}
                </span>
              ))}
            </div>
          </div>
          <CumulativeDistanceChart
            playerStats={players}
            playerNames={playerNames}
            isLight={isLight}
          />
        </div>
      )}

      {/* ── ゾーンヒートマップ ───────────────────────────────────────────── */}
      {playerKeys.length > 0 && (
        <div className={`${cardInner} rounded p-3 space-y-2`}>
          <span className={`text-xs font-medium ${textSecondary}`}>ゾーン別滞在頻度</span>
          <div className="flex flex-wrap gap-4">
            {playerKeys.map((key) => {
              const p = players[key]
              const name = playerNames[key] ?? key
              return (
                <div key={key} className="flex flex-col items-center gap-1">
                  <span className={`text-[10px] ${textFaint}`}>{name}</span>
                  <MiniCourtHeatmap
                    zoneVisits={p.zone_visits}
                    playerKey={key}
                    isLight={isLight}
                  />
                </div>
              )
            })}
          </div>
          <p className={`text-[9px] ${textFaint}`}>
            ゾーン内の数字はフレーム数。濃いほど長時間滞在。A: 自コート上部 / B: 相手コート下部。
          </p>
        </div>
      )}

      {/* 信頼度ノート */}
      <p className={`text-[9px] ${textFaint}`}>※ {conf.reason}</p>
    </div>
  )
}
