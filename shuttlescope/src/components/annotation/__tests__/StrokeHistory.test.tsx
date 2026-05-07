/**
 * StrokeHistory コンポーネントテスト (Phase A override badge)
 *
 * 目的:
 *   hit_zone_source === 'manual' かつ CV 元値と現在値が異なるストロークに
 *   「手動打点」バッジが描画されることを契約として固定する。
 *   将来 hit_zone_source の値域や条件式を変えるリファクタで、
 *   override 可視性が黙って消えないようにする。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { StrokeHistory } from '../StrokeHistory'
import type { StrokeInput } from '@/types'

const baseStroke: StrokeInput = {
  stroke_num: 1,
  player: 'player_a',
  shot_type: 'short_service',
  hit_zone: 5,
  hit_zone_source: 'cv',
  hit_zone_cv_original: 5,
  land_zone: '7',
  is_backhand: false,
  is_around_head: false,
  above_net: undefined,
  timestamp_sec: 1.0,
}

describe('StrokeHistory hit_zone override badge', () => {
  it('CV と一致する打点ではバッジを表示しない', () => {
    const stroke: StrokeInput = {
      ...baseStroke,
      hit_zone: 5,
      hit_zone_source: 'cv',
      hit_zone_cv_original: 5,
    }
    render(<StrokeHistory strokes={[stroke]} />)
    expect(screen.queryByText('手動打点')).toBeNull()
  })

  it('hit_zone_source = "manual" + CV 元値と現在値が違うときバッジを表示する', () => {
    const stroke: StrokeInput = {
      ...baseStroke,
      hit_zone: 9,
      hit_zone_source: 'manual',
      hit_zone_cv_original: 5,
    }
    render(<StrokeHistory strokes={[stroke]} />)
    expect(screen.getByText('手動打点')).toBeTruthy()
  })

  it('hit_zone_source = "manual" でも CV 元値と現在値が同じならバッジを出さない', () => {
    // CV 値そのままでも source が "manual" になる経路があった場合の防衛。
    // override されていない (値が変わっていない) なら強調しない。
    const stroke: StrokeInput = {
      ...baseStroke,
      hit_zone: 5,
      hit_zone_source: 'manual',
      hit_zone_cv_original: 5,
    }
    render(<StrokeHistory strokes={[stroke]} />)
    expect(screen.queryByText('手動打点')).toBeNull()
  })

  it('hit_zone_cv_original が null/undefined なら override 判定しない', () => {
    // CV 推定が走らなかったストローク。手動入力扱いだが「override」ではない。
    const stroke: StrokeInput = {
      ...baseStroke,
      hit_zone: 9,
      hit_zone_source: 'manual',
      hit_zone_cv_original: null,
    }
    render(<StrokeHistory strokes={[stroke]} />)
    expect(screen.queryByText('手動打点')).toBeNull()
  })

  it('複数ストロークの中で override したものだけにバッジが付く', () => {
    const cv: StrokeInput = {
      ...baseStroke,
      stroke_num: 1,
      hit_zone: 5,
      hit_zone_source: 'cv',
      hit_zone_cv_original: 5,
    }
    const overridden: StrokeInput = {
      ...baseStroke,
      stroke_num: 2,
      hit_zone: 8,
      hit_zone_source: 'manual',
      hit_zone_cv_original: 3,
    }
    const cv2: StrokeInput = {
      ...baseStroke,
      stroke_num: 3,
      hit_zone: 4,
      hit_zone_source: 'cv',
      hit_zone_cv_original: 4,
    }
    render(<StrokeHistory strokes={[cv, overridden, cv2]} />)
    const badges = screen.getAllByText('手動打点')
    expect(badges).toHaveLength(1)
  })

  it('tooltip に CV 値と選択値が表示される', () => {
    const stroke: StrokeInput = {
      ...baseStroke,
      hit_zone: 7,
      hit_zone_source: 'manual',
      hit_zone_cv_original: 2,
    }
    render(<StrokeHistory strokes={[stroke]} />)
    const badge = screen.getByText('手動打点')
    const tooltip = badge.getAttribute('title') ?? ''
    expect(tooltip).toContain('2')
    expect(tooltip).toContain('7')
  })
})
