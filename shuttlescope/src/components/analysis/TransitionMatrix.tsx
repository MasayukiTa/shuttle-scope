// ショット遷移マトリクスをD3.jsで描画するヒートマップコンポーネント
// 注意: d3 は本ファイルのみで使用
import { useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as d3 from 'd3'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { AnalysisFilters, DEFAULT_FILTERS } from '@/types'

interface TransitionMatrixProps {
  playerId: number
  filters?: AnalysisFilters
}

interface TopSequence {
  from: string
  to: string
  count: number
  probability: number
}

interface MatrixData {
  matrix: number[][]          // 確率値 0〜1
  shot_labels: string[]       // 日本語ラベル
  shot_keys: string[]         // 英語キー
  raw_counts: number[][]      // 実件数
  total_transitions: number
  top_sequences: TopSequence[]
}

interface TransitionMatrixResponse {
  data: MatrixData
  meta?: {
    sample_size: number
    confidence?: { level: string; stars: string; label: string; warning?: string }
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// D3 描画ロジック
// ──────────────────────────────────────────────────────────────────────────────

const CELL = 32          // セルサイズ
const MARGIN_LEFT = 100  // Y軸ラベル用
const MARGIN_TOP = 20    // 上余白（タイトルなし）
const MARGIN_RIGHT = 20
const MARGIN_BOTTOM = 110 // X軸ラベル（下部、回転あり）

function calcSvgSize(n: number) {
  const w = MARGIN_LEFT + n * CELL + MARGIN_RIGHT
  const h = MARGIN_TOP + n * CELL + MARGIN_BOTTOM
  return { w, h }
}

function drawMatrix(
  svgEl: SVGSVGElement,
  matrixData: MatrixData,
  isLight: boolean
) {
  const { matrix, shot_labels, raw_counts } = matrixData
  const n = shot_labels.length
  const { w, h } = calcSvgSize(n)

  // SVG クリア
  d3.select(svgEl).selectAll('*').remove()

  const svg = d3.select(svgEl)
    .attr('width', w)
    .attr('height', h)

  // ライトモード: SVG 背景を明示的に設定（透明だと白背景との区別が消える）
  if (isLight) {
    svg.append('rect')
      .attr('width', w)
      .attr('height', h)
      .attr('fill', '#f7f9fc')
      .attr('rx', 4)
  }

  const g = svg.append('g')
    .attr('transform', `translate(${MARGIN_LEFT},${MARGIN_TOP})`)

  // カラースケール: 白→深青（密度ヒートマップ: seqBlue ルール）
  const maxVal = d3.max(matrix.flat()) ?? 1

  // seqBlue: 0=白(rgb 240,244,255) → 1=深青(#3b4cc0)
  function seqBlueColor(prob: number, max: number): string {
    if (max === 0) return 'rgb(240,244,255)'
    const t = Math.max(0, Math.min(prob / max, 1))
    const r = Math.round(240 - (240 - 59) * t)
    const g = Math.round(244 - (244 - 76) * t)
    const b = Math.round(255 - (255 - 192) * t)
    return `rgb(${r},${g},${b})`
  }

  // ツールチップ（HTMLのdivを使用）
  const tooltip = d3.select('body')
    .selectAll<HTMLDivElement, unknown>('#transition-matrix-tooltip')
    .data([null])
    .join('div')
    .attr('id', 'transition-matrix-tooltip')
    .style('position', 'fixed')
    .style('visibility', 'hidden')
    .style('background', '#111827')
    .style('border', '1px solid #374151')
    .style('border-radius', '6px')
    .style('padding', '8px 12px')
    .style('font-size', '12px')
    .style('color', '#f9fafb')
    .style('pointer-events', 'none')
    .style('z-index', '9999')
    .style('white-space', 'nowrap')

  // ── セル描画 ──
  matrix.forEach((row, ri) => {
    row.forEach((prob, ci) => {
      const isDiag = ri === ci
      const count = raw_counts?.[ri]?.[ci] ?? 0

      g.append('rect')
        .attr('x', ci * CELL)
        .attr('y', ri * CELL)
        .attr('width', CELL - 1)
        .attr('height', CELL - 1)
        .attr('rx', 2)
        .attr('fill', isDiag ? '#374151' : seqBlueColor(prob, maxVal))
        .attr('stroke', 'none')
        .style('cursor', isDiag ? 'default' : 'pointer')
        .on('mouseover', function (event) {
          if (isDiag) return
          const fromLabel = shot_labels[ri] ?? shot_keys_fallback(ri)
          const toLabel = shot_labels[ci] ?? shot_keys_fallback(ci)
          const probPct = (prob * 100).toFixed(1)
          tooltip
            .style('visibility', 'visible')
            .html(
              `<strong>${fromLabel} → ${toLabel}</strong><br/>` +
              `${count}回 (${probPct}%)`
            )
        })
        .on('mousemove', function (event) {
          tooltip
            .style('left', `${event.clientX + 14}px`)
            .style('top', `${event.clientY - 28}px`)
        })
        .on('mouseout', function () {
          tooltip.style('visibility', 'hidden')
        })
    })
  })

  // テーマ別テキスト色
  const labelColor  = isLight ? '#334155' : '#9ca3af'
  const titleColor  = isLight ? '#475569' : '#6b7280'

  // ── X 軸ラベル（下部） ──
  const xLabelY = n * CELL + 8
  shot_labels.forEach((label, ci) => {
    g.append('text')
      .attr('x', ci * CELL + CELL / 2)
      .attr('y', xLabelY)
      .attr('text-anchor', 'start')
      .attr('dominant-baseline', 'middle')
      .attr('transform', `rotate(45, ${ci * CELL + CELL / 2}, ${xLabelY})`)
      .attr('fill', labelColor)
      .attr('font-size', 10)
      .text(truncate(label, 6))
  })

  // ── Y 軸ラベル（左側） ──
  shot_labels.forEach((label, ri) => {
    g.append('text')
      .attr('x', -6)
      .attr('y', ri * CELL + CELL / 2)
      .attr('text-anchor', 'end')
      .attr('dominant-baseline', 'middle')
      .attr('fill', labelColor)
      .attr('font-size', 10)
      .text(truncate(label, 7))
  })

  // ── 軸タイトル（X軸: 下, Y軸: 左） ──
  svg.append('text')
    .attr('x', MARGIN_LEFT + (n * CELL) / 2)
    .attr('y', MARGIN_TOP + n * CELL + MARGIN_BOTTOM - 10)
    .attr('text-anchor', 'middle')
    .attr('fill', titleColor)
    .attr('font-size', 11)
    .text('次のショット →')

  svg.append('text')
    .attr('transform', `rotate(-90)`)
    .attr('x', -(MARGIN_TOP + (n * CELL) / 2))
    .attr('y', 14)
    .attr('text-anchor', 'middle')
    .attr('fill', titleColor)
    .attr('font-size', 11)
    .text('現在のショット')
}

// ラベルが長い場合に切り詰める
function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + '…' : s
}

function shot_keys_fallback(i: number): string {
  return `Shot${i + 1}`
}

// ──────────────────────────────────────────────────────────────────────────────
// React コンポーネント
// ──────────────────────────────────────────────────────────────────────────────

export function TransitionMatrix({ playerId, filters = DEFAULT_FILTERS }: TransitionMatrixProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const isLight = useIsLightMode()

  const fp = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-shot-transition-matrix', playerId, filters],
    queryFn: () =>
      apiGet<TransitionMatrixResponse>('/analysis/shot_transition_matrix', {
        player_id: playerId,
        ...fp,
      }),
    enabled: !!playerId,
  })

  const matrixData = resp?.data
  const sampleSize = resp?.meta?.sample_size ?? 0

  // データまたはテーマが変わるたびに D3 で再描画
  useEffect(() => {
    if (!svgRef.current || !matrixData?.matrix?.length) return
    drawMatrix(svgRef.current, matrixData, isLight)

    // クリーンアップ: ツールチップ要素を削除
    return () => {
      d3.select('#transition-matrix-tooltip').remove()
    }
  }, [matrixData, isLight])

  if (isLoading) {
    return (
      <div className="text-gray-500 text-sm py-8 text-center">読み込み中...</div>
    )
  }

  if (!matrixData || !matrixData.matrix?.length || sampleSize === 0) {
    return (
      <div className="text-gray-500 text-sm py-4 text-center">
        データ不足（アノテーション後に解析可能）
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* ヘッダー行 */}
      <div className="flex flex-wrap items-center gap-3">
        <ConfidenceBadge sampleSize={sampleSize} />
        <span className="text-xs text-gray-500">
          総遷移数: {matrixData.total_transitions.toLocaleString()} 回
        </span>
      </div>

      {/* ヒートマップ SVG（スクロール対応） */}
      <div className="overflow-x-auto">
        <svg ref={svgRef} style={{ display: 'block' }} />
      </div>

      {/* 凡例: 白→深青（密度スケール） */}
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <span>低頻度</span>
        <div
          className="h-3 w-32 rounded"
          style={{
            background: 'linear-gradient(to right, rgb(240,244,255), rgb(59,76,192))',
          }}
        />
        <span>高頻度</span>
        <span className="ml-2 text-gray-600">（対角線はグレーでマスク）</span>
      </div>

      {/* よく起きる遷移トップ5 */}
      {matrixData.top_sequences?.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 mb-2">
            頻出ショット遷移 Top 5
          </p>
          <div className="space-y-1">
            {matrixData.top_sequences.slice(0, 5).map((seq, i) => {
              const fromIdx = matrixData.shot_keys.indexOf(seq.from)
              const toIdx = matrixData.shot_keys.indexOf(seq.to)
              const fromLabel =
                fromIdx >= 0 ? matrixData.shot_labels[fromIdx] : seq.from
              const toLabel =
                toIdx >= 0 ? matrixData.shot_labels[toIdx] : seq.to
              return (
                <div
                  key={i}
                  className="flex items-center gap-2 text-xs"
                >
                  <span className="w-4 text-gray-600 shrink-0">{i + 1}.</span>
                  <span className="text-gray-300 flex-1 min-w-0 truncate">
                    {fromLabel} → {toLabel}
                  </span>
                  <div className="shrink-0 flex items-center gap-1.5">
                    <span className="text-blue-400">{seq.count}回</span>
                    <span className="text-gray-500 w-10 text-right">
                      {(seq.probability * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
