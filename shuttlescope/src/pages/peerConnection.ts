export function connectionAction(state: RTCPeerConnectionState): 'connected' | 'wait' | 'failed' | 'none' {
  if (state === 'connected') return 'connected'
  if (state === 'disconnected') return 'wait'
  if (state === 'failed') return 'failed'
  return 'none'
}

export function watchPeerConnection(
  pc: RTCPeerConnection, isCurrent: () => boolean, onConnected: () => void, onFailed: () => void,
) {
  let timer: ReturnType<typeof setTimeout> | undefined
  pc.onconnectionstatechange = () => {
    if (!isCurrent()) { if (timer) clearTimeout(timer); return }
    const action = connectionAction(pc.connectionState)
    if (action === 'connected' || action === 'failed' || pc.connectionState === 'closed') {
      if (timer) clearTimeout(timer)
      timer = undefined
    }
    if (action === 'connected') onConnected()
    if (action === 'failed') onFailed()
    if (action === 'wait' && !timer) {
      timer = setTimeout(() => {
        timer = undefined
        if (isCurrent() && pc.connectionState !== 'connected' && pc.connectionState !== 'closed') onFailed()
      }, 4000)
    }
  }
}

export async function addCandidate(pc: RTCPeerConnection | null, queue: RTCIceCandidateInit[], candidate: RTCIceCandidateInit) {
  if (!pc?.remoteDescription) { queue.push(candidate); return }
  try { await pc.addIceCandidate(candidate) } catch (error) { console.warn('ICE candidate rejected', error) }
}

export async function flushCandidates(pc: RTCPeerConnection, queue: RTCIceCandidateInit[]) {
  while (queue.length) await addCandidate(pc, queue, queue.shift()!)
}
