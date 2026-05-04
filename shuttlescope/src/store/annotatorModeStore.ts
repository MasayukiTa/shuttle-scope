/**
 * U2: AnnotatorPage の mode (入力 / 確認 / 解析 / 設定) を管理する store.
 *
 * デフォルト = 'input' (addendum §4 確定事項)
 * last-used は永続化しない (open 時に常に input)
 */
import { create } from 'zustand'

export type AnnotatorMode = 'input' | 'review' | 'analysis' | 'settings'

interface AnnotatorModeState {
  mode: AnnotatorMode
  setMode: (m: AnnotatorMode) => void
}

export const useAnnotatorModeStore = create<AnnotatorModeState>((set) => ({
  mode: 'input',
  setMode: (mode) => set({ mode }),
}))
