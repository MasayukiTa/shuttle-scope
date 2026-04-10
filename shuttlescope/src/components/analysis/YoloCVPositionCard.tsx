/**
 * YoloCVPositionCard
 *
 * ダブルス CV ポジション解析カード（research / assisted 扱い）
 *
 * 表示内容:
 *   - formation_tendency: 陣形傾向（前後陣 / 平行陣 / 混合）
 *   - rotation_transitions: ラリー間陣形切り替え回数
 *   - pressure_map: ゾーン別の受け手前衛率
 *   - hitter_distribution: ヒッター候補分布（TrackNet アライメントがある場合）
 *
 * データ取得フロー:
 *   1. GET /api/matches?player_id={playerId} → 最新試合IDを特定
 *   2. GET /api/yolo/doubles_analysis/{match_id} → CV 解析結果を取得
 *
 * YOLO データがない試合では "データなし" を表示し、処理を促す。
 */
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'

interface Props {
  playerId: number
  filters: AnalysisFilters
}

// ─── API レスポンス型 ──────────────────────────────────────────────────────────

interface MatchSummary {
  id: number
  match_date: string | null
  format: string | null
}

interface FormationBreakdown {
  count: number
  ratio: number
}

interface FormationTendency {
  dominant: string
  style_label: string
  front_back_ratio: number
  parallel_ratio: number
  breakdown: Record<string, FormationBreakdown>
}

interface HitterDistribution {
  hitter_a_count: number
  hitter_b_count: number
  hitter_a_ratio: number
  hitter_b_ratio: number
  rally_dominant: Record<string, number>
  note: string
}

interface PressureZone {
  sample_count: number
  receiver_front_ratio: number
}

interface CVAnalysis {
  available: boolean
  yolo_frame_count?: number
  backend_used?: string
  position_summary?: Record<string, unknown>
  formation_tendency?: FormationTendency
  rotation_transitions?: number
  pressure_map?: Record<string, PressureZone>
  hitter_distribution?: HitterDistribution | null
  cv_role_signal?: Record<string, unknown> | null
  notes?: string[]
}

// ─── ヘルパー ─────────────────────────────────────────────────────────────────

const FORMATION_LABELS: Record<string, string> = {
  front_back: '前後陣',
  parallel: '平行陣',
  mixed: '混合',
  unknown: '不明',
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`
}

function FormationBar({ breakdown }: { breakdown: Record<string, FormationBreakdown> }) {
  const colors: Record<string, string> = {
    front_back: 'bg-sky-500',
    parallel: 'bg-amber-500',
    mixed: 'bg-purple-500',
    unknown: 'bg-gray-500',
  }
  const order = ['front_back', 'parallel', 'mixed', 'unknown']
  return (
    <div className="flex h-2.5 w-full rounded-full overflow-hidden gap-px">
      {order.map((k) => {
        const seg = breakdown[k]
        if (!seg || seg.ratio === 0) return null
        return (
          <div
            key={k}
            className={colors[k] ?? 'bg-gray-500'}
            style={{ width: `${seg.ratio * 100}%` }}
            title={`${FORMATION_LABELS[k] ?? k}: ${pct(seg.ratio)}`}
          />
        )
      })}
    </div>
  )
}

// ─── メインコンポーネント ──────────────────────────────────────────────────────

export function YoloCVPositionCard({ playerId, filters }: Props) {
  const { card, cardInner, textHeading, textSecondary, textMuted, textFaint, loading, isLight } =
    useCardTheme()

  // 1. プレイヤーの試合一覧（最新順）
  const filterParams = {
    player_id: playerId,
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  const { data: matchesResp, isLoading: matchesLoading } = useQuery({
    queryKey: ['player-matches-for-cv', playerId, filters],
    queryFn: () =>
      apiGet<{ success: boolean; data: MatchSummary[] }>('/matches', filterParams),
    enabled: !!playerId,
  })

  // 最新試合 ID（データがある最初の試合を使う）
  const recentMatch = matchesResp?.data?.[0] ?? null
  const matchId = recentMatch?.id ?? null

  // 2. CV 解析結果
  const { data: cvResp, isLoading: cvLoading } = useQuery({
    queryKey: ['yolo-doubles-analysis', matchId],
    queryFn: () =>
      apiGet<{ success: boolean; data: CVAnalysis }>(`/yolo/doubles_analysis/${matchId}`),
    enabled: !!matchId,
  })

  const isLoading = matchesLoading || cvLoading
  const cv = cvResp?.data

  // ─── ローディング ────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className={`${card} rounded-lg p-4`}>
        <div className={`text-xs ${textMuted} animate-pulse`}>CV 解析データを読み込み中…</div>
      </div>
    )
  }

  // ─── 試合なし ────────────────────────────────────────────────────────────────
  if (!recentMatch) {
    return (
      <div className={`${card} rounded-lg p-4`}>
        <p className={`text-xs ${textMuted}`}>対象期間に試合データがありません。</p>
      </div>
    )
  }

  // ─── YOLO データなし ─────────────────────────────────────────────────────────
  if (!cv?.available) {
    return (
      <div className={`${card} rounded-lg p-4 space-y-2`}>
        <h3 className={`text-sm font-semibold ${textHeading}`}>CV ポジション解析</h3>
        <p className={`text-xs ${textMuted}`}>
          試合 #{recentMatch.id} の YOLO 検出データがありません。
        </p>
        <p className={`text-xs ${textFaint}`}>
          アノテーター画面で「プレイヤー検出」を実行してください。
        </p>
        {cv?.notes?.map((n, i) => (
          <p key={i} className={`text-[10px] ${textFaint}`}>{n}</p>
        ))}
      </div>
    )
  }

  const ft = cv.formation_tendency
  const hd = cv.hitter_distribution
  const pm = cv.pressure_map ?? {}

  return (
    <div className={`${card} rounded-lg p-4 space-y-4`}>
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className={`text-sm font-semibold ${textHeading}`}>CV ポジション解析</h3>
          <p className={`text-[10px] ${textFaint}`}>
            試合 #{recentMatch.id}
            {recentMatch.match_date ? ` · ${recentMatch.match_date}` : ''}
            {' · '}
            {cv.yolo_frame_count ?? '?'} フレーム
            {cv.backend_used ? ` · ${cv.backend_used}` : ''}
          </p>
        </div>
        <EvidenceBadge tier="research" evidenceLevel="directional" recommendationAllowed={false} />
      </div>

      <ResearchNotice
        caution="CV 推定値はビデオ品質・カメラアングルに依存します。annotation truth には使用しないでください。"
        reason="YOLO プレイヤー検出 + TrackNet シャトル軌跡による assisted 解析です。"
      />

      {/* 陣形傾向 */}
      {ft && (
        <div className={`${cardInner} rounded p-3 space-y-2`}>
          <div className="flex items-center justify-between">
            <span className={`text-xs font-medium ${textSecondary}`}>陣形傾向</span>
            <span className={`text-xs font-bold ${textHeading}`}>{ft.style_label}</span>
          </div>
          {Object.keys(ft.breakdown).length > 0 && (
            <FormationBar breakdown={ft.breakdown} />
          )}
          <div className={`grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] ${textMuted}`}>
            {Object.entries(ft.breakdown).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between">
                <span>{FORMATION_LABELS[k] ?? k}</span>
                <span className={textFaint}>{pct(v.ratio)} ({v.count})</span>
              </div>
            ))}
          </div>
          {cv.rotation_transitions !== undefined && (
            <div className={`flex items-center justify-between text-[11px] ${textMuted} pt-1 border-t ${isLight ? 'border-gray-200' : 'border-gray-700'}`}>
              <span>ラリー間陣形切り替え</span>
              <span className={`font-bold ${textHeading}`}>{cv.rotation_transitions} 回</span>
            </div>
          )}
        </div>
      )}

      {/* ヒッター候補分布（アライメントがある場合） */}
      {hd && (
        <div className={`${cardInner} rounded p-3 space-y-2`}>
          <span className={`text-xs font-medium ${textSecondary}`}>ヒッター候補分布</span>
          <div className="flex h-2.5 w-full rounded-full overflow-hidden gap-px">
            <div
              className="bg-blue-500"
              style={{ width: `${hd.hitter_a_ratio * 100}%` }}
              title={`Player A: ${pct(hd.hitter_a_ratio)}`}
            />
            <div
              className="bg-amber-500"
              style={{ width: `${hd.hitter_b_ratio * 100}%` }}
              title={`Player B: ${pct(hd.hitter_b_ratio)}`}
            />
          </div>
          <div className={`grid grid-cols-2 text-[10px] ${textMuted}`}>
            <div>
              <span className="text-blue-400">A</span>: {hd.hitter_a_count}回 ({pct(hd.hitter_a_ratio)})
            </div>
            <div>
              <span className="text-amber-400">B</span>: {hd.hitter_b_count}回 ({pct(hd.hitter_b_ratio)})
            </div>
          </div>
          <div className={`flex gap-3 text-[10px] ${textFaint}`}>
            <span>ラリー主導: A={hd.rally_dominant['player_a'] ?? 0} B={hd.rally_dominant['player_b'] ?? 0} 均衡={hd.rally_dominant['balanced'] ?? 0}</span>
          </div>
          <p className={`text-[9px] ${textFaint} italic`}>{hd.note}</p>
        </div>
      )}

      {/* 圧力マップ（ゾーン別） */}
      {Object.keys(pm).length > 0 && (
        <div className={`${cardInner} rounded p-3 space-y-2`}>
          <span className={`text-xs font-medium ${textSecondary}`}>ゾーン別受け手前衛率</span>
          <div className="grid grid-cols-2 gap-1">
            {Object.entries(pm)
              .sort((a, b) => b[1].receiver_front_ratio - a[1].receiver_front_ratio)
              .slice(0, 8)
              .map(([zone, zd]) => (
                <div
                  key={zone}
                  className={`flex items-center justify-between text-[10px] ${textMuted} px-1.5 py-0.5 rounded ${isLight ? 'bg-gray-100' : 'bg-gray-800'}`}
                >
                  <span className={`font-mono font-bold ${textSecondary}`}>{zone}</span>
                  <div className="flex items-center gap-1.5">
                    <div className={`h-1 rounded-full bg-sky-500`} style={{ width: `${Math.round(zd.receiver_front_ratio * 32)}px`, minWidth: '2px' }} />
                    <span>{pct(zd.receiver_front_ratio)}</span>
                    <span className={textFaint}>n={zd.sample_count}</span>
                  </div>
                </div>
              ))}
          </div>
          <p className={`text-[9px] ${textFaint}`}>受け手(player_b)が前衛にいた割合。n はサンプル数。</p>
        </div>
      )}

      {/* ノート */}
      {cv.notes && cv.notes.length > 0 && (
        <div className="space-y-0.5">
          {cv.notes.map((n, i) => (
            <p key={i} className={`text-[10px] ${textFaint}`}>※ {n}</p>
          ))}
        </div>
      )}
    </div>
  )
}
