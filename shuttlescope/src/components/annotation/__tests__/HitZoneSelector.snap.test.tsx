/**
 * HitZoneSelector / CourtDiagram — snap 可視表示のコンポーネントテスト
 *
 * 背景:
 *   courtHomography の fallbackTapToCellClamped / calibratedTapToCellClamped は
 *   枠外タップを端マスへ丸めた事実を clamped フラグで返すが、その事実は
 *   これまで UI に伝搬されていなかった。ユーザは「なぜこのマスが選ばれたのか」
 *   が分からず、補正を見落とす。このテストは snapped prop が渡されたとき
 *   両コンポーネントが snap バッジを render すること (そして false のとき出さない
 *   こと) を固定する。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { HitZoneSelector } from '../HitZoneSelector'
import { CourtDiagram } from '@/components/court/CourtDiagram'

describe('HitZoneSelector snap indication', () => {
  it('renders the snap badge when snapped=true', () => {
    render(
      <HitZoneSelector
        cvPrediction={null}
        selectedZone={'MC'}
        onZoneSelect={() => {}}
        isOverridden={false}
        snapped
      />,
    )
    expect(screen.getByTestId('hit-zone-snapped-badge')).toBeTruthy()
  })

  it('does NOT render the snap badge when snapped=false (default)', () => {
    render(
      <HitZoneSelector
        cvPrediction={null}
        selectedZone={'MC'}
        onZoneSelect={() => {}}
        isOverridden={false}
      />,
    )
    expect(screen.queryByTestId('hit-zone-snapped-badge')).toBeNull()
  })

  it('snap badge is independent from the manual-override badge', () => {
    // snapped と isOverridden は同時に成立しうる (手動で枠外をタップ→補正)。
    render(
      <HitZoneSelector
        cvPrediction={'MC'}
        selectedZone={'NL'}
        onZoneSelect={() => {}}
        isOverridden
        snapped
      />,
    )
    expect(screen.getByTestId('hit-zone-snapped-badge')).toBeTruthy()
  })
})

describe('CourtDiagram snap indication', () => {
  it('renders the snap badge when snapped=true', () => {
    render(
      <CourtDiagram
        mode="hit"
        selectedZone={'MC'}
        onZoneSelect={() => {}}
        snapped
      />,
    )
    expect(screen.getByTestId('court-diagram-snapped-badge')).toBeTruthy()
  })

  it('does NOT render the snap badge when snapped is omitted', () => {
    render(
      <CourtDiagram
        mode="hit"
        selectedZone={'MC'}
        onZoneSelect={() => {}}
      />,
    )
    expect(screen.queryByTestId('court-diagram-snapped-badge')).toBeNull()
  })
})
