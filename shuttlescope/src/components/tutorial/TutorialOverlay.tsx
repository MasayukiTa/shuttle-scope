/**
 * インタラクティブ チュートリアル overlay (自前実装, no driver.js)。
 *
 * - step ごとに「target 要素をスポットライト + 赤パルスリングで強調 + 吹き出し」
 *   または「中央モーダル」(target 省略時) を出す。
 * - 操作: 前へ / 次へ(完了) / スキップ(今回だけ閉じる) / 次回は表示しない(以後出さない)
 * - キーボード: ← / → / Enter で移動、Esc で閉じる
 * - 進行は /api/tutorials/{id}/step に POST。完了/次回非表示は status を伴う。
 *
 * step は新形式 (titleKey/bodyKey) と旧形式 (title/body) の両方を受ける。
 * tutorial 自体のタイトルも titleKey 推奨で、なければ title を使う。
 *
 * onClose の status:
 *   'completed'  = 完了 (再表示しない)
 *   'skipped'    = 次回は表示しない (再表示しない)
 *   'aborted'    = 今回だけ閉じる (次回また自動表示される)
 */
import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'
import { MIcon } from '@/components/common/MIcon'
import { trackTutorialStep } from '@/utils/analytics'
import { useDemoModeStore } from '@/store/demoModeStore'

/**
 * tutorial step: titleKey/bodyKey 形式 (新) を推奨。
 * title/body 直書き形式 (旧) も後方互換のため許容。
 */
export type TutorialStep =
  | { target?: string; titleKey: string; bodyKey: string; title?: never; body?: never }
  | { target?: string; title: string; body: string; titleKey?: never; bodyKey?: never }

export interface TutorialDef {
  id: string
  /** 新形式: i18n key */
  titleKey?: string
  /** 旧形式: 直書き */
  title?: string
  steps: TutorialStep[]
}

interface Props {
  tutorial: TutorialDef
  onClose: (status: 'completed' | 'skipped' | 'aborted') => void
  startStep?: number
}

interface TargetGeom {
  rect: { top: number; left: number; width: number; height: number }
  tip: { top: number; left: number }
  /** 吹き出しから見て target がある方向 (矢印を出す向き) */
  arrow: 'up' | 'down' | 'left' | 'right'
}

const TIP_W = 320
const TIP_H_EST = 200
const PAD = 6

function resolveText(t: (k: string) => string, key: string | undefined, fallback: string | undefined): string {
  if (key) return t(key)
  return fallback ?? ''
}

export function TutorialOverlay({ tutorial, onClose, startStep = 0 }: Props) {
  const { t } = useTranslation()
  const [idx, setIdx] = useState(startStep)
  const step = tutorial.steps[idx]
  const last = idx === tutorial.steps.length - 1
  const [geom, setGeom] = useState<TargetGeom | null>(null)
  const demoActive = useDemoModeStore((s) => s.active)
  // 直前の移動方向 (対象要素が画面に無いステップを自動スキップする向き)
  const dirRef = useRef<1 | -1>(1)

  const tutorialTitle = useMemo(
    () => resolveText(t, tutorial.titleKey, tutorial.title) || tutorial.id,
    [t, tutorial.titleKey, tutorial.title, tutorial.id],
  )
  const stepTitle = resolveText(t, step?.titleKey, step?.title)
  const stepBody = resolveText(t, step?.bodyKey, step?.body)

  const recompute = useCallback(() => {
    if (!step?.target) { setGeom(null); return }
    const el = document.querySelector(step.target) as HTMLElement | null
    if (!el) { setGeom(null); return }
    const r = el.getBoundingClientRect()
    // スポットライト矩形: target の周囲に PAD 分だけ余白を足して切り抜く。
    // 画面内にクランプして、丸角の切り抜き (box-shadow) がはみ出さないようにする。
    const VW = window.innerWidth
    const VH = window.innerHeight
    const rectTop = Math.max(0, r.top - PAD)
    const rectLeft = Math.max(0, r.left - PAD)
    const rectBottom = Math.min(VH, r.bottom + PAD)
    const rectRight = Math.min(VW, r.right + PAD)
    const rect = {
      top: rectTop,
      left: rectLeft,
      width: Math.max(0, rectRight - rectLeft),
      height: Math.max(0, rectBottom - rectTop),
    }
    // 吹き出しは「対象の隣」に置き、対象の切り抜きには決して重ねない。
    // 下 → 上 → 右 → 左 の順に、対象の外側へ収まる空きを探す。
    const GAP = 14 // 対象と吹き出しの間隔
    let top: number
    let left: number
    let arrow: 'up' | 'down' | 'left' | 'right'
    const spaceBelow = VH - rectBottom
    const spaceAbove = rectTop
    const spaceRight = VW - rectRight
    const spaceLeft = rectLeft
    if (spaceBelow >= TIP_H_EST + GAP) {
      // 対象の下
      top = rectBottom + GAP
      left = rect.left + rect.width / 2 - TIP_W / 2
      arrow = 'up' // 矢印は上 (対象の方) を指す
    } else if (spaceAbove >= TIP_H_EST + GAP) {
      // 対象の上
      top = rectTop - GAP - TIP_H_EST
      left = rect.left + rect.width / 2 - TIP_W / 2
      arrow = 'down'
    } else if (spaceRight >= TIP_W + GAP) {
      // 対象の右
      left = rectRight + GAP
      top = rect.top + rect.height / 2 - TIP_H_EST / 2
      arrow = 'left'
    } else if (spaceLeft >= TIP_W + GAP) {
      // 対象の左
      left = rectLeft - GAP - TIP_W
      top = rect.top + rect.height / 2 - TIP_H_EST / 2
      arrow = 'right'
    } else {
      // どの辺にも収まらない大きな対象: 下に重ねず、画面下端に寄せて置く。
      // 矢印は対象中心の向きに合わせる。
      top = VH - TIP_H_EST - 8
      left = rect.left + rect.width / 2 - TIP_W / 2
      arrow = 'up'
    }
    // 画面内にクランプ (対象の隣という原則は保ちつつ、端で見切れないようにする)
    top = Math.max(8, Math.min(VH - TIP_H_EST - 8, top))
    left = Math.max(8, Math.min(VW - TIP_W - 8, left))
    setGeom({ rect, tip: { top, left }, arrow })
  }, [step])

  useEffect(() => {
    trackTutorialStep(tutorial.id, idx, 'viewed')
    void apiPost(`/tutorials/${tutorial.id}/step`, { step: idx }).catch(() => {})
    if (step?.target) {
      const el = document.querySelector(step.target) as HTMLElement | null
      try { el?.scrollIntoView({ behavior: 'smooth', block: 'center' }) } catch { /* ignore */ }
      const tm = window.setTimeout(recompute, 320)
      // A-19: 対象要素が今の画面状態に存在しない (例: ラリー待機中は打点ゾーン/ショット種別が
      // 未表示) ステップは、見えない物の説明になるので移動方向にスキップする。
      // 遅れて現れる要素に備え、少し待って再確認してから判断する。
      // 移動先が無い (先頭/末尾) ときは中央モーダルのまま表示する。
      const skipTm = window.setTimeout(() => {
        if (document.querySelector(step.target as string)) return
        const nextIdx = idx + dirRef.current
        if (nextIdx >= 0 && nextIdx < tutorial.steps.length) setIdx(nextIdx)
      }, 900)
      return () => { window.clearTimeout(tm); window.clearTimeout(skipTm) }
    }
    setGeom(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, tutorial.id])

  useEffect(() => {
    if (!step?.target) return
    const h = () => recompute()
    window.addEventListener('resize', h)
    window.addEventListener('scroll', h, true)
    return () => {
      window.removeEventListener('resize', h)
      window.removeEventListener('scroll', h, true)
    }
  }, [step, recompute])

  const finish = useCallback(async (status: 'completed' | 'skipped') => {
    trackTutorialStep(tutorial.id, idx, status)
    try { await apiPost(`/tutorials/${tutorial.id}/step`, { step: idx, status }) } catch { /* ignore */ }
    onClose(status)
  }, [tutorial.id, idx, onClose])

  const abort = useCallback(() => {
    trackTutorialStep(tutorial.id, idx, 'aborted')
    onClose('aborted')
  }, [tutorial.id, idx, onClose])

  const goNext = useCallback(() => {
    if (last) void finish('completed')
    else { dirRef.current = 1; setIdx((i) => i + 1) }
  }, [last, finish])

  const goPrev = useCallback(() => {
    dirRef.current = -1
    setIdx((i) => Math.max(0, i - 1))
  }, [])

  // キーボードナビ: input/textarea/contenteditable に focus 中は無視
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null
      const tag = tgt?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tgt?.isContentEditable) return
      if (e.key === 'Escape') { e.preventDefault(); abort() }
      else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); goNext() }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); goPrev() }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [abort, goNext, goPrev])

  if (!step) return null

  const total = tutorial.steps.length
  const controls = (
    <Controls
      idx={idx}
      last={last}
      onPrev={goPrev}
      onNext={goNext}
      onSkip={abort}
      onNever={() => void finish('skipped')}
    />
  )

  const header = (
    <Header
      tutorialTitle={tutorialTitle}
      idx={idx}
      total={total}
      demoActive={demoActive}
    />
  )

  // 中央モーダル
  if (!step.target || !geom) {
    return (
      <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
        <div className="bg-white dark:bg-gray-800 max-w-md w-full rounded-lg shadow-xl p-5">
          {header}
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mt-3">{stepTitle}</h3>
          <div className="mt-2 text-base leading-relaxed text-gray-700 dark:text-gray-200 whitespace-pre-wrap max-h-[40vh] overflow-y-auto">
            {stepBody}
          </div>
          {controls}
        </div>
      </div>
    )
  }

  // スポットライト + 吹き出し
  //   方針 (仙台大 要望3):
  //   - 対象は「切り抜いて明るいまま」見せる。暗幕は 1 枚の全面オーバーレイに
  //     box-shadow で対象の形の穴を開けて作る (4 枠方式の隙間・丸角ずれ・発光被りを排除)。
  //   - 吹き出しは対象の「隣」に置き、対象には決して重ねない (recompute で配置)。
  //   - 暗幕は外側クリックを吸収するが、切り抜き窓 (対象) 上はクリックを素通しして
  //     元の操作を残す。穴の内側には発光や吹き出しを被せない。
  return (
    <div className="fixed inset-0 z-[300]">
      <Spotlight geom={geom} />
      {/* 吹き出し: 対象の隣。矢印 + 注意揺れ */}
      <div
        className="fixed w-80 bg-white dark:bg-gray-800 rounded-lg shadow-2xl p-4 border-2 border-red-500/70 dark:border-red-400/60 z-[302] relative tutorial-tooltip-attention"
        style={{ top: geom.tip.top, left: geom.tip.left }}
      >
        <span className={`tutorial-tooltip-arrow tutorial-tooltip-arrow-${geom.arrow}`} aria-hidden />
        {/* ステップ番号バッジ (右上) — 一目で進捗が分かる */}
        <div
          className="absolute -top-3 -right-3 flex items-center justify-center w-9 h-9 rounded-full bg-red-600 text-white text-xs font-bold shadow-md ring-2 ring-white dark:ring-gray-800"
          aria-hidden
        >
          {idx + 1}/{total}
        </div>
        {header}
        <h3 className="text-base font-bold text-gray-900 dark:text-gray-100 mt-2">{stepTitle}</h3>
        <div className="mt-1.5 text-sm leading-relaxed text-gray-700 dark:text-gray-200 whitespace-pre-wrap max-h-[40vh] overflow-y-auto">
          {stepBody}
        </div>
        {controls}
      </div>
    </div>
  )
}

/**
 * スポットライト: 対象を切り抜いて明るく見せる暗幕 + 外側クリック吸収枠 +
 * 対象外周の赤リング/リップル + 「ここを見て」矢印。穴の内側には何も被せない。
 */
function Spotlight({ geom }: { geom: TargetGeom }) {
  const absorb = (e: React.MouseEvent) => e.stopPropagation()
  const { rect } = geom
  const VW = window.innerWidth, VH = window.innerHeight
  const T = rect.top
  const L = rect.left
  const B = rect.top + rect.height
  const R = rect.left + rect.width
  const z = 300
  // 「ここを見て」矢印は対象の上端中央の少し上 (穴の外) に浮かせる。
  const pointerTop = Math.max(8, rect.top - 30)
  const pointerLeft = rect.left + rect.width / 2
  const boxStyle = { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
  return (
    <>
      {/* 暗幕 = 全面 1 枚。box-shadow で対象の形に穴を開けて切り抜く。
          穴の内側 (対象) は明るいまま、クリックも下の UI に届く (pointer-events:none)。 */}
      <div className="tutorial-spotlight-hole fixed" style={boxStyle} aria-hidden />
      {/* 暗幕の外側クリックを吸収する 4 枠。穴の上には置かないので対象は操作できる。 */}
      <div onClick={absorb} className="fixed" style={{ top: 0, left: 0, width: '100%', height: Math.max(0, T), zIndex: z }} />
      <div onClick={absorb} className="fixed" style={{ top: B, left: 0, width: '100%', height: Math.max(0, VH - B), zIndex: z }} />
      <div onClick={absorb} className="fixed" style={{ top: T, left: 0, width: Math.max(0, L), height: Math.max(0, B - T), zIndex: z }} />
      <div onClick={absorb} className="fixed" style={{ top: T, left: R, width: Math.max(0, VW - R), height: Math.max(0, B - T), zIndex: z }} />
      {/* 対象の外周だけを縁取る赤リング + 外へ拡がるリップル (内側は覆わない)。 */}
      <div className="tutorial-ring" style={boxStyle} aria-hidden />
      <div className="tutorial-ring-ripple" style={boxStyle} aria-hidden />
      {/* 「ここを見て」浮遊矢印 (対象の外に置く)。 */}
      <div className="tutorial-here-pointer" style={{ top: pointerTop, left: pointerLeft }} aria-hidden>▼</div>
    </>
  )
}

function Header({
  tutorialTitle, idx, total, demoActive,
}: {
  tutorialTitle: string; idx: number; total: number; demoActive: boolean
}) {
  const { t } = useTranslation()
  const pct = Math.round(((idx + 1) / Math.max(1, total)) * 100)
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-gray-500 dark:text-gray-400 inline-flex items-center gap-1">
          <MIcon name="school" size={14} />
          {t('auto.TutorialOverlay.header', { title: tutorialTitle, n: idx + 1, total })}
        </div>
        {demoActive && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500 text-white font-semibold whitespace-nowrap">
            {t('auto.TutorialOverlay.demo_chip')}
          </span>
        )}
      </div>
      <div className="mt-1 h-[2px] w-full bg-gray-200 dark:bg-gray-700 rounded">
        <div className="h-full bg-blue-600 rounded transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function Controls({
  idx, last, onPrev, onNext, onSkip, onNever,
}: {
  idx: number; last: boolean
  onPrev: () => void; onNext: () => void; onSkip: () => void; onNever: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center justify-between">
        <button
          onClick={onPrev}
          disabled={idx === 0}
          className="text-xs px-3 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 disabled:opacity-40"
        >
          {t('auto.TutorialOverlay.prev')}
        </button>
        <button
          onClick={onNext}
          className="text-xs px-3 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white inline-flex items-center gap-1"
        >
          {last ? t('auto.TutorialOverlay.done') : t('auto.TutorialOverlay.next')}
          {last ? <MIcon name="check" size={12} /> : <MIcon name="play_arrow" size={12} />}
        </button>
      </div>
      <div className="flex items-center justify-between text-[11px]">
        <button onClick={onSkip} className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-200">
          {t('auto.TutorialOverlay.skip')}
        </button>
        <button onClick={onNever} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 underline">
          {t('auto.TutorialOverlay.never')}
        </button>
      </div>
      <div className="text-[10px] italic text-gray-400 dark:text-gray-500 text-center">
        {t('auto.TutorialOverlay.kbd_hint')}
      </div>
    </div>
  )
}
