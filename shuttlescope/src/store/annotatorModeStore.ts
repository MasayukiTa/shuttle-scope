/**
 * U2: AnnotatorPage の mode (入力 / 確認 / 解析 / 設定) を管理する store.
 *
 * デフォルト = 'input' (addendum §4 確定事項)
 * last-used は永続化しない (open 時に常に input)
 */
import { create } from 'zustand'

export type AnnotatorMode = 'input' | 'review' | 'analysis' | 'settings'

/** UX-R1: 入力モード右パネルを inputStep に連動して 1 コンポーネントだけ表示するか。 */
export type StepFocusMode = 'step' | 'all'

interface AnnotatorModeState {
  mode: AnnotatorMode
  setMode: (m: AnnotatorMode) => void
  stepFocusMode: StepFocusMode
  setStepFocusMode: (s: StepFocusMode) => void
}

const STEP_FOCUS_KEY = 'ss_annotator_step_focus'

function loadStepFocus(): StepFocusMode {
  if (typeof window === 'undefined') return 'step'
  try {
    const v = window.localStorage.getItem(STEP_FOCUS_KEY)
    if (v === 'step' || v === 'all') return v
  } catch { /* noop */ }
  return 'step'
}

export const useAnnotatorModeStore = create<AnnotatorModeState>((set) => ({
  mode: 'input',
  setMode: (mode) => set({ mode }),
  stepFocusMode: loadStepFocus(),
  setStepFocusMode: (stepFocusMode) => {
    if (typeof window !== 'undefined') {
      try { window.localStorage.setItem(STEP_FOCUS_KEY, stepFocusMode) } catch { /* noop */ }
    }
    set({ stepFocusMode })
  },
}))
