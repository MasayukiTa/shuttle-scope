// ショット遷移マトリクスをD3.jsで描画するヒートマップコンポーネント
// 注意: d3 は本ファイルのみで使用
import { useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as d3 from 'd3'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'

interface TransitionMatrixProps {
  playerId: number
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
  matrixData: MatrixData
) {
  const { matrix, shot_labels, raw_counts } = matrixData
  const n = shot_labels.length
  const { w, h } = calcSvgSize(n)

  // SVG クリア
  d3.select(svgEl).selectAll('*').remove()

  const svg = d3.select(svgEl)
    .attr('width', w)
    .attr('height', h)

  const g = svg.append('g')
    .attr('transform', `translate(${MARGIN_LEFT},${MARGIN_TOP})`)

  // カラースケール: 低頻度=cool(青), 高頻度=warm(赤) — matplotlib coolwarm相当
  const maxVal = d3.max(matrix.flat()) ?? 1
  const colorScale = d3.scaleSequential(d3.interpolateCool)
    .domain([maxVal > 0 ? maxVal : 1, 0])  // 反転: 低=青

  // coolwarm: 低=青(#3b4cc0)→白→高=赤(#b40426)
  function coolwarmColor(prob: number, max: number): string {
    if (max === 0) return '#1f2937'
    const t = prob / max  // 0(低)→1(高)
    // 制御点: 0=#3b4cc0, 0.5=#dddddd, 1=#b40426
    let r: number, g: number, b: number
    if (t < 0.5) {
      const u = t * 2
      r = Math.round(59 + (221 - 59) * u)
      g = Math.round(76 + (221 - 76) * u)
      b = Math.round(192 + (221 - 192) * u)
    } else {
      const u = (t - 0.5) * 2
      r = Math.round(221 + (180 - 221) * u)
      g = Math.round(221 + (4 - 221) * u)
      b = Math.round(221 + (38 - 221) * u)
    }
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
        .attr('fill', isDiag ? '#374151' : coolwarmColor(prob, maxVal))
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

  // ── X 軸ラベル（下部） ──
  const xLabelY = n * CELL + 8
  shot_labels.forEach((label, ci) => {
    g.append('text')
      .attr('x', ci * CELL + CELL / 2)
      .attr('y', xLabelY)
      .attr('text-anchor', 'start')
      .attr('dominant-baseline', 'middle')
      .attr('transform', `rotate(45, ${ci * CELL + CELL / 2}, ${xLabelY})`)
      .attr('fill', '#9ca3af')
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
      .attr('fill', '#9ca3af')
      .attr('font-size', 10)
      .text(truncate(label, 7))
  })

  // ── 軸タイトル（X軸: 下, Y軸: 左） ──
  svg.append('text')
    .attr('x', MARGIN_LEFT + (n * CELL) / 2)
    .attr('y', MARGIN_TOP + n * CELL + MARGIN_BOTTOM - 10)
    .attr('text-anchor', 'middle')
    .attr('fill', '#6b7280')
    .attr('font-size', 11)
    .text('次のショット →')

  svg.append('text')
    .attr('transform', `rotate(-90)`)
    .attr('x', -(MARGIN_TOP + (n * CELL) / 2))
    .attr('y', 14)
    .attr('text-anchor', 'middle')
    .attr('fill', '#6b7280')
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

export function TransitionMatrix({ playerId }: TransitionMatrixProps) {
  const svgRef = useRef<SVGSVGElement>(null)

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-shot-transition-matrix', playerId],
    queryFn: () =>
      apiGet<TransitionMatrixResponse>('/analysis/shot_transition_matrix', {
        player_id: playerId,
      }),
    enabled: !!playerId,
  })

  const matrixData = resp?.data
  const sampleSize = resp?.meta?.sample_size ?? 0

  // データが変わるたびに D3 で再描画
  useEffect(() => {
    if (!svgRef.current || !matrixData?.matrix?.length) return
    drawMatrix(svgRef.current, matrixData)

    // クリーンアップ: ツールチップ要素を削除
    return () => {
      d3.select('#transition-matrix-tooltip').remove()
    }
  }, [matrixData])

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

      {/* 凡例: coolwarm（低=青, 高=赤） */}
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <span>低頻度</span>
        <div
          className="h-3 w-32 rounded"
          style={{
            background:
              'linear-gradient(to right, #3b4cc0, #dddddd, #b40426)',
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
                  <span className="text-gray-300">
                    {fromLabel} → {toLabel}
                  </span>
                  <span className="ml-auto text-blue-400 shrink-0">
                    {seq.count}回
                  </span>
                  <span className="w-12 text-right text-gray-500 shrink-0">
                    {(seq.probability * 100).toFixed(1)}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
