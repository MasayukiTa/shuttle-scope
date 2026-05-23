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
import { useEffect, useState, useCallback, useMemo } from 'react'
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
    const rect = { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 }
    const belowTop = r.bottom + 12
    const aboveTop = r.top - 12 - TIP_H_EST
    let top: number
    let arrow: 'up' | 'down' | 'left' | 'right' = 'up'
    if (belowTop + TIP_H_EST <= window.innerHeight) {
      top = belowTop
      arrow = 'up' // 吹き出しは target の下 → 矢印は上向き
    } else if (aboveTop >= 8) {
      top = aboveTop
      arrow = 'down' // 吹き出しは target の上 → 矢印は下向き
    } else {
      top = Math.max(8, Math.min(window.innerHeight - TIP_H_EST - 8, r.top))
      arrow = r.left > window.innerWidth / 2 ? 'right' : 'left'
    }
    const left = Math.max(8, Math.min(window.innerWidth - TIP_W - 8, r.left + r.width / 2 - TIP_W / 2))
    setGeom({ rect, tip: { top, left }, arrow })
  }, [step])

  useEffect(() => {
    trackTutorialStep(tutorial.id, idx, 'viewed')
    void apiPost(`/tutorials/${tutorial.id}/step`, { step: idx }).catch(() => {})
    if (step?.target) {
      const el = document.querySelector(step.target) as HTMLElement | null
      try { el?.scrollIntoView({ behavior: 'smooth', block: 'center' }) } catch { /* ignore */ }
      const tm = window.setTimeout(recompute, 320)
      return () => window.clearTimeout(tm)
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
    else setIdx((i) => i + 1)
  }, [last, finish])

  const goPrev = useCallback(() => {
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
  //   注意誘導を最大化:
  //   - 暗幕は 0.78 まで濃く（周辺視を遮断）
  //   - 暗幕は pointer-events: auto で外側クリックを吸収（ユーザは強制的に target / 説明を見るしかない）
  //   - target 自体は元の操作を残すため、spotlight 矩形の上にだけ pointer-events:none の透明窓を被せる
  //   - 赤パルスリング + 外側へ拡大するリップル + target 上に浮遊する「↓」バウンスポインタ
  //   - tooltip は周辺視で気付かせる微小揺れ (うるさくない 6 秒周期)
  const arrowClass = `tutorial-tooltip-arrow tutorial-tooltip-arrow-${geom.arrow}`
  // 「ここを見て」ポインタの位置: target の上端中央から 32px 上に浮かせる
  const pointerTop = Math.max(8, geom.rect.top - 32)
  const pointerLeft = geom.rect.left + geom.rect.width / 2
  return (
    <div className="fixed inset-0 z-[300]">
      {/* 1) 暗幕を 4 枠で target を囲む = 外側クリック吸収（強制注意）+ target 内は素通し */}
      {(() => {
        const dark = 'rgba(0,0,0,0.78)'
        const absorb = (e: React.MouseEvent) => e.stopPropagation()
        const VW = window.innerWidth, VH = window.innerHeight
        const T = Math.max(0, geom.rect.top)
        const L = Math.max(0, geom.rect.left)
        const B = Math.min(VH, geom.rect.top + geom.rect.height)
        const R = Math.min(VW, geom.rect.left + geom.rect.width)
        return (
          <>
            {/* 上 */}
            <div onClick={absorb} className="fixed" style={{ top: 0, left: 0, width: '100%', height: T, background: dark, zIndex: 300 }} />
            {/* 下 */}
            <div onClick={absorb} className="fixed" style={{ top: B, left: 0, width: '100%', height: Math.max(0, VH - B), background: dark, zIndex: 300 }} />
            {/* 左 */}
            <div onClick={absorb} className="fixed" style={{ top: T, left: 0, width: L, height: Math.max(0, B - T), background: dark, zIndex: 300 }} />
            {/* 右 */}
            <div onClick={absorb} className="fixed" style={{ top: T, left: R, width: Math.max(0, VW - R), height: Math.max(0, B - T), background: dark, zIndex: 300 }} />
          </>
        )
      })()}
      {/* 2) 赤パルスリング (1 重目) */}
      <div
        className="tutorial-ring"
        style={{ top: geom.rect.top, left: geom.rect.left, width: geom.rect.width, height: geom.rect.height }}
      />
      {/* 3) 外側に拡がるリップル (2 重発信で視野の周辺視に強く訴える) */}
      <div
        className="tutorial-ring-ripple"
        style={{ top: geom.rect.top, left: geom.rect.left, width: geom.rect.width, height: geom.rect.height }}
        aria-hidden
      />
      {/* 4) 「ここを見て」浮遊矢印 (バウンス) — Material Symbols ではなく文字で軽量 */}
      <div
        className="tutorial-here-pointer"
        style={{ top: pointerTop, left: pointerLeft }}
        aria-hidden
      >▼</div>
      {/* 5) 吹き出し: 矢印 + 注意揺れ */}
      <div
        className="fixed w-80 bg-white dark:bg-gray-800 rounded-lg shadow-2xl p-4 border-2 border-red-500/70 dark:border-red-400/60 z-[302] relative tutorial-tooltip-attention"
        style={{ top: geom.tip.top, left: geom.tip.left }}
      >
        <span className={arrowClass} aria-hidden />
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
