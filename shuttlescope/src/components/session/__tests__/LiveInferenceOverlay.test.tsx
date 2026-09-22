/**
 * ライブ推論オーバーレイのマーカー表示条件。
 *
 * A-1b で CV は画像座標から Zone9 を名乗るのをやめた（画像座標には
 * ネット位置も半面も遠近も入っていないので決めようがない）。その結果
 * `live_frame_hint` の `zone` は常に null になる。
 *
 * `ZoneMarker` は `!candidate.zone` を描画条件に入れていたので、その瞬間に
 * **マーカーが完全に消えた**。ここで見せたいのは「シャトルがどこにいるか」で、
 * ゾーン名は横のテキストの話。条件は位置があることだけにする。
 *
 * ついでに `!candidate.x_norm` は **0 を falsy として弾く**ので、
 * 画面の左端・上端にシャトルが来るとマーカーが消えていた。
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { ZoneMarker } from '../LiveInferenceOverlay'
import type { LiveInferenceCandidate } from '@/types'

function candidate(over: Partial<LiveInferenceCandidate> = {}): LiveInferenceCandidate {
  return {
    zone: null,
    confidence: 0.8,
    x_norm: 0.4,
    y_norm: 0.6,
    available: true,
    ...over,
  }
}

function marker(container: HTMLElement): HTMLElement | null {
  return container.querySelector('.absolute.pointer-events-none')
}

describe('ZoneMarker', () => {
  it('ゾーン名が無くても位置があれば描く', () => {
    const { container } = render(<ZoneMarker candidate={candidate({ zone: null })} />)
    const el = marker(container)
    expect(el).not.toBeNull()
    expect(el!.getAttribute('style')).toContain('left: 40%')
    expect(el!.getAttribute('style')).toContain('top: 60%')
  })

  it('ゾーン名があるときも当然描く', () => {
    const { container } = render(<ZoneMarker candidate={candidate({ zone: 'BL' })} />)
    expect(marker(container)).not.toBeNull()
  })

  it('左端・上端 (0) でも消えない', () => {
    const { container } = render(
      <ZoneMarker candidate={candidate({ x_norm: 0, y_norm: 0 })} />,
    )
    const el = marker(container)
    expect(el).not.toBeNull()
    expect(el!.getAttribute('style')).toContain('left: 0%')
    expect(el!.getAttribute('style')).toContain('top: 0%')
  })

  it('位置が無ければ描かない', () => {
    const { container } = render(
      <ZoneMarker
        candidate={candidate({
          x_norm: null as unknown as number,
          y_norm: null as unknown as number,
        })}
      />,
    )
    expect(marker(container)).toBeNull()
  })
})
