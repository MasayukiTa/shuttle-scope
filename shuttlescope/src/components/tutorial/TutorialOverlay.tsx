/**
 * 軽量チュートリアル overlay (independently rolled, no driver.js dep).
 *
 * - step ごとに「target セレクタ近傍に吹き出し」or 「中央モーダル」を出す
 * - スキップ / 次へ / 前へ ボタン
 * - 進行状況は /api/tutorials/{id}/step に POST
 * - 完了で /api/tutorials/{id}/step status=completed
 */
import { useEffect, useState } from 'react'
import { apiPost } from '@/api/client'
import { MIcon } from '@/components/common/MIcon'
import { trackTutorialStep } from '@/utils/analytics'

export interface TutorialStep {
  /** 中央モーダルとして表示する場合は target 省略 */
  target?: string  // CSS selector
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

export function TutorialOverlay({ tutorial, onClose, startStep = 0 }: Props) {
  const [idx, setIdx] = useState(startStep)
  const step = tutorial.steps[idx]
  const last = idx === tutorial.steps.length - 1
  const [pos, setPos] = useState<{ top: number; left: number; align: 'top' | 'bottom' } | null>(null)

  useEffect(() => {
    trackTutorialStep(tutorial.id, idx, 'viewed')
    // backend に進行を記録 (best-effort)
    void apiPost(`/tutorials/${tutorial.id}/step`, { step: idx }).catch(() => {})
    // target 位置計算
    if (step?.target) {
      const el = document.querySelector(step.target) as HTMLElement | null
      if (el) {
        const r = el.getBoundingClientRect()
        const below = r.bottom + 12
        const above = Math.max(12, r.top - 12 - 120)
        const useAbove = below + 180 > window.innerHeight && r.top > 200
        setPos({
          top: useAbove ? above : below,
          left: Math.max(12, Math.min(window.innerWidth - 340, r.left + r.width / 2 - 160)),
          align: useAbove ? 'top' : 'bottom',
        })
        try { el.scrollIntoView({ behavior: 'smooth', block: 'center' }) } catch { /* ignore */ }
      } else {
        setPos(null)
      }
    } else {
      setPos(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, tutorial.id])

  const finish = async (status: 'completed' | 'skipped') => {
    trackTutorialStep(tutorial.id, idx, status)
    try {
      await apiPost(`/tutorials/${tutorial.id}/step`, { step: idx, status })
    } catch { /* ignore */ }
    onClose(status)
  }

  if (!step) return null

  // 中央モーダル (target 指定なし)
  if (!step.target || !pos) {
    return (
      <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
        <div className="bg-white dark:bg-gray-800 max-w-md w-full rounded-lg shadow-xl p-5">
          <Header tutorialTitle={tutorial.title} idx={idx} total={tutorial.steps.length} onSkip={() => void finish('skipped')} />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mt-3">{step.title}</h3>
          <p className="text-sm text-gray-700 dark:text-gray-200 mt-2 whitespace-pre-wrap">{step.body}</p>
          <Footer
            idx={idx}
            last={last}
            onPrev={() => setIdx((i) => Math.max(0, i - 1))}
            onNext={() => last ? void finish('completed') : setIdx((i) => i + 1)}
          />
        </div>
      </div>
    )
  }

  // target 近傍吹き出し
  return (
    <div className="fixed inset-0 z-[300] pointer-events-none">
      {/* 暗幕 (target の周辺だけ少し明るく出来ると良いが今は全体淡め) */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[1px] pointer-events-auto" onClick={() => void finish('skipped')} />
      <div
        className="absolute w-80 bg-white dark:bg-gray-800 rounded-lg shadow-2xl p-4 pointer-events-auto border border-gray-300 dark:border-gray-600"
        style={{ top: pos.top, left: pos.left }}
        onClick={(e) => e.stopPropagation()}
      >
        <Header tutorialTitle={tutorial.title} idx={idx} total={tutorial.steps.length} onSkip={() => void finish('skipped')} />
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mt-2">{step.title}</h3>
        <p className="text-xs text-gray-700 dark:text-gray-200 mt-1 whitespace-pre-wrap">{step.body}</p>
        <Footer
          idx={idx}
          last={last}
          onPrev={() => setIdx((i) => Math.max(0, i - 1))}
          onNext={() => last ? void finish('completed') : setIdx((i) => i + 1)}
        />
      </div>
    </div>
  )
}

function Header({ tutorialTitle, idx, total, onSkip }: { tutorialTitle: string; idx: number; total: number; onSkip: () => void }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="text-xs text-gray-500 dark:text-gray-400 inline-flex items-center gap-1">
        <MIcon name="school" size={14} />
        {tutorialTitle} · {idx + 1} / {total}
      </div>
      <button onClick={onSkip} className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-200">
        スキップ
      </button>
    </div>
  )
}

function Footer({ idx, last, onPrev, onNext }: { idx: number; last: boolean; onPrev: () => void; onNext: () => void }) {
  return (
    <div className="mt-3 flex items-center justify-between">
      <button
        onClick={onPrev}
        disabled={idx === 0}
        className="text-xs px-3 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 disabled:opacity-40"
      >
        前へ
      </button>
      <button
        onClick={onNext}
        className="text-xs px-3 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white inline-flex items-center gap-1"
      >
        {last ? '完了' : '次へ'}
        {last ? <MIcon name="check" size={12} /> : <MIcon name="play_arrow" size={12} />}
      </button>
    </div>
  )
}
