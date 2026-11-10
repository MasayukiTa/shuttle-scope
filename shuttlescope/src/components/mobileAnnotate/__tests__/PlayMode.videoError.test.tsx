/**
 * モバイル再生: video の内部 MediaError / networkState / readyState を
 * そのまま画面に出さず、利用者向けメッセージを表示する (項目513)。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ja from '@/i18n/ja.json'

vi.mock('@/hooks/useHapticFeedback', () => ({ useHapticFeedback: () => ({ tap: () => {}, impact: () => {} }) }))
vi.mock('@/api/client', () => ({ apiGet: vi.fn().mockResolvedValue({ success: true, data: [] }) }))
vi.mock('@/components/mobileAnnotate/MobileCVOverlay', () => ({ MobileCVOverlay: () => null }))

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

import { PlayMode } from '../PlayMode'

const expected = (ja as unknown as { auto: { PlayMode: Record<string, string> } }).auto.PlayMode.playback_failed

function renderPlayMode() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PlayMode matchId={1} videoSrc="http://example.test/v.mp4" onTapVideo={() => {}} />
    </QueryClientProvider>,
  )
}

describe('PlayMode video error message (項目513)', () => {
  it('shows a user-facing message, not internal MediaError / net / ready state', () => {
    const { container } = renderPlayMode()
    const video = container.querySelector('video') as HTMLVideoElement
    fireEvent.error(video)
    expect(screen.getByText(expected)).toBeTruthy()
    expect(container.textContent).not.toContain('net=')
    expect(container.textContent).not.toContain('ready=')
    expect(container.textContent).not.toContain('MEDIA_ERR')
  })
})
