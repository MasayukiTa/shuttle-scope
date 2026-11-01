/**
 * 今週の伸びしろ: サーバーが例示データ (meta.example) を返したとき、
 * 本番では作り物の数値・文面を出さない。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const exampleResponse = {
  items: [
    {
      id: 'growth_main',
      prose: 'FAKE_EXAMPLE_PROSE',
      evidence_path: '/x',
      confidence: 0.5,
      metric: { sample_n: 120 },
    },
  ],
  generator: 'template',
  generated_at: '2026-10-22T00:00:00Z',
  meta: { example: true },
}

vi.mock('@/api/client', () => ({
  API_BASE_URL: 'http://localhost',
  apiGet: vi.fn().mockImplementation(() => Promise.resolve(exampleResponse)),
}))

import { GrowthSnapshotCard } from '../GrowthSnapshotCard'

function renderCard(allowSample: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <GrowthSnapshotCard playerId={1} allowSample={allowSample} />
    </QueryClientProvider>,
  )
}

describe('GrowthSnapshotCard with example data', () => {
  it('hides the example prose and shows the not-available message when samples are not allowed', async () => {
    const { container } = renderCard(false)
    await waitFor(() => {
      expect(container.querySelector('.animate-pulse')).toBeNull()
    })
    expect(screen.queryByText('FAKE_EXAMPLE_PROSE')).toBeNull()
    // 本番で例示を隠すときは「データ不足」ではなく「準備中」を出す (#752)。
    expect(screen.getByText('この機能は準備中です。実データの提供を開始するまでお待ちください。')).toBeTruthy()
    expect(screen.queryByText('もう少しデータが集まると伸びしろが出せます')).toBeNull()
    expect(screen.queryByText('サンプルデータ')).toBeNull()
  })

  it('shows the example prose with the sample label when samples are allowed', async () => {
    renderCard(true)
    expect(await screen.findByText('FAKE_EXAMPLE_PROSE')).toBeTruthy()
    expect(screen.getByText('サンプルデータ')).toBeTruthy()
  })
})
