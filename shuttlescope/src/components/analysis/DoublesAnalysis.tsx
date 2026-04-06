// ダブルス解析コンポーネント（F-002 / F-003 / F-004）
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
} from 'recharts'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { WIN, LOSS, BAR, perfColor, TOOLTIP_STYLE } from '@/styles/colors'

interface MatchItem {
  match_id: number
  opponent: string
  date: string
  result: string
  format: string
}

interface DoublesAnalysisProps {
  playerId: number
  allMatches: MatchItem[]
}


// ─── パートナー比較 (F-002) ──────────────────────────────────────────────────

interface PartnerItem {
  partner_id: number
  partner_name: string
  match_count: number
  win_rate: number
  synergy_score: number
  avg_rally_length: number
}

function PartnerComparison({ playerId }: { playerId: number }) {
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-partner-comparison', playerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: { partners: PartnerItem[] }; meta: any }>(
        '/analysis/partner_comparison',
        { player_id: playerId }
      ),
    enabled: !!playerId,
  })

  if (isLoading) return <p className="text-gray-500 text-xs py-3 text-center">読み込み中...</p>

  const partners = resp?.data?.partners ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (partners.length === 0) {
    return <p className="text-gray-500 text-sm py-3 text-center">ダブルスデータがありません</p>
  }

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />
      <div className="space-y-2">
        {partners.map((p) => (
          <div key={p.partner_id} className="bg-gray-700/40 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-white font-medium">{p.partner_name}</span>
              <span className="text-xs text-gray-400">{p.match_count}試合</span>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <p className="text-lg font-bold text-blue-300">{(p.win_rate * 100).toFixed(0)}%</p>
                <p className="text-[10px] text-gray-500">勝率</p>
              </div>
              <div>
                <p className="text-lg font-bold text-amber-300">{(p.synergy_score * 100).toFixed(0)}</p>
                <p className="text-[10px] text-gray-500">相乗効果</p>
              </div>
              <div>
                <p className="text-lg font-bold text-cyan-300">{p.avg_rally_length.toFixed(1)}</p>
                <p className="text-[10px] text-gray-500">平均打数</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── サーブ/レシーブ勝率 (F-003) ────────────────────────────────────────────

interface ServeReceiveData {
  serve_win_rate: number
  receive_win_rate: number
  serve_style: Record<string, number>
  receive_zones: { zone: string; count: number; win_rate: number }[]
}

function ServeReceiveStats({ playerId }: { playerId: number }) {
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-doubles-serve-receive', playerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: ServeReceiveData; meta: any }>(
        '/analysis/doubles_serve_receive',
        { player_id: playerId }
      ),
    enabled: !!playerId,
  })

  if (isLoading) return <p className="text-gray-500 text-xs py-3 text-center">読み込み中...</p>

  const d = resp?.data
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (!d || sampleSize === 0) {
    return <p className="text-gray-500 text-sm py-3 text-center">ダブルスデータがありません</p>
  }

  const srData = [
    { name: 'サーブ側', rate: +(d.serve_win_rate * 100).toFixed(1), fill: WIN },
    { name: 'レシーブ側', rate: +(d.receive_win_rate * 100).toFixed(1), fill: BAR },
  ]

  const serveStyleEntries = Object.entries(d.serve_style)
  const totalServes = serveStyleEntries.reduce((s, [, v]) => s + v, 0)

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* サーブ/レシーブ勝率バー */}
      <ResponsiveContainer width="100%" height={100}>
        <BarChart data={srData} layout="vertical" margin={{ top: 0, right: 40, left: 8, bottom: 0 }}>
          <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fill: '#9ca3af', fontSize: 10 }} />
          <YAxis type="category" dataKey="name" width={72} tick={{ fill: '#d1d5db', fontSize: 11 }} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number) => [`${v.toFixed(1)}%`, '勝率']}
          />
          <Bar dataKey="rate" radius={[0, 4, 4, 0]}>
            {srData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* サーブ種別比率 */}
      {serveStyleEntries.length > 0 && (
        <div>
          <p className="text-xs text-gray-500 mb-1.5">サーブ種別比率</p>
          <div className="flex gap-3">
            {serveStyleEntries.map(([st, rate]) => (
              <div key={st} className="flex-1 bg-gray-700/40 rounded p-2 text-center">
                <p className="text-sm font-bold text-white">{(rate * 100).toFixed(0)}%</p>
                <p className="text-[10px] text-gray-400">
                  {st === 'short_service' ? 'ショート' : 'ロング'}サーブ
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* レシーブゾーン勝率 */}
      {d.receive_zones.length > 0 && (
        <div>
          <p className="text-xs text-gray-500 mb-1.5">レシーブゾーン別勝率</p>
          <div className="grid grid-cols-3 gap-1">
            {d.receive_zones.slice(0, 9).map((z) => (
              <div
                key={z.zone}
                className="rounded p-1.5 text-center text-xs"
                style={{ backgroundColor: perfColor(z.win_rate, 0.6) }}
              >
                <p className="text-white font-medium">{z.zone}</p>
                <p className="text-gray-300">{(z.win_rate * 100).toFixed(0)}%</p>
                <p className="text-gray-500 text-[10px]">{z.count}回</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── 打球分担 (F-004) ────────────────────────────────────────────────────────

interface StrokeSharingData {
  balanced_win_rate: number
  imbalanced_win_rate: number
  balanced_count: number
  imbalanced_count: number
  avg_balance_ratio: number
}

function StrokeSharing({ playerId }: { playerId: number }) {
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-stroke-sharing', playerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: StrokeSharingData; meta: any }>(
        '/analysis/stroke_sharing',
        { player_id: playerId }
      ),
    enabled: !!playerId,
  })

  if (isLoading) return <p className="text-gray-500 text-xs py-3 text-center">読み込み中...</p>

  const d = resp?.data
  const sampleSize = resp?.meta?.sample_size ?? 0

  if (!d || sampleSize === 0) {
    return <p className="text-gray-500 text-sm py-3 text-center">ダブルスデータがありません</p>
  }

  const shareData = [
    { name: 'バランス良', rate: +(d.balanced_win_rate * 100).toFixed(1), count: d.balanced_count, fill: WIN },
    { name: '偏り大', rate: +(d.imbalanced_win_rate * 100).toFixed(1), count: d.imbalanced_count, fill: LOSS },
  ]

  const balancePct = Math.round(d.avg_balance_ratio * 100)

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* 平均バランス比率メーター */}
      <div className="bg-gray-700/40 rounded-lg p-3">
        <p className="text-xs text-gray-400 mb-2">平均打球分担バランス</p>
        <div className="relative h-4 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="absolute left-0 top-0 h-full rounded-full bg-gradient-to-r from-orange-500 via-green-400 to-orange-500"
            style={{ width: `${balancePct}%` }}
          />
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-xs font-bold text-white drop-shadow">{balancePct}%</span>
          </div>
        </div>
        <div className="flex justify-between text-[10px] text-gray-600 mt-0.5">
          <span>偏り大</span><span>バランス均衡</span>
        </div>
      </div>

      {/* バランス別勝率 */}
      <ResponsiveContainer width="100%" height={90}>
        <BarChart data={shareData} layout="vertical" margin={{ top: 0, right: 40, left: 8, bottom: 0 }}>
          <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fill: '#9ca3af', fontSize: 10 }} />
          <YAxis type="category" dataKey="name" width={60} tick={{ fill: '#d1d5db', fontSize: 11 }} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number, _: string, entry: any) =>
              [`${v.toFixed(1)}% (${entry.payload.count}ラリー)`, '勝率']
            }
          />
          <Bar dataKey="rate" radius={[0, 4, 4, 0]}>
            {shareData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── コートカバレッジ (F-001) ────────────────────────────────────────────────

interface CoverageData {
  balance_score: number
  player_a?: { front_rate: number; back_rate: number; mid_rate: number; total_strokes: number }
  partner_a?: { front_rate: number; back_rate: number; mid_rate: number; total_strokes: number }
}

function CourtCoverage({ matchId }: { matchId: number }) {
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-court-coverage-split', matchId],
    queryFn: () =>
      apiGet<{ success: boolean; data: CoverageData; meta: any }>(
        '/analysis/court_coverage_split',
        { match_id: matchId }
      ),
    enabled: !!matchId,
  })

  if (isLoading) return <p className="text-gray-500 text-xs py-3 text-center">読み込み中...</p>

  const d = resp?.data
  if (!d) return <p className="text-gray-500 text-sm py-3 text-center">データがありません</p>

  const players = [
    { label: '自分', data: d.player_a },
    { label: 'パートナー', data: d.partner_a },
  ].filter((p) => p.data)

  if (players.length === 0) return <p className="text-gray-500 text-sm py-3">コートデータがありません</p>

  const radarData = [
    { area: '前衛率', ...Object.fromEntries(players.map((p) => [p.label, +(p.data!.front_rate * 100).toFixed(1)])) },
    { area: '中間率', ...Object.fromEntries(players.map((p) => [p.label, +(p.data!.mid_rate * 100).toFixed(1)])) },
    { area: '後衛率', ...Object.fromEntries(players.map((p) => [p.label, +(p.data!.back_rate * 100).toFixed(1)])) },
  ]

  const COLORS = [WIN, BAR]

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400">バランススコア:</span>
        <span className={`text-sm font-bold ${d.balance_score >= 0.8 ? 'text-green-400' : d.balance_score >= 0.6 ? 'text-amber-400' : 'text-red-400'}`}>
          {(d.balance_score * 100).toFixed(0)}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <RadarChart data={radarData}>
          <PolarGrid stroke="#374151" />
          <PolarAngleAxis dataKey="area" tick={{ fill: '#9ca3af', fontSize: 11 }} />
          {players.map((p, i) => (
            <Radar
              key={p.label}
              name={p.label}
              dataKey={p.label}
              stroke={COLORS[i]}
              fill={COLORS[i]}
              fillOpacity={0.2}
            />
          ))}
        </RadarChart>
      </ResponsiveContainer>

      <div className="flex gap-3">
        {players.map((p, i) => (
          <div key={p.label} className="flex items-center gap-1.5 text-xs">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS[i] }} />
            <span className="text-gray-400">{p.label}</span>
            <span className="text-gray-300">{p.data!.total_strokes}打</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── メインコンポーネント ────────────────────────────────────────────────────

export function DoublesAnalysis({ playerId, allMatches }: DoublesAnalysisProps) {
  const doublesMatches = allMatches.filter((m) => m.format && m.format !== 'singles')
  const [selectedDoubleMatchId, setSelectedDoubleMatchId] = useState<number | null>(
    doublesMatches[0]?.match_id ?? null
  )

  return (
    <div className="space-y-5">
      {/* パートナー比較 + サーブ受け */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <div className="bg-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-200 mb-3">パートナー別パフォーマンス</h3>
          <PartnerComparison playerId={playerId} />
        </div>
        <div className="bg-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-200 mb-3">サーブ / レシーブ勝率</h3>
          <ServeReceiveStats playerId={playerId} />
        </div>
      </div>

      {/* 打球分担 + コートカバレッジ */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <div className="bg-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-200 mb-3">打球分担バランス</h3>
          <StrokeSharing playerId={playerId} />
        </div>

        <div className="bg-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-200">コートカバレッジ分担</h3>
            {doublesMatches.length > 0 && (
              <select
                className="text-xs bg-gray-700 border border-gray-600 text-gray-200 rounded px-2 py-1 max-w-[180px]"
                value={selectedDoubleMatchId ?? ''}
                onChange={(e) => setSelectedDoubleMatchId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">-- 試合を選択 --</option>
                {doublesMatches.map((m: any) => (
                  <option key={m.match_id} value={m.match_id}>
                    {m.date} vs {m.opponent}
                  </option>
                ))}
              </select>
            )}
          </div>
          {selectedDoubleMatchId ? (
            <CourtCoverage matchId={selectedDoubleMatchId} />
          ) : (
            <p className="text-gray-500 text-sm text-center py-4">
              ダブルス試合を選択するとカバレッジが表示されます
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
