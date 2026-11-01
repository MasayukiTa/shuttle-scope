/**
 * #602: 通常 Ray の起動/停止が失敗したとき、ボタンが元に戻るだけで
 * 管理者に理由が見えない問題の回帰テスト。start が reject したら
 * cluster.ray_op_error の alert を出すことを検証する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: (...a: unknown[]) => apiPost(...a),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'ja' } }),
}))
vi.mock('@/hooks/useIsLightMode', () => ({ useIsLightMode: () => false }))
vi.mock('@/hooks/useCardTheme', () => ({ useCardTheme: () => ({}) }))
vi.mock('@/components/common/MIcon', () => ({ MIcon: () => null }))
vi.mock('@/components/common/QueryErrorNotice', () => ({ QueryErrorNotice: () => null }))

import { ClusterSettingsPanel } from '../ClusterSettingsPanel'

const CONFIG = {
  mode: 'single',
  network: { workers: [] },
  ray: {},
  load_limits: {},
  resources: {},
  task_routing: {},
}
const STATUS = {
  mode: 'single',
  node_id: 'n1',
  load: {
    cpu_percent: 10, gpu_percent: 0, active_tasks: 0, max_concurrent_inference: 2,
    cpu_limit: 90, gpu_limit: 90, cpu_ok: true, gpu_ok: true, slots_ok: true,
  },
  ray: { status: 'off', nodes: [] },
}

function mockGet(path: string) {
  if (path === '/cluster/config') return Promise.resolve(CONFIG)
  if (path === '/cluster/interfaces') return Promise.resolve([])
  if (path === '/cluster/hardware') return Promise.resolve({ system_ram_gb: 16, vram_total_gb: 8 })
  if (path === '/cluster/status') return Promise.resolve(STATUS)
  return Promise.resolve({})
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ClusterSettingsPanel />
    </QueryClientProvider>,
  )
}

describe('ClusterSettingsPanel #602 ray op error', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockImplementation((p: string) => mockGet(p))
  })

  it('ray/start が失敗したら cluster.ray_op_error の alert を出す', async () => {
    apiPost.mockImplementation((p: string) => {
      if (p === '/cluster/ray/start') return Promise.reject(new Error('boom'))
      return Promise.resolve({ ok: true })
    })
    renderPanel()
    const startButtons = await screen.findAllByText('cluster.ray_start')
    fireEvent.click(startButtons[0])
    await waitFor(() => {
      const alert = screen.getByRole('alert')
      expect(alert.textContent).toContain('cluster.ray_op_error')
    })
  })
})
