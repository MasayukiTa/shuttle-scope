/**
 * MobileAnnotate / AnnotateOverlay (R48 step 4)
 *
 * Annotate mode の入力 overlay。動画 pause 状態の上に半透明で重ね、
 * コート 9 zone snap + touch-magnifier (touch 中だけズーム表示) + staging→commit の
 * 2 段階確定を提供する。
 *
 * - 9 zone: backend `Stroke.hit_zone / land_zone` の BL/BC/BR/ML/MC/MR/NL/NC/NR
 *   表記に揃える (B=Back, M=Mid, N=Net / L=Left, C=Center, R=Right)
 * - touch-magnifier: 指がついている間だけ、その位置周辺 1.5x のフローティング
 *   ループ (虫眼鏡) を上に出してタップ位置を視認しやすくする。
 * - staging: タップで「赤い○ 仮置き」状態。下部の [次へ ▶] で commit、
 *   [取消] で破棄。複数タップ可能、最後のタップが採用される。
 * - 確定後の commit は親 (MobileAnnotatePage) に zone code を返すだけ。
 *   実 DB 書き込みは親の Pass 別 step machine が enqueue する。
 */
import { useRef, useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { calibratedTapToCell, fallbackTapToCell, type Quad } from '@/utils/courtHomography'

export type ZoneCode =
  | 'BL' | 'BC' | 'BR'
  | 'ML' | 'MC' | 'MR'
  | 'NL' | 'NC' | 'NR'

export const ZONE_GRID: ZoneCode[][] = [
  ['BL', 'BC', 'BR'],  // 奥 (back, ベースライン側)
  ['ML', 'MC', 'MR'],  // 中
  ['NL', 'NC', 'NR'],  // 手前 (net 側)
]

interface Props {
  /** プロンプト (例: "サーブ打点を選択") */
  prompt: string
  /** [取消][次へ] の代わりにカスタムボタンを出すなら (未指定は i18n の既定) */
  primaryLabel?: string
  cancelLabel?: string
  /** primary 押下時の callback。staged zone がない場合は呼ばれない */
  onCommit: (zone: ZoneCode) => void
  onCancel: () => void
  /** 既存値の修正時に最初から選択済みにするゾーン (そのまま確定すれば既存値を保持) */
  initialZone?: ZoneCode | null
  /** コートを描画する物理的な座標域: [0..1] x [0..1] の中央付近に置く */
  courtRect?: { x: number; y: number; w: number; h: number }
  /**
   * 動画上の実コート 4 隅 (TL, TR, BR, BL) を正規化座標 [0,1] で渡すと、
   * タップ判定とグリッド描画をその四角形 (= 実際のコート) に合わせる。
   * これにより撮影方向が斜め・後方・横でも、動画に写ったコートの «真ん中» を
   * そのままタップして選べる。未指定なら従来の軸平行な固定枠にフォールバックする。
   * court-calib-{matchId} の 6 点のうち先頭 4 点がこれに相当する。
   */
  courtQuad?: Quad | null
  /**
   * courtQuad を使うとき、入力対象がコートのどちら半面か。
   *   'near' = 手前 (ネット〜手前ベースライン)。
   *   'far'  = 奥   (ネット〜奥ベースライン)。
   * 片半面を 3×3 に割り当てる。未指定時は 'near'。
   */
  half?: 'near' | 'far'
}

/** ベース台 (動画 pause 状態の) 上に重ねるコート + 9 zone + 入力 UI */
export function AnnotateOverlay({
  prompt,
  primaryLabel,
  cancelLabel,
  onCommit,
  onCancel,
  initialZone = null,
  courtRect ={ x: 0.15, y: 0.10, w: 0.70, h: 0.70 },
  courtQuad = null,
  half = 'near',
}: Props) {
  const { t } = useTranslation()
  const primaryText = primaryLabel ?? t('auto.AnnotateOverlay.confirm')
  const cancelText = cancelLabel ?? t('auto.AnnotateOverlay.cancel')
  const courtRef = useRef<HTMLDivElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [staged, setStaged] = useState<ZoneCode | null>(initialZone)
  const [magnifier, setMagnifier] = useState<{ x: number; y: number } | null>(null)

  // タップ → snap to nearest zone
  const handleTap = useCallback((clientX: number, clientY: number) => {
    // (1) キャリブ済みコート四角形がある場合: コンテナ全体を基準に正規化し、
    //     実コートの四角形へ逆写像して (u,v) を得る。撮影方向が斜め・後方・横でも
    //     動画に写ったコートの «真ん中» がそのまま中央マスに当たる。
    if (courtQuad) {
      const crect = containerRef.current?.getBoundingClientRect()
      if (!crect) return
      const px = (clientX - crect.left) / crect.width
      const py = (clientY - crect.top) / crect.height
      const cell = calibratedTapToCell(courtQuad, px, py, half)
      if (!cell) return
      // calibratedTapToCell の row は «画面上の並び» (0=上, 2=下)。ZONE_GRID は
      // row0=back(ベースライン) / row2=net(ネット際)。
      //   far 半面  = 画面上の row がそのまま back→net
      //   near 半面 = 画面上の row を反転 (2-row): 上(ネット際)→net, 下(ベースライン)→back
      const zoneRow = half === 'far' ? cell.row : 2 - cell.row
      setStaged(ZONE_GRID[zoneRow][cell.col])
      return
    }
    // (2) フォールバック: 従来の軸平行な固定枠。枠内で 3×3 に割り当てる。
    //     枠外は «無視» せず端マスへ丸める (旧実装の死角を解消)。
    const rect = courtRef.current?.getBoundingClientRect()
    if (!rect) return
    const nx = (clientX - rect.left) / rect.width
    const ny = (clientY - rect.top) / rect.height
    const { row, col } = fallbackTapToCell(nx, ny)
    setStaged(ZONE_GRID[row][col])
  }, [courtQuad, half])

  const onTouchStart: React.TouchEventHandler<HTMLDivElement> = (e) => {
    const t = e.touches[0]
    setMagnifier({ x: t.clientX, y: t.clientY })
    handleTap(t.clientX, t.clientY)
  }

  const onTouchMove: React.TouchEventHandler<HTMLDivElement> = (e) => {
    const t = e.touches[0]
    setMagnifier({ x: t.clientX, y: t.clientY })
    handleTap(t.clientX, t.clientY)
  }

  const onTouchEnd: React.TouchEventHandler<HTMLDivElement> = () => {
    setMagnifier(null)
  }

  const onClick: React.MouseEventHandler<HTMLDivElement> = (e) => {
    // マウス (デスクトップ debugging) 用
    handleTap(e.clientX, e.clientY)
  }

  // ESC または下スワイプで取消 (アクセシビリティ + 誤反応救済)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
      if (e.key === 'Enter' && staged) onCommit(staged)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel, onCommit, staged])

  return (
    <div className="absolute inset-0 bg-black/40 backdrop-blur-[1px] flex flex-col">
      {/* プロンプト */}
      <div className="bg-black/80 text-center text-xs py-1.5 text-yellow-200 font-medium border-b border-yellow-700/40">
        {prompt}
      </div>

      {/* コート + 9 zone */}
      <div
        ref={containerRef}
        className="flex-1 relative"
        onClick={onClick}
        onTouchStart={courtQuad ? onTouchStart : undefined}
        onTouchMove={courtQuad ? onTouchMove : undefined}
        onTouchEnd={courtQuad ? onTouchEnd : undefined}
        style={courtQuad ? { touchAction: 'none' } : undefined}
      >
        {courtQuad ? (
          // ── キャリブ済み: 実コート四角形に沿って 9 マスを描く ──────────────
          <CalibratedCourtGrid quad={courtQuad} half={half} staged={staged} t={t} />
        ) : (
          <div
            ref={courtRef}
            className="absolute"
            style={{
              left: `${courtRect.x * 100}%`,
              top: `${courtRect.y * 100}%`,
              width: `${courtRect.w * 100}%`,
              height: `${courtRect.h * 100}%`,
              touchAction: 'none',
            }}
            onTouchStart={onTouchStart}
            onTouchMove={onTouchMove}
            onTouchEnd={onTouchEnd}
          >
            {/* 9 マスのグリッド */}
            <div className="absolute inset-0 grid grid-cols-3 grid-rows-3 border-2 border-white/70">
              {ZONE_GRID.flat().map((z) => {
                const isStaged = staged === z
                return (
                  <div
                    key={z}
                    className={`relative flex items-center justify-center border border-white/50 ${
                      isStaged ? 'bg-red-500/50' : 'bg-blue-500/10'
                    }`}
                    style={{ minHeight: '44px', minWidth: '44px' }}
                  >
                    <span className="text-[10px] text-white/80 absolute top-0.5 left-1 font-mono">
                      {z}
                    </span>
                    {isStaged && (
                      <span className="text-[11px] text-white font-bold inline-flex items-center gap-1">
                        <MIcon name="check" size={11} />
                        {t(`zones.${z}`)}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* touch magnifier: 指の周辺を 1.5x で別レイヤに表示 */}
        {magnifier && (
          <div
            className="absolute pointer-events-none border-2 border-yellow-300 rounded-full overflow-hidden shadow-2xl"
            style={{
              width: 120,
              height: 120,
              left: magnifier.x - 60,
              top: magnifier.y - 140,  // 指の上に表示 (指で隠れないように)
              backgroundColor: 'rgba(0,0,0,0.85)',
            }}
          >
            {/* 中心十字 */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="absolute left-0 right-0 top-1/2 h-px bg-yellow-300/60" />
              <div className="absolute top-0 bottom-0 left-1/2 w-px bg-yellow-300/60" />
              {staged && (
                <span className="text-yellow-200 font-bold text-lg z-10">{staged}</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 下部 [取消] [確定] */}
      <div className="bg-black/90 px-3 py-2 flex items-center gap-2 border-t border-gray-800">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-2 rounded bg-gray-700 text-white text-xs flex-1"
        >
          {cancelText}
        </button>
        <div className="text-xs text-gray-300 font-mono px-2 min-w-[60px] text-center">
          {staged ? `→ ${staged}` : t('auto.AnnotateOverlay.tap')}
        </div>
        <button
          type="button"
          disabled={!staged}
          onClick={() => staged && onCommit(staged)}
          className={`px-3 py-2 rounded text-white text-xs flex-1 ${
            staged ? 'bg-green-600' : 'bg-gray-700 opacity-40'
          }`}
        >
          <span className="inline-flex items-center gap-1 justify-center">
            {primaryText}
            <MIcon name="play_arrow" size={14} />
          </span>
        </button>
      </div>
    </div>
  )
}

// ─── キャリブ済みコートの 9 マス描画 ──────────────────────────────────────
//
// 実コート四角形 quad の指定半面を 3×3 に分け、各セルを SVG polygon で描く。
// セル角は双一次写像 P(u,v) でコンテナ正規化座標 (0..1) に戻し、SVG の
// viewBox 0..1 (preserveAspectRatio=none) にそのまま載せる。これで動画上の
// 実際のコート形状 (斜め・後方・横) に沿った格子になり、タップ判定 (handleTap)
// と見た目が一致する。
function bilerp(quad: Quad, u: number, v: number): { x: number; y: number } {
  const [tl, tr, br, bl] = quad
  const x = (1 - u) * (1 - v) * tl.x + u * (1 - v) * tr.x + u * v * br.x + (1 - u) * v * bl.x
  const y = (1 - u) * (1 - v) * tl.y + u * (1 - v) * tr.y + u * v * br.y + (1 - u) * v * bl.y
  return { x, y }
}

function CalibratedCourtGrid({
  quad,
  half,
  staged,
  t,
}: {
  quad: Quad
  half: 'near' | 'far'
  staged: ZoneCode | null
  t: (k: string) => string
}) {
  // gridRow/gridCol は画面上の並び (0=上, 2=下 / 0=左, 2=右)。
  // それを ZONE_GRID の意味ラベルに割り当てる (handleTap と同じ規則)。
  const cells: Array<{ pts: string; zone: ZoneCode; cx: number; cy: number }> = []
  for (let gr = 0; gr < 3; gr++) {
    for (let gc = 0; gc < 3; gc++) {
      // この半面内でのセル角 (u, v は quad 全体座標)。
      const u0 = gc / 3
      const u1 = (gc + 1) / 3
      const vTop = half === 'far' ? (gr / 3) * 0.5 : 0.5 + (gr / 3) * 0.5
      const vBot = half === 'far' ? ((gr + 1) / 3) * 0.5 : 0.5 + ((gr + 1) / 3) * 0.5
      const p00 = bilerp(quad, u0, vTop)
      const p10 = bilerp(quad, u1, vTop)
      const p11 = bilerp(quad, u1, vBot)
      const p01 = bilerp(quad, u0, vBot)
      const pts = `${p00.x},${p00.y} ${p10.x},${p10.y} ${p11.x},${p11.y} ${p01.x},${p01.y}`
      const zoneRow = half === 'far' ? gr : 2 - gr
      const zone = ZONE_GRID[zoneRow][gc]
      const cx = (p00.x + p10.x + p11.x + p01.x) / 4
      const cy = (p00.y + p10.y + p11.y + p01.y) / 4
      cells.push({ pts, zone, cx, cy })
    }
  }
  return (
    <svg
      className="absolute inset-0 w-full h-full pointer-events-none"
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
    >
      {cells.map((c) => {
        const isStaged = staged === c.zone
        return (
          <g key={c.zone}>
            <polygon
              points={c.pts}
              fill={isStaged ? 'rgba(239,68,68,0.5)' : 'rgba(59,130,246,0.1)'}
              stroke="rgba(255,255,255,0.6)"
              strokeWidth={0.004}
            />
            <text
              x={c.cx}
              y={c.cy}
              fill="rgba(255,255,255,0.85)"
              fontSize={0.035}
              textAnchor="middle"
              dominantBaseline="middle"
              style={{ fontFamily: 'monospace' }}
            >
              {isStaged ? t(`zones.${c.zone}`) : c.zone}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
