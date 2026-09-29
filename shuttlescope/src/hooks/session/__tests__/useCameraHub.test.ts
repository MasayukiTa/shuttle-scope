import { describe, expect, it } from 'vitest'

import {
  enqueuePendingIce,
  MAX_PENDING_ICE_CANDIDATES,
} from '../useCameraHub'

function ice(n: number): RTCIceCandidateInit {
  return { candidate: `candidate-${n}`, sdpMid: '0', sdpMLineIndex: 0 }
}

describe('pending ICE queue bound', () => {
  it('keeps all candidates below the cap', () => {
    const queue: RTCIceCandidateInit[] = []
    for (let i = 0; i < 5; i += 1) enqueuePendingIce(queue, ice(i))
    expect(queue.map((x) => x.candidate)).toEqual([
      'candidate-0',
      'candidate-1',
      'candidate-2',
      'candidate-3',
      'candidate-4',
    ])
  })

  it('never grows beyond the cap and drops the oldest candidates', () => {
    const queue: RTCIceCandidateInit[] = []
    for (let i = 0; i < MAX_PENDING_ICE_CANDIDATES + 20; i += 1) {
      enqueuePendingIce(queue, ice(i))
    }

    expect(queue).toHaveLength(MAX_PENDING_ICE_CANDIDATES)
    expect(queue[0]?.candidate).toBe('candidate-20')
    expect(queue[queue.length - 1]?.candidate).toBe(
      `candidate-${MAX_PENDING_ICE_CANDIDATES + 19}`,
    )
  })
})
