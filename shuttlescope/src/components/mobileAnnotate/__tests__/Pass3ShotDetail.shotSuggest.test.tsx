/**
 * v2 次ショット候補 (shot_type suggestion):
 * - pickShot フェーズで、直前の shot_type に紐づく top-3 候補が
 *   固定グリッドより前に出る。
 * - 候補は pre-select されず (自動で onStrokeAdded しない)、タップで
 *   通常の onPick 経由で hitZone へ進む。
 * - 候補が空 (player ロール / データ不足) のときは候補ブロックを出さない。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import ja from '@/i18n/ja.json'

vi.mock('@/hooks/useHapticFeedback', () => ({ useHapticFeedback: () => ({ tap: () => {}, impact: () => {} }) }))
vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

import { Pass3ShotDetail } from '../Pass3ShotDetail'

const L = (ja as unknown as { auto: { Pass3ShotDetail: Record<string, string> } }).auto.Pass3ShotDetail

const rally = { id: 1, rally_num: 1, set_num: 1, server: 'player_a' as const, winner: 'player_a' as const }

// 中間球を 1 つ置き、直前 shot_type = 'smash' にする。
const strokes = [
  { id: 10, stroke_num: 1, player: 'player_a' as const, shot_type: 'smash' },
]

// 本番の ShotSuggestion 形 (shot_type / confidence_score / decision_mode) で渡す。
// ラベルは Pass3ShotDetail が labelForShot で解決するので、ここでは渡さない。
function suggestionMap() {
  return new Map<string, Array<{ shot_type: string; confidence_score: number; decision_mode: string }>>([
    ['smash', [
      { shot_type: 'clear', confidence_score: 0.52, decision_mode: 'auto_filled' },
      { shot_type: 'drop', confidence_score: 0.3, decision_mode: 'suggested' },
      { shot_type: 'net_shot', confidence_score: 0.12, decision_mode: 'review_required' },
    ]],
  ])
}

function renderDetail(opts: { suggestions?: Map<string, Array<{ shot_type: string; confidence_score: number; decision_mode: string }>> | null }) {
  const onStrokeAdded = vi.fn()
  render(
    <Pass3ShotDetail
      rally={rally}
      strokes={strokes as never}
      doubles={false}
      shotTypeSuggestions={(opts.suggestions ?? null) as never}
      onStrokeAdded={onStrokeAdded}
      onStrokeUpdated={() => {}}
      onClose={() => {}}
    />,
  )
  return { onStrokeAdded }
}

function openPickShot() {
  // 「追加」ボタン (data-tutorial) で pickShot へ。
  const addBtn = document.querySelector('[data-tutorial="mobileAnnotate.addStroke"]') as HTMLButtonElement
  expect(addBtn).toBeTruthy()
  fireEvent.click(addBtn)
}

describe('Pass3ShotDetail v2 next-shot suggestions', () => {
  it('surfaces top-3 candidates at the front, not pre-selected', () => {
    const { onStrokeAdded } = renderDetail({ suggestions: suggestionMap() })
    openPickShot()
    const grid = screen.getByTestId('shot-suggestions')
    const chips = within(grid).getAllByRole('button')
    expect(chips).toHaveLength(3)
    // 先頭性: 候補グリッドがタイトル直後にあり、最初の候補ラベルがクリア。
    expect(chips[0].textContent).toContain(L.k2)
    // pre-select されていない: レンダ直後に保存は起きない。
    expect(onStrokeAdded).not.toHaveBeenCalled()
    // 各チップは「候補(未確定)」バッジを持つ。
    expect(grid.textContent).toContain(L.suggest_badge)
  })

  it('tapping a candidate advances via onPick (candidate block disappears)', () => {
    renderDetail({ suggestions: suggestionMap() })
    openPickShot()
    const grid = screen.getByTestId('shot-suggestions')
    const first = within(grid).getAllByRole('button')[0]
    fireEvent.click(first)
    // hitZone へ進むと候補グリッドは消える。
    expect(screen.queryByTestId('shot-suggestions')).toBeNull()
  })

  it('renders no candidate block when suggestions are empty (player role / insufficient data)', () => {
    renderDetail({ suggestions: null })
    openPickShot()
    expect(screen.queryByTestId('shot-suggestions')).toBeNull()
  })
})
