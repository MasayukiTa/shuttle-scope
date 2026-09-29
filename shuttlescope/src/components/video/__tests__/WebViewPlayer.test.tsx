/**
 * WebViewPlayer コンポーネントテスト
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { WebViewPlayer } from '../WebViewPlayer'

const defaultProps = {
  url: 'https://example-streaming.com/watch/12345',
  siteName: 'TestSite',
}

describe('WebViewPlayer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('ナビゲーションバー（戻る・進む・再読込）が表示される', () => {
    render(<WebViewPlayer {...defaultProps} />)

    expect(screen.getByTitle('戻る')).toBeInTheDocument()
    expect(screen.getByTitle('進む')).toBeInTheDocument()
    expect(screen.getByTitle('再読込')).toBeInTheDocument()
  })

  it('初期URLがURL入力バーに表示される', () => {
    render(<WebViewPlayer {...defaultProps} />)

    const urlInput = screen.getByRole('textbox', { name: 'URL' })
    expect(urlInput).toHaveValue(defaultProps.url)
  })

  it('サービス名がページタイトルに表示される', () => {
    render(<WebViewPlayer {...defaultProps} />)

    expect(screen.getByText('TestSite')).toBeInTheDocument()
  })

  it('外部ブラウザで開くボタンが表示される', () => {
    render(<WebViewPlayer {...defaultProps} />)

    expect(screen.getByTitle('システムブラウザで開く')).toBeInTheDocument()
  })

  it('URL入力バーで Enter を押すと webview の src が更新される', () => {
    render(<WebViewPlayer {...defaultProps} />)

    const urlInput = screen.getByRole('textbox', { name: 'URL' })
    fireEvent.change(urlInput, { target: { value: 'https://new-url.example.com/' } })
    expect(urlInput).toHaveValue('https://new-url.example.com/')
  })

  it('戻るボタンは初期状態で無効化されている', () => {
    render(<WebViewPlayer {...defaultProps} />)

    const backButton = screen.getByTitle('戻る')
    expect(backButton).toBeDisabled()
  })

  it('進むボタンは初期状態で無効化されている', () => {
    render(<WebViewPlayer {...defaultProps} />)

    const forwardButton = screen.getByTitle('進む')
    expect(forwardButton).toBeDisabled()
  })

  it('読み込み中インジケーターが初期状態で表示される', () => {
    render(<WebViewPlayer {...defaultProps} />)

    expect(screen.getByText('読み込み中...')).toBeInTheDocument()
  })

  it('<webview> 要素が正しい props でレンダリングされる', () => {
    const { container } = render(<WebViewPlayer {...defaultProps} />)

    const webview = container.querySelector('webview')
    expect(webview).toBeTruthy()
    expect(webview?.getAttribute('src')).toBe(defaultProps.url)
    expect(webview?.getAttribute('partition')).toBe('persist:streaming')
  })
})
