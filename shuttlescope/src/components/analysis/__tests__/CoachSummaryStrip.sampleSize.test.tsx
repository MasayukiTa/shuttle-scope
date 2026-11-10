/**
 * CoachSummaryStrip: サンプル数の表示。
 * i18n キー `analysis.sample_size` が未定義で、生のキー文字列が画面に出ていた。
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { CoachSummaryStrip } from '../CoachSummaryStrip'

describe('CoachSummaryStrip sample size', () => {
  it('shows the sample size, never the raw i18n key', () => {
    const { container } = render(
      <CoachSummaryStrip
        winProbability={0.6}
        confidenceStars="★★☆"
        setDistribution={{ '2-0': 0.3, '2-1': 0.3, '1-2': 0.2, '0-2': 0.2 }}
        cautionFlags={[]}
        tacticalNotes={[]}
        sampleSize={12}
      />,
    )
    const text = container.textContent ?? ''
    expect(text).not.toContain('analysis.sample_size')
    expect(text).toContain('サンプル数: 12')
  })
})
