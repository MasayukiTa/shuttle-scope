import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { StreamingDownloadPanel } from '../StreamingDownloadPanel'
import * as apiClient from '@/api/client'

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

const defaultProps = {
  url: 'https://www.youtube.com/watch?v=test123',
  matchId: '42',
  siteName: 'YouTube',
  onDownloadComplete: vi.fn(),
}

function mockCapabilities(ffmpeg = true) {
  vi.mocked(apiClient.apiGet).mockImplementation((path: string) => {
    if (path === '/system/capabilities') {
      return Promise.resolve({ success: true, data: { yt_dlp: true, ffmpeg } })
    }
    return Promise.reject(new Error(`unexpected GET ${path}`))
  })
}

describe('StreamingDownloadPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCapabilities(true)
  })

  it('idle state renders source and download button', async () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    expect(screen.getByText('YouTube')).toBeInTheDocument()
    expect(screen.getByText(defaultProps.url)).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /ダウンロードして再生/ })).toBeInTheDocument()
    })
  })

  it('shows quality select with 720p as default', async () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByDisplayValue('720p（推奨）')).toBeInTheDocument()
    })
  })

  it('allows changing the quality', async () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    const select = await screen.findByDisplayValue('720p（推奨）')
    fireEvent.change(select, { target: { value: '1080' } })

    expect(screen.getByDisplayValue('1080p')).toBeInTheDocument()
  })

  it('shows a cookie browser hint after selecting a browser', async () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    const cookieSelects = await screen.findAllByRole('combobox')
    fireEvent.change(cookieSelects[1], { target: { value: 'chrome' } })

    await waitFor(() => {
      expect(screen.getByText(/Cookieをディスクから直接読み取ります/)).toBeInTheDocument()
    })
  })

  it('posts to the download endpoint when the button is clicked', async () => {
    vi.mocked(apiClient.apiGet).mockImplementation((path: string) => {
      if (path === '/system/capabilities') {
        return Promise.resolve({ success: true, data: { yt_dlp: true, ffmpeg: true } })
      }
      return Promise.resolve({
        success: true,
        data: { status: 'complete', filepath: 'localfile:///test.mp4' },
      })
    })
    vi.mocked(apiClient.apiPost).mockResolvedValueOnce({ success: true, data: { job_id: 'job-abc' } })

    render(<StreamingDownloadPanel {...defaultProps} />)
    fireEvent.click(await screen.findByRole('button', { name: /ダウンロードして再生/ }))

    await waitFor(() => {
      expect(apiClient.apiPost).toHaveBeenCalledWith(
        '/matches/42/download',
        expect.objectContaining({ quality: '720' })
      )
    })
  })

  it('shows an error message and retry link when the API fails', async () => {
    vi.mocked(apiClient.apiPost).mockRejectedValueOnce(new Error('ネットワークエラー'))

    render(<StreamingDownloadPanel {...defaultProps} />)
    fireEvent.click(await screen.findByRole('button', { name: /ダウンロードして再生/ }))

    await waitFor(() => {
      expect(screen.getByText('ネットワークエラー')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /やり直す/ })).toBeInTheDocument()
    })
  })

  it('returns to idle state after retry', async () => {
    vi.mocked(apiClient.apiPost).mockRejectedValueOnce(new Error('エラー'))

    render(<StreamingDownloadPanel {...defaultProps} />)
    fireEvent.click(await screen.findByRole('button', { name: /ダウンロードして再生/ }))
    fireEvent.click(await screen.findByRole('button', { name: /やり直す/ }))

    expect(screen.getByRole('button', { name: /ダウンロードして再生/ })).toBeInTheDocument()
  })

  it('renders all quality options', async () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByText('360p')).toBeInTheDocument()
      expect(screen.getByText('480p')).toBeInTheDocument()
      expect(screen.getByText('720p（推奨）')).toBeInTheDocument()
      expect(screen.getByText('1080p')).toBeInTheDocument()
      expect(screen.getByText('最高画質')).toBeInTheDocument()
    })
  })

  it('shows a warning banner when ffmpeg is unavailable', async () => {
    mockCapabilities(false)
    render(<StreamingDownloadPanel {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByText(/ffmpegが未インストール/)).toBeInTheDocument()
    })
  })

  it('marks the download button as low-quality mode when ffmpeg is unavailable', async () => {
    mockCapabilities(false)
    render(<StreamingDownloadPanel {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByText(/低画質モード/)).toBeInTheDocument()
    })
  })

  it('does not show the ffmpeg warning when ffmpeg is available', async () => {
    mockCapabilities(true)
    render(<StreamingDownloadPanel {...defaultProps} />)

    await waitFor(() => {
      expect(screen.queryByText(/ffmpegが未インストール/)).not.toBeInTheDocument()
    })
  })
})
