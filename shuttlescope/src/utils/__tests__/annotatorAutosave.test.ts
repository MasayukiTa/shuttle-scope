import { describe, expect, it } from 'vitest'
import {
  AUTOSAVE_PREFIX,
  buildAutosaveKey,
  clearAutosaveStorage,
  isAutosaveOwnedBy,
  listAutosaveKeys,
} from '../annotatorAutosave'

function fakeStorage(initial: Record<string, string>) {
  const data = new Map(Object.entries(initial))
  return {
    get length() {
      return data.size
    },
    key: (i: number) => Array.from(data.keys())[i] ?? null,
    removeItem: (k: string) => {
      data.delete(k)
    },
    has: (k: string) => data.has(k),
  }
}

describe('buildAutosaveKey', () => {
  it('puts the user id between the prefix and the match id', () => {
    expect(buildAutosaveKey('12', 7)).toBe(`${AUTOSAVE_PREFIX}7.12`)
    expect(buildAutosaveKey(12, 7)).toBe(`${AUTOSAVE_PREFIX}7.12`)
  })

  it('gives different keys to different users on the same match', () => {
    expect(buildAutosaveKey('12', 7)).not.toBe(buildAutosaveKey('12', 8))
  })

  it('returns null when the match or the user is unknown', () => {
    expect(buildAutosaveKey(null, 7)).toBeNull()
    expect(buildAutosaveKey('', 7)).toBeNull()
    expect(buildAutosaveKey('12', null)).toBeNull()
    expect(buildAutosaveKey('12', undefined)).toBeNull()
    expect(buildAutosaveKey('12', 0)).toBeNull()
    expect(buildAutosaveKey('12', -3)).toBeNull()
  })
})

describe('isAutosaveOwnedBy', () => {
  it('accepts only the recorded owner', () => {
    expect(isAutosaveOwnedBy({ ownerUserId: 7 }, 7)).toBe(true)
    expect(isAutosaveOwnedBy({ ownerUserId: 7 }, 8)).toBe(false)
  })

  it('rejects saves with no recorded owner and unknown users', () => {
    expect(isAutosaveOwnedBy({}, 7)).toBe(false)
    expect(isAutosaveOwnedBy({ ownerUserId: null }, 7)).toBe(false)
    expect(isAutosaveOwnedBy({ ownerUserId: 7 }, null)).toBe(false)
    expect(isAutosaveOwnedBy(null, 7)).toBe(false)
  })
})

describe('clearAutosaveStorage', () => {
  it('removes every autosave key, old and new format, and nothing else', () => {
    const s = fakeStorage({
      [`${AUTOSAVE_PREFIX}7.12`]: '{}',
      [`${AUTOSAVE_PREFIX}12`]: '{}',
      'shuttlescope.viewpoint.12': 'x',
      other: 'y',
    })
    expect(listAutosaveKeys(s)).toHaveLength(2)
    expect(clearAutosaveStorage(s)).toBe(2)
    expect(s.has(`${AUTOSAVE_PREFIX}7.12`)).toBe(false)
    expect(s.has(`${AUTOSAVE_PREFIX}12`)).toBe(false)
    expect(s.has('shuttlescope.viewpoint.12')).toBe(true)
    expect(s.has('other')).toBe(true)
  })

  it('returns 0 when there is nothing to remove', () => {
    expect(clearAutosaveStorage(fakeStorage({ other: 'y' }))).toBe(0)
  })
})
