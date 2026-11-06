/**
 * 確認モード: 実データ未接続 (connected 未指定=default false) のときは
 * 「境界候補 0 / ID紐付 0 / Swing 0」を実測値のように出さず、「未接続（開発中）」を明示する。
 * connected のときは従来通り件数バッジを表示する。
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { ReviewModePanel } from '../ReviewModePanel'

describe('ReviewModePanel 未接続表示', () => {
  it('connected 未指定: 件数バッジを出さず未接続を明示する', () => {
    const { container } = render(<ReviewModePanel />)
    const text = container.textContent ?? ''
    // 固定 default 0 を実測値のように見せない
    expect(text).not.toContain('境界候補 0')
    expect(text).not.toContain('ID紐付 0')
    expect(text).not.toContain('Swing 0')
    // 未接続を明示
    expect(text).toContain('未接続')
    expect(text).toContain('開発中')
  })

  it('connected: 従来通り件数バッジを表示する', () => {
    const { container } = render(
      <ReviewModePanel
        connected
        rallyBoundaryCount={3}
        identityMappingCount={2}
        swingEventCount={5}
      />,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('境界候補 3')
    expect(text).toContain('ID紐付 2')
    expect(text).toContain('Swing 5')
  })
})
