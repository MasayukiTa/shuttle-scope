/**
 * demo モード store。
 *
 * チュートリアル中に「デモデータ（編集不可）」を read-only 表示するための
 * グローバル状態。active の間、API クライアントは GET に `?demo=1` を付与し、
 * バックエンドは検証済み demo データのみを返す（実データは漏れない）。
 *
 * 設計: private_docs/TUTORIAL_REVAMP_2026-05-21.md
 */
import { create } from 'zustand'
import { setDemoMode } from '@/api/client'

export interface DemoTarget {
  team_id: number
  player_id: number
  player_name: string
  match_id: number | null
}

interface DemoModeState {
  active: boolean
  target: DemoTarget | null
  /** demo モードを有効化（API GET に demo=1 を付与開始） */
  enable: (target: DemoTarget | null) => void
  /** demo モードを解除（実データ表示に戻す） */
  disable: () => void
}

export const useDemoModeStore = create<DemoModeState>((set) => ({
  active: false,
  target: null,
  enable: (target) => {
    setDemoMode(true)
    set({ active: true, target })
  },
  disable: () => {
    setDemoMode(false)
    set({ active: false, target: null })
  },
}))
