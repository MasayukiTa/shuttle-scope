import { afterEach, describe, expect, it, vi } from 'vitest'
import { addCandidate, connectionAction, flushCandidates, watchPeerConnection } from '../peerConnection'

afterEach(() => vi.useRealTimers())

describe('peer connection handling', () => {
  it('maps connection states', () => {
    expect(['new', 'connecting', 'connected', 'disconnected', 'failed', 'closed'].map(
      state => connectionAction(state as RTCPeerConnectionState),
    )).toEqual(['none', 'none', 'connected', 'wait', 'failed', 'none'])
  })

  it('allows recovery within the grace period and reports a persistent disconnect', () => {
    vi.useFakeTimers()
    const pc = { connectionState: 'disconnected' } as RTCPeerConnection
    const connected = vi.fn(), failed = vi.fn()
    watchPeerConnection(pc, () => true, connected, failed)
    const change = () => pc.onconnectionstatechange!(new Event('connectionstatechange'))
    change()
    Object.assign(pc, { connectionState: 'connected' })
    change()
    vi.advanceTimersByTime(4000)
    expect(connected).toHaveBeenCalledTimes(1)
    expect(failed).not.toHaveBeenCalled()
    Object.assign(pc, { connectionState: 'disconnected' })
    change()
    vi.advanceTimersByTime(4000)
    expect(failed).toHaveBeenCalledTimes(1)
  })

  it('queues early ICE and continues after a rejected candidate', async () => {
    const addIceCandidate = vi.fn().mockRejectedValueOnce(new Error('race')).mockResolvedValue(undefined)
    const pc = { remoteDescription: null, addIceCandidate } as unknown as RTCPeerConnection
    const queue: RTCIceCandidateInit[] = []
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await addCandidate(pc, queue, { candidate: 'first' })
    await addCandidate(pc, queue, { candidate: 'second' })
    expect(addIceCandidate).not.toHaveBeenCalled()
    Object.assign(pc, { remoteDescription: { type: 'offer', sdp: '' } })
    await flushCandidates(pc, queue)
    expect(addIceCandidate).toHaveBeenCalledTimes(2)
    expect(queue).toHaveLength(0)
    expect(warn).toHaveBeenCalledTimes(1)
    warn.mockRestore()
  })
})
