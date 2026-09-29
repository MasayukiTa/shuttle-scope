/**
 * 移動量カードのミニコートヒートマップの行並び。
 *
 * `front` / `mid` / `back` は **ネットからの距離** で、画面上の位置ではない。
 * 上から下へ A_back / A_mid / A_front | NET | B_front / B_mid / B_back と並ぶ。
 *
 * A-1b 以前は `pixel_to_court_zone` が A 側だけ depth を反転させて出しており
 * (コート y=0 の奥のベースラインを "front" と呼んでいた)、この描画が
 * `si * 3 + di` という素直な並べ方をしていたおかげで**見た目だけ合っていた**。
 * バックエンドを直した時点で A 側が上下逆になるので、ここも直す。
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { MiniCourtHeatmap } from '../PlayerMovementCard'

const CELL_H = 16
const NET_H = 4

/** そのゾーンのセルが描かれた y 座標を返す。 */
function yOf(zone: string): number {
  const { container } = render(
    <MiniCourtHeatmap zoneVisits={{ [zone]: 5 }} playerKey="player_a" isLight />,
  )
  const g = container.querySelector(`g[key="${zone}"]`) ?? null
  // React は key を DOM に出さないので、描かれた数字から特定する。
  const texts = Array.from(container.querySelectorAll('text')).filter(
    (t) => t.textContent === '5',
  )
  expect(texts.length, `${zone} のセルが 1 つだけ描かれていない`).toBe(1)
  void g
  // text の y はセル中心 + 4
  return Number(texts[0].getAttribute('y')) - CELL_H / 2 - 4
}

describe('MiniCourtHeatmap の行並び', () => {
  it('A 側はネットに近いほど下（A_back が一番上）', () => {
    expect(yOf('A_back_left')).toBe(0)
    expect(yOf('A_mid_left')).toBe(CELL_H)
    expect(yOf('A_front_left')).toBe(CELL_H * 2)
  })

  it('B 側はネットに近いほど上（B_back が一番下）', () => {
    expect(yOf('B_front_left')).toBe(CELL_H * 3 + NET_H)
    expect(yOf('B_mid_left')).toBe(CELL_H * 4 + NET_H)
    expect(yOf('B_back_left')).toBe(CELL_H * 5 + NET_H)
  })

  it('front 同士がネット線を挟んで隣り合う', () => {
    const netY = CELL_H * 3
    const aFrontBottom = yOf('A_front_left') + CELL_H
    const bFrontTop = yOf('B_front_left')
    expect(aFrontBottom).toBe(netY)
    expect(bFrontTop).toBe(netY + NET_H)
  })

  it('列は鏡映しない（left は両半面とも同じ x）', () => {
    const xOf = (zone: string) => {
      const { container } = render(
        <MiniCourtHeatmap zoneVisits={{ [zone]: 7 }} playerKey="player_a" isLight />,
      )
      const t = Array.from(container.querySelectorAll('text')).find(
        (n) => n.textContent === '7',
      )
      return Number(t!.getAttribute('x'))
    }
    expect(xOf('A_front_left')).toBe(xOf('B_front_left'))
    expect(xOf('A_front_right')).toBe(xOf('B_front_right'))
    expect(xOf('A_front_left')).toBeLessThan(xOf('A_front_right'))
  })
})
