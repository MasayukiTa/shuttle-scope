import { describe, expect, it } from 'vitest'
import { INFER_DEADLINE_MS, isInferenceOverdue } from '../useRealtimeYolo'

describe('isInferenceOverdue (lost-frame watchdog)', () => {
  it('releases a stuck inflight once the deadline has passed', () => {
    expect(isInferenceOverdue(1, 1000, 1000 + INFER_DEADLINE_MS + 1)).toBe(true)
  })

  it('keeps waiting while the response is still within the deadline', () => {
    expect(isInferenceOverdue(1, 1000, 1000 + INFER_DEADLINE_MS)).toBe(false)
  })

  it('never fires when nothing is in flight', () => {
    expect(isInferenceOverdue(0, 0, 10 * INFER_DEADLINE_MS)).toBe(false)
  })
})
