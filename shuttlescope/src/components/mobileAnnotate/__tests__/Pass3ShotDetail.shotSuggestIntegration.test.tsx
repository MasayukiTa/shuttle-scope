/**
 * AI入力補助 (next shot_type suggestion) の回帰テスト。
 *
 * 既存の 2 本はそれぞれ単体だった:
 *   - mobileAnnotateShotSuggest.test.ts   : util 単体 (遷移・候補抽出・role ゲート)
 *   - Pass3ShotDetail.shotSuggest.test.tsx : UI 単体 (suggestions prop を手組みで渡す)
 *
 * 本テストは両者を繋ぐ経路を固める:
 *   (1) buildShotTypeSuggestions の *実出力* をそのまま Pass3ShotDetail に食わせ、
 *       実データから UI の候補チップが出るまでを一気通貫で検証する
 *       (prop の型契約がずれたらここで落ちる)。
 *   (2) canSuggestShotType が false の role (player) では null となり、
 *       候補ブロックが出ない end-to-end を固める。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

vi.mock('@/hooks/useHapticFeedback', () => ({ useHapticFeedback: () => ({ tap: () => {}, impact: () => {} }) }))
vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

import { Pass3ShotDetail } from '../Pass3ShotDetail'
import {
  buildShotTypeSuggestions,
  canSuggestShotType,
  type SuggestRally,
} from '@/utils/mobileAnnotateShotSuggest'

const rally = { id: 1, rally_num: 1, set_num: 1, server: 'player_a' as const, winner: 'player_a' as const }

// 中間球を 1 つ置き、直前 shot_type = 'smash' にする。
const strokes = [
  { id: 10, stroke_num: 1, player: 'player_a' as const, shot_type: 'smash' },
]

// smash -> clear を閾値 (minSupport=10) 超えの支持で作る。
// clear が圧倒的多数なので top-1 候補は clear (= k2)。
function smashHeavyRallies(): SuggestRally[] {
  const rallies: SuggestRally[] = []
  for (let i = 0; i < 12; i++) {
    rallies.push({ strokes: [
      { stroke_num: 1, shot_type: 'smash' },
      { stroke_num: 2, shot_type: 'clear' },
    ] })
  }
  return rallies
}

function renderWith(suggestions: ReturnType<typeof buildShotTypeSuggestions> | null) {
  const onStrokeAdded = vi.fn()
  render(
    <Pass3ShotDetail
      rally={rally}
      strokes={strokes as never}
      doubles={false}
      shotTypeSuggestions={(suggestions ?? null) as never}
      onStrokeAdded={onStrokeAdded}
      onStrokeUpdated={() => {}}
      onClose={() => {}}
    />,
  )
  return { onStrokeAdded }
}

function openPickShot() {
  const addBtn = document.querySelector('[data-tutorial="mobileAnnotate.addStroke"]') as HTMLButtonElement
  expect(addBtn).toBeTruthy()
  fireEvent.click(addBtn)
}

describe('AI入力補助 end-to-end (util 実出力 -> Pass3ShotDetail)', () => {
  it('buildShotTypeSuggestions の実出力がそのまま UI の候補チップになる (clear が先頭)', () => {
    const suggestions = buildShotTypeSuggestions(smashHeavyRallies())
    // util が smash 行を実際に生成していること (前提の検査)。
    expect(suggestions.get('smash')?.length).toBeGreaterThan(0)
    expect(suggestions.get('smash')?.[0].shot_type).toBe('clear')

    const { onStrokeAdded } = renderWith(suggestions)
    openPickShot()
    const grid = screen.getByTestId('shot-suggestions')
    const chips = within(grid).getAllByRole('button')
    // top-3 が前面に出る。
    expect(chips.length).toBeGreaterThan(0)
    expect(chips.length).toBeLessThanOrEqual(3)
    // 先頭候補は clear = k2。
    expect(chips[0].textContent).toContain('クリア')
    // pre-select されない。
    expect(onStrokeAdded).not.toHaveBeenCalled()
    // 候補は「候補（未確定）」バッジを持つ。
    expect(grid.textContent).toContain('候補')
  })

  it('canSuggestShotType=false の role (player) では候補を作らず UI にも出ない', () => {
    // 親の配線と同じように role ゲート -> null。
    const suggestions = canSuggestShotType('player') ? buildShotTypeSuggestions(smashHeavyRallies()) : null
    expect(suggestions).toBeNull()
    renderWith(suggestions)
    openPickShot()
    expect(screen.queryByTestId('shot-suggestions')).toBeNull()
  })

  it('データ不足 (支持 < 10) では候補を出さない (全 18 チップにフォールバック)', () => {
    // smash -> clear を 3 回だけ = 閾値未満。
    const few: SuggestRally[] = Array.from({ length: 3 }, () => ({
      strokes: [
        { stroke_num: 1, shot_type: 'smash' },
        { stroke_num: 2, shot_type: 'clear' },
      ],
    }))
    const suggestions = buildShotTypeSuggestions(few)
    // util 側ですでに空 (支持未満なので smash キーが入らない)。
    expect(suggestions.get('smash')).toBeUndefined()
    renderWith(suggestions)
    openPickShot()
    expect(screen.queryByTestId('shot-suggestions')).toBeNull()
  })
})
