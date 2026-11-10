/**
 * #695: provider/SSE 生成失敗時に「再試行」導線 (retryPrompt) が出ることを検証する。
 * 会話作成失敗だけでなく、ストリーム中/直後の error でも再試行ボタンが表示される。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import i18n from '@/i18n'

// streamMessage は呼び出しごとに制御する (最初の呼びで error、2 回目で成功)。
const streamMessageMock = vi.fn()

vi.mock('@/api/llm', () => ({
  createConversation: vi.fn().mockResolvedValue({ id: 1, title: 'c', created_at: '', updated_at: '' }),
  deleteConversation: vi.fn().mockResolvedValue(undefined),
  getLlmConfig: vi.fn().mockResolvedValue({ configured: true }),
  getLlmModels: vi.fn().mockResolvedValue({ models: [] }),
  getMessages: vi.fn().mockResolvedValue([]),
  listConversations: vi.fn().mockResolvedValue([]),
  renameConversation: vi.fn().mockResolvedValue(undefined),
  // 安定コード以外はそのまま文言化されるので null を返す (従来どおり)。
  llmStreamErrorKey: vi.fn().mockReturnValue(null),
  streamMessage: (...args: unknown[]) => streamMessageMock(...args),
}))

import LlmChatPage from '../LlmChatPage'

function typeAndSend(text: string) {
  const ta = screen.getByPlaceholderText(i18n.t('llm.placeholder')) as HTMLTextAreaElement
  fireEvent.change(ta, { target: { value: text } })
  fireEvent.keyDown(ta, { key: 'Enter' })
}

describe('LlmChatPage retry on provider/SSE failure (#695)', () => {
  beforeEach(() => {
    streamMessageMock.mockReset()
  })

  it('shows a retry button when the stream reports an error', async () => {
    // onEvent(error) を発火させる。
    streamMessageMock.mockImplementationOnce(async (_conv, _content, onEvent) => {
      onEvent({ type: 'error', message: 'boom' })
    })

    render(<LlmChatPage />)
    typeAndSend('hello')

    // エラーバナー + 再試行ボタンが出る。
    const retryLabel = i18n.t('llm.retry')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: new RegExp(retryLabel) })).toBeTruthy()
    })
  })

  it('retries the failed prompt when the retry button is clicked', async () => {
    streamMessageMock
      .mockImplementationOnce(async (_conv, _content, onEvent) => {
        onEvent({ type: 'error', message: 'boom' })
      })
      .mockImplementationOnce(async (_conv, _content, onEvent) => {
        onEvent({ type: 'start' })
        onEvent({ type: 'delta', content: 'ok' })
        onEvent({ type: 'done' })
      })

    render(<LlmChatPage />)
    typeAndSend('hello')

    const retryLabel = i18n.t('llm.retry')
    const btn = await screen.findByRole('button', { name: new RegExp(retryLabel) })
    fireEvent.click(btn)

    // 2 回目の streamMessage が同じ内容で呼ばれる。
    await waitFor(() => {
      expect(streamMessageMock).toHaveBeenCalledTimes(2)
    })
    const secondCall = streamMessageMock.mock.calls[1]
    expect(secondCall[1]).toBe('hello')
  })
})
