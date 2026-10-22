/**
 * はじめに: ロール別の案内文を、バックエンドの実際の権限に合わせる
 *
 * - 選手の新規登録: analyst / admin のみ (POST /players は require_analyst)
 * - 試合の作成・編集: player 以外 (POST /matches, PUT /matches/{id} は player を 403)
 * そのため coach に「閲覧のみ」と案内してはならない。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { UserRole } from '@/types'
import ja from '@/i18n/ja.json'

let mockRole: UserRole | null = 'coach'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: mockRole }),
}))

import { GettingStartedPage } from '../GettingStartedPage'

const gs = (ja as unknown as { getting_started: Record<string, string> }).getting_started

function renderPage() {
  return render(
    <MemoryRouter>
      <GettingStartedPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockRole = 'coach'
})

describe('GettingStartedPage role note', () => {
  it('coach: 閲覧のみとは案内せず、自チームの試合を登録・編集できると案内する', () => {
    const { container } = renderPage()
    const text = container.textContent ?? ''
    expect(text).toContain(gs.role_note_coach)
    expect(text).not.toContain(gs.role_note)
    expect(text).not.toContain('閲覧のみ')
  })

  it('player: 登録できない旨の案内を出す', () => {
    mockRole = 'player'
    const { container } = renderPage()
    expect(container.textContent).toContain(gs.role_note)
  })

  it.each(['analyst', 'admin'] as UserRole[])('%s: 注意書きを出さない', (r) => {
    mockRole = r
    const { container } = renderPage()
    const text = container.textContent ?? ''
    expect(text).not.toContain(gs.role_note)
    expect(text).not.toContain(gs.role_note_coach)
  })
})
