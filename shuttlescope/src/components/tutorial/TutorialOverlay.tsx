/**
 * インタラクティブ チュートリアル overlay (自前実装, no driver.js)。
 *
 * - step ごとに「target 要素をスポットライト + 赤パルスリングで強調 + 吹き出し」
 *   または「中央モーダル」(target 省略時) を出す。
 * - 操作: 前へ / 次へ(完了) / スキップ(今回だけ閉じる) / 次回は表示しない(以後出さない)
 * - 進行は /api/tutorials/{id}/step に POST。完了/次回非表示は status を伴う。
 *
 * onClose の status:
 *   'completed'  = 完了 (再表示しない)
 *   'skipped'    = 次回は表示しない (再表示しない)
 *   'aborted'    = 今回だけ閉じる (次回また自動表示される)
 */
import { useEffect, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'
import { MIcon } from '@/components/common/MIcon'
import { trackTutorialStep } from '@/utils/analytics'

export interface TutorialStep {
  /** 中央モーダルとして表示する場合は target 省略 */
  target?: string  // CSS selector (例: '[data-tutorial="annotator.modeTabs"]')
  title: string
  body: string
}

export interface TutorialDef {
  id: string
  title: string
  steps: TutorialStep[]
}

interface Props {
  tutorial: TutorialDef
  onClose: (status: 'completed' | 'skipped' | 'aborted') => void
  startStep?: number
}

interface TargetGeom {
  // target 要素の viewport 矩形 (スポットライト/リング用)
  rect: { top: number; left: number; width: number; height: number }
  // 吹き出し位置
  tip: { top: number; left: number }
}

const TIP_W = 320
const TIP_H_EST = 170
const PAD = 6  // リングと要素の隙間

export function TutorialOverlay({ tutorial, onClose, startStep = 0 }: Props) {
  const [idx, setIdx] = useState(startStep)
  const step = tutorial.steps[idx]
  const last = idx === tutorial.steps.length - 1
  const [geom, setGeom] = useState<TargetGeom | null>(null)

  const recompute = useCallback(() => {
    if (!step?.target) { setGeom(null); return }
    const el = document.querySelector(step.target) as HTMLElement | null
    if (!el) { setGeom(null); return }
    const r = el.getBoundingClientRect()
    const rect = { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 }
    // 吹き出しは要素の下、入らなければ上、それも無理なら右
    const belowTop = r.bottom + 12
    const aboveTop = r.top - 12 - TIP_H_EST
    let top: number
    if (belowTop + TIP_H_EST <= window.innerHeight) top = belowTop
    else if (aboveTop >= 8) top = aboveTop
    else top = Math.max(8, Math.min(window.innerHeight - TIP_H_EST - 8, r.top))
    const left = Math.max(8, Math.min(window.innerWidth - TIP_W - 8, r.left + r.width / 2 - TIP_W / 2))
    setGeom({ rect, tip: { top, left } })
  }, [step])

  useEffect(() => {
    trackTutorialStep(tutorial.id, idx, 'viewed')
    void apiPost(`/tutorials/${tutorial.id}/step`, { step: idx }).catch(() => {})
    // target を画面内へ → 次フレームで位置計算 (scroll 後に矩形が動くため)
    if (step?.target) {
      const el = document.querySelector(step.target) as HTMLElement | null
      try { el?.scrollIntoView({ behavior: 'smooth', block: 'center' }) } catch { /* ignore */ }
      const t = window.setTimeout(recompute, 320)
      return () => window.clearTimeout(t)
    }
    setGeom(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, tutorial.id])

  // resize / scroll に追随
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

  const finish = async (status: 'completed' | 'skipped') => {
    trackTutorialStep(tutorial.id, idx, status)
    try { await apiPost(`/tutorials/${tutorial.id}/step`, { step: idx, status }) } catch { /* ignore */ }
    onClose(status)
  }
  // 今回だけ閉じる (terminal status を送らない → 次回また自動表示)
  const abort = () => { trackTutorialStep(tutorial.id, idx, 'aborted'); onClose('aborted') }

  if (!step) return null

  const controls = (
    <Controls
      idx={idx}
      last={last}
      onPrev={() => setIdx((i) => Math.max(0, i - 1))}
      onNext={() => last ? void finish('completed') : setIdx((i) => i + 1)}
      onSkip={abort}
      onNever={() => void finish('skipped')}
    />
  )

  // 中央モーダル (target なし or 見つからない)
  if (!step.target || !geom) {
    return (
      <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
        <div className="bg-white dark:bg-gray-800 max-w-md w-full rounded-lg shadow-xl p-5">
          <Header tutorialTitle={tutorial.title} idx={idx} total={tutorial.steps.length} />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mt-3">{step.title}</h3>
          <p className="text-sm text-gray-700 dark:text-gray-200 mt-2 whitespace-pre-wrap">{step.body}</p>
          {controls}
        </div>
      </div>
    )
  }

  // target スポットライト + 赤パルスリング + 吹き出し
  return (
    <div className="fixed inset-0 z-[300]">
      {/* スポットライト: target の穴あき暗幕 (巨大 box-shadow で周囲だけ暗く) */}
      <div
        className="fixed pointer-events-none"
        style={{
          top: geom.rect.top, left: geom.rect.left, width: geom.rect.width, height: geom.rect.height,
          borderRadius: 8,
          boxShadow: '0 0 0 9999px rgba(0,0,0,0.55)',
          zIndex: 300,
        }}
      />
      {/* 赤パルスリング */}
      <div
        className="tutorial-ring"
        style={{ top: geom.rect.top, left: geom.rect.left, width: geom.rect.width, height: geom.rect.height }}
      />
      {/* 暗幕クリックで今回だけ閉じる (target 上のクリックは透過させ通常操作可) */}
      <div className="fixed inset-0 z-[300]" style={{ pointerEvents: 'none' }} />
      {/* 吹き出し */}
      <div
        className="fixed w-80 bg-white dark:bg-gray-800 rounded-lg shadow-2xl p-4 border border-gray-300 dark:border-gray-600 z-[302]"
        style={{ top: geom.tip.top, left: geom.tip.left }}
      >
        <Header tutorialTitle={tutorial.title} idx={idx} total={tutorial.steps.length} />
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mt-2">{step.title}</h3>
        <p className="text-xs text-gray-700 dark:text-gray-200 mt-1 whitespace-pre-wrap">{step.body}</p>
        {controls}
      </div>
    </div>
  )
}

function Header({ tutorialTitle, idx, total }: { tutorialTitle: string; idx: number; total: number }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="text-xs text-gray-500 dark:text-gray-400 inline-flex items-center gap-1">
        <MIcon name="school" size={14} />
        {t('auto.TutorialOverlay.header', { title: tutorialTitle, n: idx + 1, total })}
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
          {last ? '完了' : '次へ'}
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
    </div>
  )
}
