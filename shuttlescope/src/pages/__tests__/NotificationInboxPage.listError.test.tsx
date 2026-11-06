/**
 * 監査 #704: 通知 Inbox 本体 (NotificationInboxPage) が一覧 API
 * (publicInquiryList / GET /public/inquiries) の取得失敗を「問い合わせ 0 件」の
 * 正常な空状態へ倒さず、明示的なエラー状態と再試行導線を出すことを検証する。
 *
 * isError のとき QueryErrorNotice (role="alert", common_ui.query_failed) を出し、
 * 空表示 (k4) を出さないこと。取得成功かつ 0 件のときは逆に
 * エラーを出さず k4 空表示になることを固定する。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ja from '@/i18n/ja.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  return typeof v === 'string' ? v : key
}
function interp(s: string, o?: Record<string, unknown>): string {
  return s.replace(/\{\{(\w+)\}\}/g, (_m, k) => String(o?.[k] ?? ''))
}

// react-i18next は ja.json を実引きする。QueryErrorNotice は実物を使い、
// 共通の失敗文言 (common_ui.query_failed) と role="alert" を見る。
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, o?: Record<string, unknown> | string) => {
      const hit = lookup(ja as Dict, key)
      if (hit !== key) return interp(hit, typeof o === 'object' ? o : undefined)
      if (typeof o === 'string') return o
      return key
    },
  }),
}))

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

const queryFailed = lookup(ja as Dict, 'common_ui.query_failed')
const emptyLabel = lookup(ja as Dict, 'auto.NotificationInboxPage.k4')

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

describe('NotificationInboxPage 一覧取得失敗 (監査 #704)', () => {
  beforeEach(() => {
    publicInquiryList.mockReset()
    vi.spyOn(window, 'alert').mockImplementation(() => {})
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })
  afterEach(() => {
    vi.restoreAllMocks()
    cleanup()
  })

  it('一覧 API が失敗したとき、明示エラーを出し「0 件」の空表示に倒さない', async () => {
    publicInquiryList.mockRejectedValue(new Error('500'))
    renderPage()
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(queryFailed)
    // 取得失敗時は「新しい通知はありません」を出さない
    expect(screen.queryByText(emptyLabel)).toBeNull()
  })

  it('取得成功かつ 0 件のときはエラーを出さず空表示を出す', async () => {
    publicInquiryList.mockResolvedValue({ success: true, data: [] })
    renderPage()
    expect(await screen.findByText(emptyLabel)).not.toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('取得成功かつデータありのときはエラーも空表示も出さない', async () => {
    publicInquiryList.mockResolvedValue({ success: true, data: [row] })
    renderPage()
    expect(await screen.findByText(row.name)).not.toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByText(emptyLabel)).toBeNull()
  })
})
