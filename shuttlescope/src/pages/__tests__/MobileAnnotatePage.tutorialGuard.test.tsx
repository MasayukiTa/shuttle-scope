import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const autoTutorial = vi.fn()
vi.mock('@/components/tutorial/useTutorial', () => ({
  useAutoTutorial: (id: string, enabled?: boolean) => autoTutorial(id, enabled),
}))
vi.mock('@/api/client', () => ({
  apiGet: vi.fn().mockResolvedValue({ data: [] }),
  apiPost: vi.fn().mockResolvedValue({}),
  apiPut: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue({}),
}))

vi.mock('@/utils/mobileAnnotateQueue', () => ({
  startBackgroundFlush: vi.fn(),
  getStatus: vi.fn().mockResolvedValue({ pending: 0, failed: 0, manual: 0 }),
  retryAllManual: vi.fn(),
  enqueue: vi.fn(),
}))
vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

import { MobileAnnotatePage } from '../MobileAnnotatePage'

function setViewport(w: number, h: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: w })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: h })
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/m/annotate/1']}>
        <Routes>
          <Route path="/m/annotate/:matchId" element={<MobileAnnotatePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const lastEnabled = () => {
  const calls = autoTutorial.mock.calls.filter((c) => c[0] === 'mobile_annotate_pass')
  return calls[calls.length - 1]?.[1]
}

describe('MobileAnnotatePage: 縦向きではツアーを自動起動しない (A-21)', () => {
  afterEach(() => { autoTutorial.mockClear(); setViewport(1024, 768) })

  it('縦向き=無効、横向きに回すと有効になる (再開)', async () => {
    setViewport(390, 844)
    mount()
    expect(lastEnabled()).toBe(false)
    await act(async () => {
      setViewport(844, 390)
      window.dispatchEvent(new Event('resize'))
    })
    expect(lastEnabled()).toBe(true)
  })

  it('最初から横向きなら有効', () => {
    setViewport(844, 390)
    mount()
    expect(lastEnabled()).toBe(true)
  })
})
