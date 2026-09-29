/**
 * Participant rejoin proof.
 *
 * device_uid は再接続候補を探すための識別子であって認証情報ではない。
 * 同じ participant 行（approved 状態を含む）を再利用するには、join で得た
 * participant token を proof-of-possession として再提示する。
 *
 * token は localStorage ではなく sessionStorage に置く。
 * - 同一タブの reload では再接続 UX を維持
 * - ブラウザ/タブを閉じた後まで bearer credential を永続化しない
 */
const PREFIX = 'ss_participant_rejoin:'

function key(sessionCode: string, deviceUid: string): string {
  return `${PREFIX}${sessionCode.trim().toUpperCase()}:${deviceUid}`
}

export function getParticipantRejoinToken(sessionCode: string, deviceUid: string): string {
  if (!sessionCode || !deviceUid) return ''
  try {
    return sessionStorage.getItem(key(sessionCode, deviceUid)) ?? ''
  } catch {
    return ''
  }
}

export function setParticipantRejoinToken(
  sessionCode: string,
  deviceUid: string,
  token: string,
): void {
  if (!sessionCode || !deviceUid || !token) return
  try {
    sessionStorage.setItem(key(sessionCode, deviceUid), token)
  } catch {
    // Private browsing / storage-disabled contexts simply fall back to a new pending participant.
  }
}

export function clearParticipantRejoinToken(sessionCode: string, deviceUid: string): void {
  if (!sessionCode || !deviceUid) return
  try {
    sessionStorage.removeItem(key(sessionCode, deviceUid))
  } catch {
    // no-op
  }
}
