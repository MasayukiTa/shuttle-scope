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
import { MIcon } from '@/components/common/MIcon'

export type ZoneCode =
  | 'BL' | 'BC' | 'BR'
  | 'ML' | 'MC' | 'MR'
  | 'NL' | 'NC' | 'NR'

export const ZONE_GRID: ZoneCode[][] = [
  ['BL', 'BC', 'BR'],  // 奥 (back, ベースライン側)
  ['ML', 'MC', 'MR'],  // 中
  ['NL', 'NC', 'NR'],  // 手前 (net 側)
]

const ZONE_LABEL_JP: Record<ZoneCode, string> = {
  BL: '左奥', BC: '中央奥', BR: '右奥',
  ML: '左中', MC: '中央', MR: '右中',
  NL: '左手前', NC: '中央手前', NR: '右手前',
}

interface Props {
  /** プロンプト (例: "サーブ打点を選択") */
  prompt: string
  /** [取消][次へ] の代わりにカスタムボタンを出すなら */
  primaryLabel?: string  // 既定: '確定'
  cancelLabel?: string   // 既定: '取消'
  /** primary 押下時の callback。staged zone がない場合は呼ばれない */
  onCommit: (zone: ZoneCode) => void
  onCancel: () => void
  /** コートを描画する物理的な座標域: [0..1] x [0..1] の中央付近に置く */
  courtRect?: { x: number; y: number; w: number; h: number }
}

/** ベース台 (動画 pause 状態の) 上に重ねるコート + 9 zone + 入力 UI */
export function AnnotateOverlay({
  prompt,
  primaryLabel = '確定',
  cancelLabel = '取消',
  onCommit,
  onCancel,
  courtRect = { x: 0.15, y: 0.10, w: 0.70, h: 0.70 },
}: Props) {
  const courtRef = useRef<HTMLDivElement | null>(null)
  const [staged, setStaged] = useState<ZoneCode | null>(null)
  const [magnifier, setMagnifier] = useState<{ x: number; y: number } | null>(null)

  // タップ → snap to nearest zone
  const handleTap = useCallback((clientX: number, clientY: number) => {
    const rect = courtRef.current?.getBoundingClientRect()
    if (!rect) return
    const nx = (clientX - rect.left) / rect.width
    const ny = (clientY - rect.top) / rect.height
    if (nx < 0 || nx > 1 || ny < 0 || ny > 1) return
    const col = Math.min(2, Math.max(0, Math.floor(nx * 3)))
    const row = Math.min(2, Math.max(0, Math.floor(ny * 3)))
    setStaged(ZONE_GRID[row][col])
  }, [])

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
      <div className="flex-1 relative" onClick={onClick}>
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
                      {ZONE_LABEL_JP[z]}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>

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
          {cancelLabel}
        </button>
        <div className="text-xs text-gray-300 font-mono px-2 min-w-[60px] text-center">
          {staged ? `→ ${staged}` : 'タップ'}
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
            {primaryLabel}
            <MIcon name="play_arrow" size={14} />
          </span>
        </button>
      </div>
    </div>
  )
}
