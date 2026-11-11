/**
 * match-registration-ux: 「暗定登録して作成」ボタンの意味が画面から分からない問題への対応。
 * 未発見の名前を入力して暗定登録 CTA が出たとき、その直下に短い説明文を表示することを検証する。
 */
import type React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PlayerCombobox } from '../PlayerCombobox'

function renderCombobox(overrides: Partial<React.ComponentProps<typeof PlayerCombobox>> = {}) {
  const props = {
    label: '対象選手',
    required: true,
    value: '' as number | '',
    query: '山田',
    setQuery: vi.fn(),
    setValue: vi.fn(),
    candidates: [],
    isLight: true,
    textSecondary: 'text-gray-500',
    canCreate: true,
    ...overrides,
  }
  return render(<PlayerCombobox {...props} />)
}

describe('PlayerCombobox tentative-registration hint', () => {
  it('shows a short explanation under the tentative-registration button when the player can create', () => {
    renderCombobox()
    // ドロップダウンを開く (query が 1 文字以上で input focus)
    fireEvent.focus(screen.getByPlaceholderText('名前を入力して検索...'))
    // 暗定登録 CTA が出ている
    expect(screen.getByText(/暗定登録して作成/)).toBeInTheDocument()
    // その直下の説明文が表示されている
    expect(
      screen.getByText(/選手情報を補えます/),
    ).toBeInTheDocument()
  })

  it('does not show the hint when the player cannot create (no tentative CTA)', () => {
    renderCombobox({ canCreate: false })
    fireEvent.focus(screen.getByPlaceholderText('名前を入力して検索...'))
    expect(screen.queryByText(/選手情報を補えます/)).not.toBeInTheDocument()
  })
})
