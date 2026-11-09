/**
 * T003 F-T003-01: エンリッチメント（詳細入力）パネルの対象ストローク見出し。
 *
 * 背景:
 *   以前は詳細入力が常に「末尾（直前に確定した）ストローク」へ書き込まれ、
 *   どのストロークが対象かが画面に出ていなかった。そのためサーブへ付けた
 *   つもりの意図タグ・打点高さが、次に入力したネットショットへ付いてしまう
 *   取り違えが起きていた。
 *
 * この契約テストで固定すること:
 *   1. 見出しに「対象ストローク」が明示される（何本目・ショット種別・打者）。
 *   2. 対象 index を変えると見出しがそのストロークへ切り替わる
 *      （＝直前固定ではなく、選んだストロークが対象になる）。
 *   3. 前後ボタンで対象を移動でき、端では disabled になる。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

import { EnrichmentTargetHeader } from '../EnrichmentTargetHeader'
import type { StrokeInput } from '@/types'

afterEach(() => cleanup())

const mkStroke = (over: Partial<StrokeInput>): StrokeInput => ({
  stroke_num: 1,
  player: 'player_a',
  shot_type: 'short_service',
  is_backhand: false,
  is_around_head: false,
  ...over,
})

// サーブ(1本目, player_a) → ネットショット(2本目, player_b) の 2 本。
const strokes: StrokeInput[] = [
  mkStroke({ stroke_num: 1, player: 'player_a', shot_type: 'short_service' }),
  mkStroke({ stroke_num: 2, player: 'player_b', shot_type: 'net_shot' }),
]

describe('T003 F-T003-01 EnrichmentTargetHeader 対象ストローク見出し', () => {
  it('見出しに対象ストローク（本数・ショット種別・打者）を表示する', () => {
    render(
      <EnrichmentTargetHeader
        strokes={strokes}
        targetIndex={0}
        onPrev={() => {}}
        onNext={() => {}}
        playerAName="山田"
        playerBName="佐藤"
      />,
    )
    const label = screen.getByTestId('enrichment-target-label').textContent ?? ''
    // 1本目・ショートサーブ・山田(player_a) が見出しに含まれる
    expect(label).toContain('1')
    expect(label).toContain('ショートサーブ')
    expect(label).toContain('山田')
    // 取り違えの元（2本目の相手/ショット）は出ていない
    expect(label).not.toContain('ネットショット')
    expect(label).not.toContain('佐藤')
  })

  it('対象 index を変えると見出しがそのストロークへ切り替わる（直前固定ではない）', () => {
    const { rerender } = render(
      <EnrichmentTargetHeader
        strokes={strokes}
        targetIndex={0}
        onPrev={() => {}}
        onNext={() => {}}
        playerAName="山田"
        playerBName="佐藤"
      />,
    )
    expect(screen.getByTestId('enrichment-target-label').textContent).toContain('ショートサーブ')

    // 2本目（ネットショット・佐藤）を対象に選び直す
    rerender(
      <EnrichmentTargetHeader
        strokes={strokes}
        targetIndex={1}
        onPrev={() => {}}
        onNext={() => {}}
        playerAName="山田"
        playerBName="佐藤"
      />,
    )
    const label = screen.getByTestId('enrichment-target-label').textContent ?? ''
    expect(label).toContain('2')
    expect(label).toContain('ネットショット')
    expect(label).toContain('佐藤')
    expect(label).not.toContain('ショートサーブ')
  })

  it('前後ボタンで対象を移動でき、端では disabled になる', () => {
    const onPrev = vi.fn()
    const onNext = vi.fn()
    const { rerender } = render(
      <EnrichmentTargetHeader
        strokes={strokes}
        targetIndex={0}
        onPrev={onPrev}
        onNext={onNext}
      />,
    )
    const prev = screen.getByLabelText('前のストローク') as HTMLButtonElement
    const next = screen.getByLabelText('次のストローク') as HTMLButtonElement

    // 先頭では「前へ」は無効、「次へ」は有効
    expect(prev.disabled).toBe(true)
    expect(next.disabled).toBe(false)
    fireEvent.click(next)
    expect(onNext).toHaveBeenCalledTimes(1)

    // 末尾では「次へ」は無効、「前へ」は有効
    rerender(
      <EnrichmentTargetHeader
        strokes={strokes}
        targetIndex={1}
        onPrev={onPrev}
        onNext={onNext}
      />,
    )
    const prev2 = screen.getByLabelText('前のストローク') as HTMLButtonElement
    const next2 = screen.getByLabelText('次のストローク') as HTMLButtonElement
    expect(next2.disabled).toBe(true)
    expect(prev2.disabled).toBe(false)
    fireEvent.click(prev2)
    expect(onPrev).toHaveBeenCalledTimes(1)
  })

  it('strokes が空なら何も描画しない（null 安全）', () => {
    const { container } = render(
      <EnrichmentTargetHeader strokes={[]} targetIndex={0} onPrev={() => {}} onNext={() => {}} />,
    )
    expect(container.querySelector('[data-testid="enrichment-target"]')).toBeNull()
  })
})
