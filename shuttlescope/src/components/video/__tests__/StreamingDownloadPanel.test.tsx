/**
 * StreamingDownloadPanel コンポーネントテスト
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { StreamingDownloadPanel } from '../StreamingDownloadPanel'
import * as apiClient from '@/api/client'

// API クライアントをモック
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

describe('StreamingDownloadPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('idle 状態でサービス名・URL・ダウンロードボタンが表示される', () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    expect(screen.getByText('YouTube')).toBeInTheDocument()
    expect(screen.getByText(defaultProps.url)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ダウンロードして再生/ })).toBeInTheDocument()
  })

  it('画質セレクトが表示され720pがデフォルト', () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    const select = screen.getByDisplayValue('720p（推奨）')
    expect(select).toBeInTheDocument()
  })

  it('画質を変更できる', () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    const select = screen.getByDisplayValue('720p（推奨）')
    fireEvent.change(select, { target: { value: '1080' } })
    expect(screen.getByDisplayValue('1080p')).toBeInTheDocument()
  })

  it('Cookieブラウザを選択するとヒントが表示される', () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    // Cookie セレクトを探す（value="" のもの）
    const cookieSelects = screen.getAllByRole('combobox')
    const cookieSelect = cookieSelects[1] // 2番目が Cookie セレクト

    fireEvent.change(cookieSelect, { target: { value: 'chrome' } })

    // "Chrome" は <strong> 要素で別テキストノードになるため getByText でなく container 全文を確認
    expect(screen.getByText(/のCookieを使用します/)).toBeInTheDocument()
  })

  it('ダウンロードボタンをクリックすると POST /matches/42/download が呼ばれる', async () => {
    const mockPost = vi.mocked(apiClient.apiPost)
    mockPost.mockResolvedValueOnce({ success: true, data: { job_id: 'job-abc-123' } })

    // ステータスポーリングはすぐに "complete" を返す
    const mockGet = vi.mocked(apiClient.apiGet)
    mockGet.mockResolvedValue({
      success: true,
      data: { status: 'complete', filepath: 'localfile:///test.mp4' },
    })

    render(<StreamingDownloadPanel {...defaultProps} />)

    fireEvent.click(screen.getByRole('button', { name: /ダウンロードして再生/ }))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/matches/42/download',
        expect.objectContaining({ quality: '720' })
      )
    })
  })

  it('APIエラー時にエラーメッセージとやり直しボタンが表示される', async () => {
    vi.mocked(apiClient.apiPost).mockRejectedValueOnce(
      new Error('ネットワークエラー')
    )

    render(<StreamingDownloadPanel {...defaultProps} />)

    fireEvent.click(screen.getByRole('button', { name: /ダウンロードして再生/ }))

    await waitFor(() => {
      expect(screen.getByText('ネットワークエラー')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /やり直す/ })).toBeInTheDocument()
    })
  })

  it('やり直しボタンでidle状態にリセットされる', async () => {
    vi.mocked(apiClient.apiPost).mockRejectedValueOnce(new Error('エラー'))

    render(<StreamingDownloadPanel {...defaultProps} />)
    fireEvent.click(screen.getByRole('button', { name: /ダウンロードして再生/ }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /やり直す/ })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /やり直す/ }))

    expect(screen.getByRole('button', { name: /ダウンロードして再生/ })).toBeInTheDocument()
  })

  it('ダウンロード完了時に onDownloadComplete が呼ばれる', async () => {
    const onComplete = vi.fn()
    vi.mocked(apiClient.apiPost).mockResolvedValueOnce({
      success: true,
      data: { job_id: 'job-done' },
    })
    vi.mocked(apiClient.apiGet).mockResolvedValue({
      success: true,
      data: { status: 'complete', filepath: 'localfile:///video.mp4' },
    })

    render(<StreamingDownloadPanel {...defaultProps} onDownloadComplete={onComplete} />)
    fireEvent.click(screen.getByRole('button', { name: /ダウンロードして再生/ }))

    await waitFor(() => {
      expect(screen.getByText(/ダウンロード完了/)).toBeInTheDocument()
    }, { timeout: 5000 })

    // 800ms 遅延後に onDownloadComplete が呼ばれる
    await waitFor(() => {
      expect(onComplete).toHaveBeenCalled()
    }, { timeout: 2000 })
  })

  it('全ての画質オプションが表示される', () => {
    render(<StreamingDownloadPanel {...defaultProps} />)

    expect(screen.getByText('360p')).toBeInTheDocument()
    expect(screen.getByText('480p')).toBeInTheDocument()
    expect(screen.getByText('720p（推奨）')).toBeInTheDocument()
    expect(screen.getByText('1080p')).toBeInTheDocument()
    expect(screen.getByText('最高画質')).toBeInTheDocument()
  })
})
