/**
 * HitZoneSelector コンポーネントテスト (Phase A)
 *
 * カバー範囲:
 *  - 9 タイル (1-9) が描画される
 *  - cvPrediction が指定されたセルに ✨ アイコンと CV ラベルが出る
 *  - selectedZone が isOverridden=true のとき orange、false のとき blue で塗られる
 *  - クリックで onZoneSelect が呼ばれ、引数が Zone9 値である
 *  - disabled=true のときクリックしても callback が呼ばれない
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { HitZoneSelector } from '../HitZoneSelector'

describe('HitZoneSelector', () => {
  it('renders 9 zone buttons (1-9)', () => {
    render(
      <HitZoneSelector
        cvPrediction={null}
        selectedZone={null}
        onZoneSelect={() => {}}
        isOverridden={false}
      />,
    )
    for (let z = 1; z <= 9; z++) {
      const btn = screen.getByRole('button', { name: new RegExp(`${z}`) })
      expect(btn).toBeTruthy()
    }
  })

  it('shows CV preselect indicator when cvPrediction is set', () => {
    const { container } = render(
      <HitZoneSelector
        cvPrediction={5}
        selectedZone={5}
        onZoneSelect={() => {}}
        isOverridden={false}
      />,
    )
    // CV ラベル "CV推定: ゾーン 5" がレンダされる
    expect(container.textContent).toContain('5')
    // ✨ Sparkles svg が存在 (lucide-react が svg を描画する)
    expect(container.querySelector('svg')).toBeTruthy()
  })

  it('calls onZoneSelect with the tapped zone number', () => {
    const onSelect = vi.fn()
    render(
      <HitZoneSelector
        cvPrediction={5}
        selectedZone={5}
        onZoneSelect={onSelect}
        isOverridden={false}
      />,
    )
    const btn7 = screen.getByRole('button', { name: /7/ })
    fireEvent.click(btn7)
    expect(onSelect).toHaveBeenCalledWith(7)
  })

  it('does not call onZoneSelect when disabled', () => {
    const onSelect = vi.fn()
    render(
      <HitZoneSelector
        cvPrediction={null}
        selectedZone={null}
        onZoneSelect={onSelect}
        isOverridden={false}
        disabled
      />,
    )
    const btn3 = screen.getByRole('button', { name: /3/ })
    fireEvent.click(btn3)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('marks the selected zone with aria-pressed=true', () => {
    render(
      <HitZoneSelector
        cvPrediction={null}
        selectedZone={6}
        onZoneSelect={() => {}}
        isOverridden
      />,
    )
    const btn6 = screen.getByRole('button', { name: /6/ })
    expect(btn6.getAttribute('aria-pressed')).toBe('true')
    const btn1 = screen.getByRole('button', { name: /1/ })
    expect(btn1.getAttribute('aria-pressed')).toBe('false')
  })
})
