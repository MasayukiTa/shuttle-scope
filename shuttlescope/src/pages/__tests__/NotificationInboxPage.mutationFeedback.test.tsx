/**
 * 通知 Inbox: mutation 失敗を握りつぶさない (#486) / status 連打で状態逆転させない (#487)
 *
 * #486 期間指定削除は API 成功を待ってからモーダルを閉じ、失敗時は入力条件を残して
 *      明示的なエラーを出す (以前は mutate 直後に setDateModalOpen(false) で閉じていた)。
 * #487 詳細のステータス 3 ボタンは updateMutation.isPending 中は disable し、
 *      応答が逆順に返って最終状態が逆転するのを防ぐ。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: 'admin' }) }))
vi.mock('@/hooks/useIsLightMode', () => ({ useIsLightMode: () => false }))

const publicInquiryList = vi.fn()
const publicInquiryUpdate = vi.fn()
const publicInquiryDelete = vi.fn()
const publicInquiryBulkDelete = vi.fn()
vi.mock('@/api/client', () => ({
  publicInquiryList: (...a: unknown[]) => publicInquiryList(...a),
  publicInquiryUpdate: (...a: unknown[]) => publicInquiryUpdate(...a),
  publicInquiryDelete: (...a: unknown[]) => publicInquiryDelete(...a),
  publicInquiryBulkDelete: (...a: unknown[]) => publicInquiryBulkDelete(...a),
}))

import { NotificationInboxPage } from '../NotificationInboxPage'

const row = {
  id: 1,
  name: '山田太郎',
  organization: null,
  role: null,
  contact_reference: null,
  message: 'テスト本文',
  status: 'new' as const,
  admin_note: null,
  created_at: '2026-01-01T00:00:00Z',
  pending_user_id: null,
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <NotificationInboxPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('NotificationInboxPage mutation feedback (#486/#487)', () => {
  beforeEach(() => {
    publicInquiryList.mockReset()
    publicInquiryUpdate.mockReset()
    publicInquiryDelete.mockReset()
    publicInquiryBulkDelete.mockReset()
    publicInquiryList.mockResolvedValue({ data: [row] })
    vi.spyOn(window, 'alert').mockImplementation(() => {})
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  // #486: 期間指定削除が失敗したらモーダルを閉じず、入力条件を残してエラーを出す
  it('keeps the date-range modal open and alerts on bulk delete failure', async () => {
    publicInquiryBulkDelete.mockRejectedValue(new Error('500'))
    renderPage()

    // 管理メニュー -> 期間指定で削除 を開く
    fireEvent.click(await screen.findByText('管理メニュー'))
    fireEvent.click(await screen.findByText('期間指定で削除'))

    // モーダルが開いたことを確認し、開始日を入力
    const heading = await screen.findByText('期間指定削除')
    const dateInputs = document.querySelectorAll('input[type="date"]')
    expect(dateInputs.length).toBeGreaterThan(0)
    fireEvent.change(dateInputs[0], { target: { value: '2026-01-01' } })

    // 削除実行
    fireEvent.click(screen.getByText('削除実行'))

    await waitFor(() => expect(publicInquiryBulkDelete).toHaveBeenCalledTimes(1))
    // 失敗後: エラー alert が出て、モーダルは閉じず、入力条件が残る
    await waitFor(() =>
      expect(window.alert).toHaveBeenCalledWith('操作に失敗しました。時間をおいて再度お試しください。')
    )
    expect(heading).toBeInTheDocument()
    expect((document.querySelector('input[type="date"]') as HTMLInputElement).value).toBe('2026-01-01')
  })

  // #486: 成功時は成功を待ってからモーダルを閉じる
  it('closes the modal only after a successful bulk delete', async () => {
    publicInquiryBulkDelete.mockResolvedValue({ data: { deleted: 2, ids: [] } })
    renderPage()
    fireEvent.click(await screen.findByText('管理メニュー'))
    fireEvent.click(await screen.findByText('期間指定で削除'))
    await screen.findByText('期間指定削除')
    const dateInputs = document.querySelectorAll('input[type="date"]')
    fireEvent.change(dateInputs[0], { target: { value: '2026-01-01' } })
    fireEvent.click(screen.getByText('削除実行'))
    await waitFor(() => expect(publicInquiryBulkDelete).toHaveBeenCalledTimes(1))
    // 成功後はモーダルが閉じる
    await waitFor(() => expect(screen.queryByText('期間指定削除')).not.toBeInTheDocument())
  })

  // #487: 更新中はステータス 3 ボタンを disable する
  it('disables the status buttons while an update is in flight', async () => {
    // 解決しない Promise で isPending を維持
    publicInquiryUpdate.mockReturnValue(new Promise(() => {}))
    renderPage()

    // 通知を選択（一覧の名前をクリック）
    const nameNodes = await screen.findAllByText('山田太郎')
    fireEvent.click(nameNodes[0])

    // 詳細のステータスボタン「確認中」を押す
    const reviewBtn = await screen.findByRole('button', { name: '確認中' })
    fireEvent.click(reviewBtn)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '新着' })).toBeDisabled()
      expect(screen.getByRole('button', { name: '確認中' })).toBeDisabled()
      expect(screen.getByRole('button', { name: '対応済み' })).toBeDisabled()
    })
    expect(publicInquiryUpdate).toHaveBeenCalledTimes(1)
  })
})
