/**
 * CVCandidateBadge コンポーネントテスト
 *
 * カバー範囲:
 * - auto_filled / suggested / review_required 各バッジのラベルテキスト
 * - compact モード（サイズのみ変化、テキストは同じ）
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CVCandidateBadge } from '../CVCandidateBadge'

describe('CVCandidateBadge', () => {
  it('auto_filled → 「自動入力」を表示する', () => {
    render(<CVCandidateBadge mode="auto_filled" />)
    expect(screen.getByText('自動入力')).toBeInTheDocument()
  })

  it('suggested → 「候補」を表示する', () => {
    render(<CVCandidateBadge mode="suggested" />)
    expect(screen.getByText('候補')).toBeInTheDocument()
  })

  it('review_required → 「要確認」を表示する', () => {
    render(<CVCandidateBadge mode="review_required" />)
    expect(screen.getByText('要確認')).toBeInTheDocument()
  })

  it('compact モードでも同じラベルテキストを表示する', () => {
    render(<CVCandidateBadge mode="auto_filled" compact />)
    expect(screen.getByText('自動入力')).toBeInTheDocument()
  })

  it('compact=false でテキストが text-[10px] クラスを持つ', () => {
    const { container } = render(<CVCandidateBadge mode="suggested" compact={false} />)
    const span = container.querySelector('span')
    expect(span?.className).toContain('text-[10px]')
  })

  it('compact=true でテキストが text-[9px] クラスを持つ', () => {
    const { container } = render(<CVCandidateBadge mode="suggested" compact />)
    const span = container.querySelector('span')
    expect(span?.className).toContain('text-[9px]')
  })
})
