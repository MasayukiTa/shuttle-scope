/**
 * ShotTypePanel の「AI入力補助」★印 UI 結線の回帰テスト。
 *
 * 背景:
 *   候補の並べ替え・最多候補の選定ロジックは shotSuggestion.ts (rankShotGroups)
 *   に純関数として実装され、shotSuggestion.test.ts で単体検証済み。しかし、その
 *   結果の topSuggestion を ShotTypePanel が実際に DOM へ描画する結線
 *   (data-top-suggestion 属性 と ★ (star) アイコン、title/aria-label) が外れても、
 *   純関数テストは緑のままになる。本テストはその UI 結線を固定する:
 *
 *   (1) 現ラリー履歴 (strokes) を渡すと、直前ショット種別の「次」に最多で選ばれた
 *       種別のタイルに data-top-suggestion="true" と ★ アイコンが付く。
 *   (2) strokes 省略 (従来挙動) では ★ 印が一切付かない (後方互換)。
 *
 * 実在の選手名・実データは使わない (合成ショット列のみ)。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ShotTypePanel } from '../ShotTypePanel'
import type { ShotType } from '@/types'
import type { ShotTypeRecord } from '../shotSuggestion'

const rec = (s: ShotType): ShotTypeRecord => ({ shot_type: s })

/** data-top-suggestion="true" が付いたタイルを集める。 */
function topTiles(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll('[data-tile="true"][data-top-suggestion="true"]'),
  ) as HTMLElement[]
}

describe('ShotTypePanel AI入力補助の★印 UI 結線', () => {
  it('現ラリー履歴の最多「次打」タイルに data-top-suggestion と ★ が付く', () => {
    // clear の次: drop, drop, smash → drop が最多 (2 件)。
    // stroke_num>=2 の既定グループ back に drop/smash/clear が含まれる。
    const strokes = [
      rec('clear'), rec('drop'),
      rec('clear'), rec('drop'),
      rec('clear'), rec('smash'),
    ]
    render(
      <ShotTypePanel
        selected={null}
        onSelect={() => {}}
        strokeNum={2}
        lastShotType="clear"
        strokes={strokes}
      />,
    )

    const tops = topTiles()
    // 最多候補はちょうど 1 件。
    expect(tops).toHaveLength(1)
    // それは drop タイル (日本語ラベル「ドロップ」)。
    expect(tops[0].textContent).toContain('ドロップ')
    // ★ (star) アイコンが aria-label つきで付く。
    const star = screen.getByLabelText('このラリーで最も多い次打')
    expect(star).toBeTruthy()
    expect(tops[0].contains(star)).toBe(true)
  })

  it('strokes 省略時 (従来挙動) は ★ 印が付かない', () => {
    render(
      <ShotTypePanel
        selected={null}
        onSelect={() => {}}
        strokeNum={2}
        lastShotType="clear"
      />,
    )
    expect(topTiles()).toHaveLength(0)
    expect(screen.queryByLabelText('このラリーで最も多い次打')).toBeNull()
  })

  it('クリックした種別が onSelect に渡る (★印は選択挙動を壊さない)', () => {
    const onSelect = vi.fn()
    const strokes = [
      rec('clear'), rec('drop'),
      rec('clear'), rec('drop'),
    ]
    render(
      <ShotTypePanel
        selected={null}
        onSelect={onSelect}
        strokeNum={2}
        lastShotType="clear"
        strokes={strokes}
      />,
    )
    // ★ が付いた drop タイルをクリックしても、pre-select ではなく通常の onSelect。
    const top = topTiles()[0]
    top.click()
    expect(onSelect).toHaveBeenCalledWith('drop')
  })
})
