/**
 * 承認待ち件数バッジ用フック: admin のみ取得し、失敗時は偽の 0 を出さない。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

// vi.fn の戻り値 Promise を vitest が追跡して未処理 rejection になるため、
// 呼び出しは素の配列に記録し、応答は handler で返す。
const calls: unknown[][] = []
let handler: () => Promise<unknown> = async () => ({ success: true, data: [] })
vi.mock('@/api/client', () => ({
  apiGet: async (...a: unknown[]) => {
    calls.push(a)
    return handler()
  },
}))

import { usePendingApprovalCount } from '../usePendingApprovalCount'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const rows = (n: number) => ({ success: true, data: Array.from({ length: n }, (_, i) => ({ id: i + 1 })) })
const settle = () => new Promise((r) => setTimeout(r, 50))

describe('usePendingApprovalCount', () => {
  beforeEach(() => {
    calls.length = 0
  })

  it('admin は件数を取得する', async () => {
    handler = async () => rows(3)
    const { result } = renderHook(() => usePendingApprovalCount('admin'), { wrapper })
    await waitFor(() => expect(result.current).toBe(3))
    expect(calls).toEqual([['/auth/users/pending']])
  })

  it.each(['coach', 'analyst', 'player', 'demo', 'llm', null, undefined])(
    '%s はリクエストを送らずバッジなし',
    async (role) => {
      handler = async () => rows(5)
      const { result } = renderHook(() => usePendingApprovalCount(role as string | null | undefined), { wrapper })
      await settle()
      expect(calls).toHaveLength(0)
      expect(result.current).toBeNull()
    },
  )

  it('件数 0 は 0 を返す (表示側で非表示)', async () => {
    handler = async () => rows(0)
    const { result } = renderHook(() => usePendingApprovalCount('admin'), { wrapper })
    await waitFor(() => expect(result.current).toBe(0))
  })

  it('リクエストエラーでは null (偽の 0 を出さない)', async () => {
    handler = async () => {
      throw Object.assign(new Error('boom'), { status: 500 })
    }
    const { result } = renderHook(() => usePendingApprovalCount('admin'), { wrapper })
    await waitFor(() => expect(calls.length).toBeGreaterThan(0))
    await settle()
    expect(result.current).toBeNull()
  })

  it('403 でも null', async () => {
    handler = async () => {
      throw Object.assign(new Error('forbidden'), { status: 403 })
    }
    const { result } = renderHook(() => usePendingApprovalCount('admin'), { wrapper })
    await waitFor(() => expect(calls.length).toBeGreaterThan(0))
    await settle()
    expect(result.current).toBeNull()
  })
})
