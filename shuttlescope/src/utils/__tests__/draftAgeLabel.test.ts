import { beforeEach, describe, expect, it } from 'vitest'
import {
  buildAutosaveKey,
  resolveDraftFirstInputAt,
  draftAgeMinutes,
} from '../annotatorAutosave'

/**
 * \u89b3\u5bdf (2026-11-10 muse \u5b9f\u6a5f):
 *   \u30e9\u30ea\u30fc\u5165\u529b\u9014\u4e2d (11:04) \u2192 \u7121\u64cd\u4f5c\u3067\u671f\u9650\u5207\u308c \u2192 \u518d\u30ed\u30b0\u30a4\u30f3 (11:29) \u3067
 *   \u300c\u524d\u56de\u306e\u672a\u4fdd\u5b58\u30c7\u30fc\u30bf\u304c\u898b\u3064\u304b\u308a\u307e\u3057\u305f\uff081\u672c\u78ba\u5b9a\u3001\u7d04 0 \u5206\u524d\uff09\u300d\u3068\u51fa\u305f\u3002
 *   \u5143\u306e\u5165\u529b\u304b\u3089\u7d04 25 \u5206\u305f\u3063\u3066\u3044\u308b\u306e\u306b\u300c\u7d04 0 \u5206\u524d\u300d\u306f\u8aa4\u308a\u3002
 *   \u539f\u56e0: savedAt \u304c flush (PR 243) \u3084 IndexedDB \u9000\u907f (PR 250) \u306e\u305f\u3073\u306b now \u3078\u66f4\u65b0\u3055\u308c\u308b\u305f\u3081\u3002
 *
 * \u4fee\u6b63: firstInputAt \u3092\u5225\u306b\u6301\u3061\u3001flush/\u5fa9\u5143\u3067\u306f\u66f4\u65b0\u3057\u306a\u3044\u3002
 *   \u300c\u7d04 N \u5206\u524d\u300d\u306f firstInputAt \u304b\u3089\u6570\u3048\u308b\u3002
 */

const USER = 7
const MATCH = 12
const SET = 3
const RALLY = 28

interface Draft {
  setId: number
  rallyNum: number
  strokes: Array<Record<string, unknown>>
  savedAt: number
  firstInputAt: number
  ownerUserId: number
}

// saveAutosaveNow \u3068\u540c\u3058\u5f62\u3067 localStorage \u3078\u66f8\u304f\u3002firstInputAt \u306f\u524d\u56de\u5024\u3092\u5f15\u304d\u7d99\u3050\u3002
function saveNow(key: string, strokesCount: number, now: number): void {
  let prevFirstInputAt: number | undefined
  const prevRaw = localStorage.getItem(key)
  if (prevRaw) {
    const prev = JSON.parse(prevRaw) as { firstInputAt?: number }
    if (typeof prev.firstInputAt === 'number') prevFirstInputAt = prev.firstInputAt
  }
  const data: Draft = {
    setId: SET,
    rallyNum: RALLY,
    strokes: Array.from({ length: strokesCount }, (_, i) => ({ shot_type: 'clear', seq: i })),
    savedAt: now,
    firstInputAt: resolveDraftFirstInputAt(prevFirstInputAt, now),
    ownerUserId: USER,
  }
  localStorage.setItem(key, JSON.stringify(data))
}

describe('\u4e0b\u66f8\u304d\u306e\u300c\u7d04 N \u5206\u524d\u300d\u306f\u6700\u521d\u306e\u5165\u529b\u6642\u523b\u304b\u3089\u6570\u3048\u308b', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('\u5165\u529b \u2192 flush \u3092 2 \u56de \u2192 \u5fa9\u5143: \u300c\u7d04 N \u5206\u524d\u300d\u304c\u5143\u306e\u5165\u529b\u6642\u523b\u304b\u3089\u8a08\u7b97\u3055\u308c\u308b', () => {
    const key = buildAutosaveKey(MATCH, USER)
    expect(key).toBeTruthy()
    const k = key as string

    const t0 = Date.UTC(2026, 10, 10, 11, 4, 0) // \u6700\u521d\u306e\u5165\u529b (11:04)
    saveNow(k, 1, t0)

    // flush 1 \u56de\u76ee (11:09): savedAt \u306f\u66f4\u65b0\u3055\u308c\u308b\u304c firstInputAt \u306f\u4e0d\u5909
    const tFlush1 = t0 + 5 * 60000
    saveNow(k, 1, tFlush1)

    // flush 2 \u56de\u76ee (\u671f\u9650\u5207\u308c\u76f4\u524d 11:29): \u540c\u3058\u304f savedAt \u3060\u3051\u66f4\u65b0
    const tFlush2 = t0 + 25 * 60000
    saveNow(k, 1, tFlush2)

    const raw = localStorage.getItem(k)
    expect(raw).toBeTruthy()
    const saved = JSON.parse(raw as string) as Draft

    // firstInputAt \u306f\u6700\u521d\u306e\u5165\u529b\u6642\u523b\u306e\u307e\u307e
    expect(saved.firstInputAt).toBe(t0)
    // savedAt \u306f\u6700\u5f8c\u306e\u66f8\u304d\u51fa\u3057\u6642\u523b
    expect(saved.savedAt).toBe(tFlush2)

    // \u5fa9\u5143\u6642\u523b (11:29) \u304b\u3089\u306e\u300c\u7d04 N \u5206\u524d\u300d\u306f firstInputAt \u57fa\u6e96\u3067 25 \u5206
    const nowRestore = t0 + 25 * 60000
    expect(draftAgeMinutes(saved, nowRestore)).toBe(25)
    // savedAt \u3092\u4f7f\u3063\u3066\u3044\u305f\u3089 0 \u5206\u306b\u306a\u3063\u3066\u3057\u307e\u3046 (\u30d0\u30b0\u306e\u518d\u73fe\u56de\u907f\u306e\u78ba\u8a8d)
    expect(Math.round((nowRestore - saved.savedAt) / 60000)).toBe(0)
  })

  it('firstInputAt \u304c\u7121\u3044\u65e7\u5f62\u5f0f\u306e\u4e0b\u66f8\u304d\u306f savedAt \u306b\u30d5\u30a9\u30fc\u30eb\u30d0\u30c3\u30af\u3059\u308b', () => {
    const savedAt = Date.UTC(2026, 10, 10, 11, 4, 0)
    const legacy = { savedAt } // firstInputAt \u7121\u3057
    const now = savedAt + 10 * 60000
    expect(draftAgeMinutes(legacy, now)).toBe(10)
  })

  it('resolveDraftFirstInputAt: \u524d\u56de\u5024\u304c\u3042\u308c\u3070\u305d\u308c\u3001\u7121\u3051\u308c\u3070 now', () => {
    expect(resolveDraftFirstInputAt(1000, 5000)).toBe(1000)
    expect(resolveDraftFirstInputAt(undefined, 5000)).toBe(5000)
    expect(resolveDraftFirstInputAt(null, 5000)).toBe(5000)
    expect(resolveDraftFirstInputAt(Number.NaN, 5000)).toBe(5000)
  })
})
