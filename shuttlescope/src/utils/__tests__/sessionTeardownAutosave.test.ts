import { beforeEach, describe, expect, it } from 'vitest'
import {
  AUTOSAVE_PREFIX,
  buildAutosaveKey,
  isAutosaveOwnedBy,
  planSessionTeardown,
  type SessionEndReason,
} from '../annotatorAutosave'
import {
  offlineStrokeIdempotencyKey,
  pendingRallyBelongsTo,
} from '../offlineStrokeQueue'

/**
 * \u8981\u671b (2026-11-05 ELN E-90e8cfaa2891):
 *   \u300c\u4f55\u304b\u5165\u529b\u3059\u308b\u305f\u3073\u306b\u4fdd\u5b58\u3055\u308c\u308b\u5f62\u614b\u3067\u3042\u308b\u3079\u304d\u3002\u4fdd\u5b58\u3057\u7d42\u3048\u305f\u306f\u305a\u304c\u4fdd\u5b58\u5931\u6557\u3068\u51fa\u308b\u5834\u5408\u304c\u3042\u308b\u300d\u3002
 *
 * \u672c\u4eba\u304c\u5165\u529b\u6e08\u307f\u306e\u30b9\u30c8\u30ed\u30fc\u30af\u304c\u3001\u6b21\u306e 4 \u3064\u306e\u5834\u5408\u306b\u5931\u308f\u308c\u306a\u3044\u3053\u3068\u3092\u8868\u660e\u3059\u308b:
 *   (a) \u30e9\u30ea\u30fc\u78ba\u5b9a\u524d\u306b\u30bf\u30d6\u3092\u9589\u3058\u305f
 *   (b) \u30d6\u30e9\u30a6\u30b6\u304c\u843d\u3061\u305f
 *   (c) \u901a\u4fe1\u304c\u5207\u308c\u305f
 *   (d) \u30ed\u30b0\u30a2\u30a6\u30c8\u3055\u308c\u305f (401/403 \u306e\u610f\u56f3\u3057\u306a\u3044\u5931\u52b9\u3092\u542b\u3080)
 */

const USER = 7
const MATCH = 12
const SET = 3

// \u5165\u529b\u4e2d\u306e\u30e9\u30ea\u30fc\u3092 localStorage \u3078\u66f8\u304f (saveAutosaveNow \u304c\u66f8\u304f\u5f62\u3068\u540c\u3058\u5f62)\u3002
function writeAutosave(strokesCount: number): string {
  const key = buildAutosaveKey(MATCH, USER)
  if (!key) throw new Error('autosave key should exist for a known user and match')
  const data = {
    setId: SET,
    rallyNum: 5,
    strokes: Array.from({ length: strokesCount }, (_, i) => ({ shot_type: 'clear', seq: i })),
    pendingStroke: {},
    inputStep: 'idle',
    rallyStartTimestamp: 1,
    currentPlayer: 'player_a',
    currentHitter: 'player_a',
    videoTimestamp: 1,
    savedAt: Date.now(),
    ownerUserId: USER,
  }
  localStorage.setItem(key, JSON.stringify(data))
  return key
}

// \u30bf\u30d6\u3092\u9589\u3058\u308b / \u30af\u30e9\u30c3\u30b7\u30e5 = JS \u30e1\u30e2\u30ea\u306f\u6d88\u3048\u308b\u304c localStorage \u306f\u6b8b\u308b\u3002
// \u65b0\u3057\u3044\u30bf\u30d6\u3067\u5fa9\u5143\u3067\u304d\u308b\u304b\u3092\u3001\u4fdd\u5b58\u6e08\u307f JSON \u304b\u3089\u78ba\u304b\u3081\u308b\u3002
function restoreOwnedStrokes(userId: number): number | null {
  const key = buildAutosaveKey(MATCH, userId)
  if (!key) return null
  const raw = localStorage.getItem(key)
  if (!raw) return null
  const saved = JSON.parse(raw) as { strokes: unknown[]; ownerUserId?: number | null }
  if (!isAutosaveOwnedBy(saved, userId)) return null
  return saved.strokes.length
}

describe('planSessionTeardown \u2014 4 \u3064\u306e\u5834\u5408\u3067\u5165\u529b\u3092\u5931\u308f\u306a\u3044', () => {
  it('closeTab: \u8ffd\u52a0 flush \u306f\u4e0d\u8981 / \u4e00\u6642\u4fdd\u5b58\u306f\u6b8b\u308b', () => {
    expect(planSessionTeardown('closeTab')).toEqual({
      flushAutosaveBeforeTeardown: false,
      keepAutosave: true,
    })
  })

  it('crash: \u8ffd\u52a0 flush \u306f\u4e0d\u8981 / \u4e00\u6642\u4fdd\u5b58\u306f\u6b8b\u308b', () => {
    expect(planSessionTeardown('crash')).toEqual({
      flushAutosaveBeforeTeardown: false,
      keepAutosave: true,
    })
  })

  it('networkLost: \u30bb\u30c3\u30b7\u30e7\u30f3\u306f\u7d9a\u304f / \u4e00\u6642\u4fdd\u5b58\u3092\u6b8b\u3059', () => {
    expect(planSessionTeardown('networkLost')).toEqual({
      flushAutosaveBeforeTeardown: false,
      keepAutosave: true,
    })
  })

  it('idleLogout: \u5931\u52b9\u524d\u306b flush \u3057\u3066 \u4e00\u6642\u4fdd\u5b58\u3092\u6b8b\u3059', () => {
    expect(planSessionTeardown('idleLogout')).toEqual({
      flushAutosaveBeforeTeardown: true,
      keepAutosave: true,
    })
  })

  it('tokenExpired (401/403): idleLogout \u3068\u540c\u3058\u304f flush \u3057\u3066\u4e00\u6642\u4fdd\u5b58\u3092\u6b8b\u3059', () => {
    expect(planSessionTeardown('tokenExpired')).toEqual({
      flushAutosaveBeforeTeardown: true,
      keepAutosave: true,
    })
  })

  it('explicitLogout \u306e\u3068\u304d\u3060\u3051 \u4e00\u6642\u4fdd\u5b58\u3092\u6d88\u3059 (\u5171\u6709\u7aef\u672b\u914d\u616e)', () => {
    expect(planSessionTeardown('explicitLogout')).toEqual({
      flushAutosaveBeforeTeardown: false,
      keepAutosave: false,
    })
  })

  it('\u610f\u56f3\u3057\u306a\u3044\u7d42\u4e86\u306f\u3059\u3079\u3066\u4e00\u6642\u4fdd\u5b58\u3092\u6b8b\u3059 (\u5165\u529b\u3092\u5931\u308f\u306a\u3044)', () => {
    const unintended: SessionEndReason[] = ['closeTab', 'crash', 'networkLost', 'idleLogout', 'tokenExpired']
    for (const reason of unintended) {
      expect(planSessionTeardown(reason).keepAutosave).toBe(true)
    }
  })
})

describe('\u5165\u529b\u6e08\u307f\u30b9\u30c8\u30ed\u30fc\u30af\u306e\u5fa9\u5143 \u2014 \u5b9f\u30c7\u30fc\u30bf\u5f80\u5fa9', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('(a) \u30bf\u30d6\u3092\u9589\u3058\u3066\u3082 \u672c\u4eba\u306e localStorage \u304b\u3089\u5fa9\u5143\u3067\u304d\u308b', () => {
    writeAutosave(3)
    // \u30bf\u30d6\u3092\u9589\u3058\u308b = JS \u30e1\u30e2\u30ea\u6d88\u5931\u3002localStorage \u306f\u6b8b\u308b\u306e\u3067\u5225\u306e\u8aad\u307f\u53d6\u308a\u3067\u78ba\u8a8d\u3002
    const plan = planSessionTeardown('closeTab')
    expect(plan.keepAutosave).toBe(true)
    expect(restoreOwnedStrokes(USER)).toBe(3)
  })

  it('(b) \u30d6\u30e9\u30a6\u30b6\u304c\u843d\u3061\u3066\u3082 \u672c\u4eba\u306e localStorage \u304b\u3089\u5fa9\u5143\u3067\u304d\u308b', () => {
    writeAutosave(2)
    const plan = planSessionTeardown('crash')
    expect(plan.keepAutosave).toBe(true)
    expect(restoreOwnedStrokes(USER)).toBe(2)
  })

  it('(c) \u901a\u4fe1\u304c\u5207\u308c\u3066\u3082 \u672c\u4eba\u306e\u9000\u907f\u884c\u304c\u53d6\u308a\u51fa\u305b\u3001\u518d\u9001\u7528\u306e\u5197\u7b49\u30ad\u30fc\u304c\u5b89\u5b9a', () => {
    // \u30e9\u30ea\u30fc\u78ba\u5b9a\u6642\u306b IndexedDB \u3078\u9000\u907f\u3055\u308c\u305f\u884c (owned) \u306e\u5f62\u3002
    const queued = {
      ownerUserId: USER,
      matchId: MATCH,
      setId: SET,
      rallyNum: 5,
      payload: {},
      queued_at: '2026-11-05T00:00:00Z',
    }
    // \u672c\u4eba\u30fb\u540c\u3058\u8a66\u5408\u306a\u3089\u53d6\u308a\u51fa\u305b\u308b (\u901a\u4fe1\u5fa9\u5e30\u5f8c\u306b useOfflineSync \u304c\u518d\u9001)\u3002
    expect(pendingRallyBelongsTo(queued, USER, MATCH)).toBe(true)
    // \u5225\u30e6\u30fc\u30b6\u30fc\u306b\u306f\u6e21\u3055\u306a\u3044\u3002
    expect(pendingRallyBelongsTo(queued, USER + 1, MATCH)).toBe(false)
    // \u518d\u9001\u306e\u5197\u7b49\u30ad\u30fc\u306f match/set/rally \u304b\u3089\u5b89\u5b9a\u7684\u306b\u6c7a\u307e\u308b (\u4e8c\u91cd\u4fdd\u5b58\u3057\u306a\u3044)\u3002
    expect(offlineStrokeIdempotencyKey(USER, MATCH, SET, 5)).toBe('offline-7-12-3-5')
  })

  it('(d) \u610f\u56f3\u3057\u306a\u3044\u5931\u52b9 (401/403) \u306e\u5f8c\u3082 \u672c\u4eba\u306e\u4e00\u6642\u4fdd\u5b58\u304c\u6b8b\u308a\u5fa9\u5143\u3067\u304d\u308b', () => {
    writeAutosave(4)
    const plan = planSessionTeardown('tokenExpired')
    // \u5931\u52b9\u524d\u306b flush \u3057\u3001\u4e00\u6642\u4fdd\u5b58\u3092\u6b8b\u3059\u5224\u65ad\u3002
    expect(plan.flushAutosaveBeforeTeardown).toBe(true)
    expect(plan.keepAutosave).toBe(true)
    // keepAutosave \u306a\u306e\u3067 \u5fa9\u5143\u53ef\u80fd\u306a\u307e\u307e\u3002
    expect(restoreOwnedStrokes(USER)).toBe(4)
  })

  it('\u5171\u6709\u7aef\u672b: \u5225\u30e6\u30fc\u30b6\u30fc\u306b\u306f\u524d\u306e\u4eba\u306e\u4e00\u6642\u4fdd\u5b58\u3092\u5fa9\u5143\u5019\u88dc\u306b\u3057\u306a\u3044', () => {
    writeAutosave(3)
    // \u5225\u306e\u5229\u7528\u8005 (userId \u9055\u3044) \u304b\u3089\u306f\u5fa9\u5143\u3067\u304d\u306a\u3044\u3002
    expect(restoreOwnedStrokes(USER + 99)).toBeNull()
  })

  it('\u660e\u793a\u30ed\u30b0\u30a2\u30a6\u30c8\u5f8c\u306f keepAutosave=false \u3067\u6d88\u3059\u3079\u304d (\u304c prefix \u306f\u5171\u901a)', () => {
    const key = writeAutosave(3)
    expect(key.startsWith(AUTOSAVE_PREFIX)).toBe(true)
    expect(planSessionTeardown('explicitLogout').keepAutosave).toBe(false)
  })
})
