/**
 * #579: 会話履歴 (getMessages) の取得失敗を「空の会話 / 会話なし」へ変換しないことを検証する。
 * 取得に失敗したときは空会話UI (スターター質問) を出さず、明示的なエラー状態 + 再読込ボタンを
 * 表示する。再読込ボタンで再取得が走り、成功すると履歴が表示される。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import i18n from '@/i18n'

const getMessagesMock = vi.fn()

vi.mock('@/api/llm', () => ({
  createConversation: vi.fn().mockResolvedValue({ id: 1, title: 'c', created_at: '', last_used_at: '' }),
  deleteConversation: vi.fn().mockResolvedValue({ success: true }),
  getLlmConfig: vi.fn().mockResolvedValue({ configured: true, streaming: true, reasoning_available: false }),
  getLlmModels: vi.fn().mockResolvedValue({ models: [], default: '' }),
  getMessages: (...args: unknown[]) => getMessagesMock(...args),
  listConversations: vi.fn().mockResolvedValue({ conversations: [{ id: 1, title: 'Conversation 1' }] }),
  renameConversation: vi.fn().mockResolvedValue({ id: 1, title: 'c' }),
  llmStreamErrorKey: vi.fn().mockReturnValue(null),
  streamMessage: vi.fn().mockResolvedValue(undefined),
}))

import LlmChatPage from '../LlmChatPage'

function selectFirstConversation() {
  // 会話一覧の行 (title) をクリックして会話を開く。
  const row = screen.getAllByText('Conversation 1')[0]
  fireEvent.click(row)
}

describe('LlmChatPage message-history fetch failure (#579)', () => {
  beforeEach(() => {
    getMessagesMock.mockReset()
  })

  it('shows an error state with a retry button, not the empty-conversation UI, when history load fails', async () => {
    getMessagesMock.mockRejectedValueOnce(new Error('network error'))

    render(<LlmChatPage />)
    await waitFor(() => expect(screen.getAllByText('Conversation 1').length).toBeGreaterThan(0))
    selectFirstConversation()

    // 取得失敗の文言と再試行ボタンが出る。
    await waitFor(() => {
      expect(screen.getByText(i18n.t('common_ui.llm_messages_failed'))).toBeTruthy()
    })
    const retryLabel = i18n.t('common_ui.query_retry')
    expect(screen.getByRole('button', { name: new RegExp(retryLabel) })).toBeTruthy()

    // 空会話UI (スターター質問の見出し) は出ない。
    expect(screen.queryByText(i18n.t('llm.empty'))).toBeNull()
    expect(screen.queryByText(i18n.t('llm.starters_title'))).toBeNull()
  })

  it('retries fetching the history when the retry button is clicked', async () => {
    getMessagesMock
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce({ messages: [{ id: 10, seq: 1, role: 'assistant', content: 'recovered history' }] })

    render(<LlmChatPage />)
    await waitFor(() => expect(screen.getAllByText('Conversation 1').length).toBeGreaterThan(0))
    selectFirstConversation()

    const retryLabel = i18n.t('common_ui.query_retry')
    const btn = await screen.findByRole('button', { name: new RegExp(retryLabel) })
    fireEvent.click(btn)

    // 再取得が走り、履歴が表示され、エラー状態は消える。
    await waitFor(() => {
      expect(screen.getByText('recovered history')).toBeTruthy()
    })
    expect(screen.queryByText(i18n.t('common_ui.llm_messages_failed'))).toBeNull()
    expect(getMessagesMock).toHaveBeenCalledTimes(2)
  })
})
