import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { UnownedRallyBanner } from '../UnownedRallyBanner'

describe('UnownedRallyBanner (S-14)', () => {
  it('件数 0 なら出さない', () => {
    const { container } = render(
      <UnownedRallyBanner count={0} userKnown onClaim={vi.fn()} onDiscard={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('閉じるボタンが無く、ユーザー不明の間は送信できない', () => {
    const onClaim = vi.fn()
    const onDiscard = vi.fn()
    render(<UnownedRallyBanner count={2} userKnown={false} onClaim={onClaim} onDiscard={onDiscard} />)

    expect(screen.getByRole('alert')).toHaveTextContent('2')
    expect(screen.getAllByRole('button')).toHaveLength(2)
    const claim = screen.getByRole('button', { name: '自分のものとして送信' })
    expect(claim).toBeDisabled()
    fireEvent.click(claim)
    expect(onClaim).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '破棄' }))
    expect(onDiscard).toHaveBeenCalledTimes(1)
  })

  it('ユーザーが分かれば送信を選べる', () => {
    const onClaim = vi.fn()
    render(<UnownedRallyBanner count={1} userKnown onClaim={onClaim} onDiscard={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '自分のものとして送信' }))
    expect(onClaim).toHaveBeenCalledTimes(1)
  })
})
