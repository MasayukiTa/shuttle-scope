import { describe, expect, it } from 'vitest'
import { classifyQueueHttpFailure } from '../mobileAnnotateQueue'

describe('mobileAnnotateQueue HTTP failure classification', () => {
  it('waits for authentication on 401 instead of poisoning the queue', () => {
    expect(classifyQueueHttpFailure(401)).toBe('auth')
  })

  it('keeps permission and validation failures manual', () => {
    expect(classifyQueueHttpFailure(403)).toBe('manual')
    expect(classifyQueueHttpFailure(422)).toBe('manual')
  })

  it('retries throttling and server failures', () => {
    expect(classifyQueueHttpFailure(429)).toBe('retry')
    expect(classifyQueueHttpFailure(500)).toBe('retry')
    expect(classifyQueueHttpFailure(503)).toBe('retry')
  })
})
