/**
 * ConfidenceBadge コンポーネントテスト
 *
 * D-5: 単位 (unit) を宣言しない呼び出しに対して★を出さないこと。
 * 以前は既定値 `'strokes'` があり、試合数を渡した画面でも打球数の閾値
 * (500/2000) で★が付き、ツールチップは「球」と表示していた。
 * ★は「どれだけ信頼できるか」の主張なので、単位が分からない状態で
 * 出すのは根拠のない確信の表示にあたる。
 *
 * カバー範囲:
 * - unit 未指定 → ★が1つも無い / 標本数は出る
 * - unit 指定 → 単位ごとの閾値で★が付く
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ConfidenceBadge } from '../ConfidenceBadge'

/** MIcon は `star` / `star_border` を文字列として描画する (Material Symbols)。 */
function filledStars(container: HTMLElement): number {
  return Array.from(container.querySelectorAll('*')).filter(
    (el) => el.children.length === 0 && el.textContent === 'star',
  ).length
}

describe('ConfidenceBadge', () => {
  it('unit 未指定なら★を1つも出さない', () => {
    const { container } = render(<ConfidenceBadge sampleSize={12} />)
    expect(filledStars(container)).toBe(0)
    expect(container.textContent).not.toContain('star_border')
  })

  it('unit 未指定でも標本数は出す', () => {
    render(<ConfidenceBadge sampleSize={1234} />)
    expect(screen.getByText('1,234')).toBeInTheDocument()
  })

  it('unit 未指定なら単位の語を書かない', () => {
    const { container } = render(<ConfidenceBadge sampleSize={12} />)
    // 「球」「ラリー」「試合」はどれも単位が決まって初めて言えるもの
    expect(container.textContent).not.toMatch(/球|ラリー|試合/)
    expect(container.querySelector('[title]')?.getAttribute('title')).not.toMatch(/球|ラリー|試合/)
  })

  it('unit 未指定は compact でも数字が残る (★が無いので空になってしまうため)', () => {
    render(<ConfidenceBadge sampleSize={7} compact />)
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('unit=matches なら試合数の閾値 (10/30) で★が付く', () => {
    const { container: low } = render(<ConfidenceBadge sampleSize={5} unit="matches" />)
    expect(filledStars(low)).toBe(1)
    const { container: mid } = render(<ConfidenceBadge sampleSize={12} unit="matches" />)
    expect(filledStars(mid)).toBe(2)
    const { container: high } = render(<ConfidenceBadge sampleSize={40} unit="matches" />)
    expect(filledStars(high)).toBe(3)
  })

  it('同じ 12 でも単位が違えば★の数が違う', () => {
    const { container: asMatches } = render(<ConfidenceBadge sampleSize={12} unit="matches" />)
    const { container: asStrokes } = render(<ConfidenceBadge sampleSize={12} unit="strokes" />)
    expect(filledStars(asMatches)).toBe(2)
    expect(filledStars(asStrokes)).toBe(1)
  })
})
