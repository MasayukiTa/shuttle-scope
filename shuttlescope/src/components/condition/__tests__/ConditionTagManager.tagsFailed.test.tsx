/**
 * 期間タグ一覧の取得失敗を「タグなし」と区別し、追加も止める。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: 'coach', hasRole: (a: string[]) => a.includes('coach') }),
}))

const refetch = vi.fn()
let tagsState: Record<string, unknown> = {}
vi.mock('@/hooks/useConditionTags', () => ({
  useConditionTags: () => tagsState,
  useCreateConditionTag: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteConditionTag: () => ({ mutate: vi.fn() }),
}))

import { ConditionTagManager } from '../ConditionTagManager'

describe('ConditionTagManager fetch failure', () => {
  it('shows a retryable error, not the empty text, and disables adding', () => {
    tagsState = { data: undefined, isLoading: false, isError: true, refetch }
    render(<ConditionTagManager playerId={1} />)
    expect(screen.getByRole('alert')).toBeTruthy()
    const buttons = screen.getAllByRole('button')
    const submit = buttons.find((b) => (b as HTMLButtonElement).type === 'submit') as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.click(buttons[buttons.length - 1])
    expect(refetch).toHaveBeenCalled()
  })

  it('shows no alert for a successful empty list', () => {
    tagsState = { data: [], isLoading: false, isError: false, refetch }
    render(<ConditionTagManager playerId={1} />)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
