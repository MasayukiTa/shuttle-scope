/**
 * AttributePanel コンポーネントテスト
 *
 * 仙台大要望「打球の高さ 4 段階（任意）」の UI 契約を固定する:
 *  - 4 つの高さボタン（ネットより上 / やや上 / やや下 / 下）が描画される
 *  - 未選択ボタンをクリックすると onChange に hit_height=index が載る
 *  - 選択中ボタンを再クリックすると hit_height=undefined（解除）になる
 *  - 選択中ボタンは aria-checked=true
 *  - disabled のときはクリックしても onChange が呼ばれない
 *  - 既存属性（BH / AH / above_net）を壊していない
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { AttributePanel } from '../AttributePanel'
import type { StrokeAttributes } from '@/types'

const baseAttrs: StrokeAttributes = {
  is_backhand: false,
  is_around_head: false,
  above_net: undefined,
  hit_height: undefined,
}

describe('AttributePanel 打球の高さ (hit_height)', () => {
  it('4 つの高さボタンを描画する', () => {
    render(<AttributePanel attributes={baseAttrs} onChange={() => {}} />)
    expect(screen.getByTestId('hit-height-0')).toBeTruthy()
    expect(screen.getByTestId('hit-height-1')).toBeTruthy()
    expect(screen.getByTestId('hit-height-2')).toBeTruthy()
    expect(screen.getByTestId('hit-height-3')).toBeTruthy()
  })

  it('日本語ラベル（ネットより上 / ネットよりやや上 / ネットよりやや下 / ネットより下）を表示する', () => {
    render(<AttributePanel attributes={baseAttrs} onChange={() => {}} />)
    expect(screen.getByTestId('hit-height-0').textContent).toBe('ネットより上')
    expect(screen.getByTestId('hit-height-1').textContent).toBe('ネットよりやや上')
    expect(screen.getByTestId('hit-height-2').textContent).toBe('ネットよりやや下')
    expect(screen.getByTestId('hit-height-3').textContent).toBe('ネットより下')
  })

  it('未選択ボタンのクリックで onChange に hit_height=index を載せる', () => {
    const onChange = vi.fn()
    render(<AttributePanel attributes={baseAttrs} onChange={onChange} />)
    fireEvent.click(screen.getByTestId('hit-height-2'))
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ hit_height: 2 }),
    )
  })

  it('選択中ボタンの再クリックで hit_height=undefined（解除）を載せる', () => {
    const onChange = vi.fn()
    render(
      <AttributePanel
        attributes={{ ...baseAttrs, hit_height: 1 }}
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByTestId('hit-height-1'))
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ hit_height: undefined }),
    )
  })

  it('選択中ボタンは aria-checked=true、他は false', () => {
    render(
      <AttributePanel
        attributes={{ ...baseAttrs, hit_height: 3 }}
        onChange={() => {}}
      />,
    )
    expect(screen.getByTestId('hit-height-3').getAttribute('aria-checked')).toBe('true')
    expect(screen.getByTestId('hit-height-0').getAttribute('aria-checked')).toBe('false')
  })

  it('disabled のときはクリックしても onChange を呼ばない', () => {
    const onChange = vi.fn()
    render(
      <AttributePanel attributes={baseAttrs} onChange={onChange} disabled />,
    )
    fireEvent.click(screen.getByTestId('hit-height-0'))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('高さ選択は既存属性（is_backhand / above_net）を保持したまま onChange する', () => {
    const onChange = vi.fn()
    render(
      <AttributePanel
        attributes={{ ...baseAttrs, is_backhand: true, above_net: true }}
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByTestId('hit-height-0'))
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        is_backhand: true,
        above_net: true,
        hit_height: 0,
      }),
    )
  })
})
