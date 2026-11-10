/**
 * 解析モード: ラリー 0 件のとき「勝率 0%」を描かない (n=0 は率にしない)
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { AnalysisModePanel } from '../AnalysisModePanel'

const base = { scoreA: 0, scoreB: 0, setNum: 1, rallyNum: 1, recentStrokes: [] }

describe('AnalysisModePanel recent rallies', () => {
  it('0 件: 勝率を描かず「データなし」の見出しにする', () => {
    const { container } = render(<AnalysisModePanel {...base} recentRallyResults={[]} />)
    const text = container.textContent ?? ''
    expect(text).not.toContain('選手 A 勝率')
    expect(text).not.toContain('0%')
    expect(text).toContain('直近 5 ラリー (データなし)')
  })

  it('件数があれば率と n を併記する', () => {
    const results = [
      { winner: 'player_a' as const },
      { winner: 'player_b' as const },
    ]
    const { container } = render(<AnalysisModePanel {...base} recentRallyResults={results} />)
    const text = container.textContent ?? ''
    expect(text).toContain('勝率 50%')
    expect(text).toContain('n=2')
  })
})
