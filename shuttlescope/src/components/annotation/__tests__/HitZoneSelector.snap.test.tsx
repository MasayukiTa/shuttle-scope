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
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { HitZoneSelector } from '../HitZoneSelector'
import { CourtDiagram, svgPointToCell } from '@/components/court/CourtDiagram'

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


describe('HitZoneSelector — hit-test gap elimination', () => {
  // grid gap-0 + 透明 padding ラッパにより、タイル間の隙間 (従来の
  // gap-1.5 の死角) をタップしてもそのセルのゾーンが選ばれることを
  // 固定する。ラッパ (= クリック領域) に onZoneSelect が一本化されている。
  it('tapping the padded cell wrapper selects that zone (idx→Zone9)', () => {
    const onSelect = vi.fn()
    render(
      <HitZoneSelector
        cvPrediction={null}
        selectedZone={null}
        onZoneSelect={onSelect}
        isOverridden={false}
      />,
    )
    // cell 1 = BL, cell 5 = MC, cell 7 = NL (ZONES の並び順)
    fireEvent.click(screen.getByTestId('hit-zone-cell-1'))
    expect(onSelect).toHaveBeenLastCalledWith('BL')
    fireEvent.click(screen.getByTestId('hit-zone-cell-5'))
    expect(onSelect).toHaveBeenLastCalledWith('MC')
    fireEvent.click(screen.getByTestId('hit-zone-cell-7'))
    expect(onSelect).toHaveBeenLastCalledWith('NL')
  })

  it('the grid uses gap-0 so there is no dead space between tiles', () => {
    const { container } = render(
      <HitZoneSelector
        cvPrediction={null}
        selectedZone={null}
        onZoneSelect={() => {}}
        isOverridden={false}
      />,
    )
    const grid = container.querySelector('[role="grid"]')
    expect(grid).toBeTruthy()
    expect(grid!.className).toContain('gap-0')
  })

  it('does not fire when disabled, even on the wrapper', () => {
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
    fireEvent.click(screen.getByTestId('hit-zone-cell-3'))
    expect(onSelect).not.toHaveBeenCalled()
  })
})

describe('CourtDiagram — svgPointToCell gap snap', () => {
  // アクティブ半面の SVG 座標→{row,col}。セル間/枠線上/半面外の
  // いずれも必ず 0..2 に clamp され、死角が生じないことを固定。
  // hit 半面: top=200, height=200。
  it('maps interior points to the correct 3×3 cell', () => {
    expect(svgPointToCell(50, 233, 200, 200)).toEqual({ row: 0, col: 0 })   // 左上
    expect(svgPointToCell(150, 300, 200, 200)).toEqual({ row: 1, col: 1 }) // 中央
    expect(svgPointToCell(250, 366, 200, 200)).toEqual({ row: 2, col: 2 }) // 右下
  })

  it('snaps a tap exactly on a cell border into an adjacent cell (no dead gap)', () => {
    // x=100 は col0/col1 の境界、y=266.67 は row0/row1 の境界。
    // floor により境界は次のセル側へ割り当てられ (死角に落ちない)。
    expect(svgPointToCell(100, 200, 200, 200)).toEqual({ row: 0, col: 1 })
  })

  it('clamps out-of-half / out-of-court taps to the edge cell', () => {
    expect(svgPointToCell(-20, 199, 200, 200)).toEqual({ row: 0, col: 0 }) // 左上外
    expect(svgPointToCell(320, 410, 200, 200)).toEqual({ row: 2, col: 2 }) // 右下外
  })

  it('renders a transparent hit overlay in interactive hit mode', () => {
    const { container } = render(
      <CourtDiagram mode="hit" selectedZone={null} onZoneSelect={() => {}} />,
    )
    expect(container.querySelector('[data-testid="court-diagram-hit-overlay"]')).toBeTruthy()
  })
})
