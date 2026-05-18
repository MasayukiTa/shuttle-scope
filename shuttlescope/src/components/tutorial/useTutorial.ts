/**
 * チュートリアル管理 hook + state API。
 *
 * - `useAutoTutorial(id)`: pageに mount したら、その tutorial を未完なら自動起動
 * - `openTutorial(id)`: 任意のタイミングで起動 (Settings > replay 等)
 * - `useTutorialState()`: 自分の全 tutorial 進行状態を取得
 */
import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from '@/api/client'

export interface TutorialStateEntry {
  tutorial_id: string
  status: 'in_progress' | 'completed' | 'skipped'
  last_step: number
  started_at: string | null
  completed_at: string | null
  replay_count: number
}

// グローバルな「いま開く tutorial」シグナル (App ルートで監視)
type Listener = (id: string | null) => void
const _listeners = new Set<Listener>()
let _current: string | null = null

export function openTutorial(id: string): void {
  _current = id
  _listeners.forEach((l) => l(id))
}

export function closeTutorial(): void {
  _current = null
  _listeners.forEach((l) => l(null))
}

export function useTutorialChannel(): string | null {
  const [v, setV] = useState<string | null>(_current)
  useEffect(() => {
    const l: Listener = (x) => setV(x)
    _listeners.add(l)
    return () => { _listeners.delete(l) }
  }, [])
  return v
}

export function useTutorialState(): { state: TutorialStateEntry[]; refresh: () => Promise<void>; loading: boolean } {
  const [state, setState] = useState<TutorialStateEntry[]>([])
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const r = await apiGet<{ data: TutorialStateEntry[] }>('/tutorials/state')
      setState(r.data || [])
    } catch {
      setState([])
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  return { state, refresh, loading }
}

export async function replayTutorial(id: string): Promise<void> {
  try { await apiPost(`/tutorials/${id}/replay`, {}) } catch { /* ignore */ }
  openTutorial(id)
}

/**
 * page に入ったら、その tutorial が未完なら自動起動。
 * 既に completed / skipped の場合は何もしない。
 */
export function useAutoTutorial(id: string): void {
  useEffect(() => {
    let cancelled = false
    apiGet<{ data: TutorialStateEntry[] }>('/tutorials/state')
      .then((r) => {
        if (cancelled) return
        const rec = (r.data || []).find((t) => t.tutorial_id === id)
        if (!rec || rec.status === 'in_progress') {
          openTutorial(id)
        }
      })
      .catch(() => { /* 失敗時は黙って何もしない */ })
    return () => { cancelled = true }
  }, [id])
}
