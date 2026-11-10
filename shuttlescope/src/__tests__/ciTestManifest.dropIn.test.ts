/**
 * Guard for the split CI test manifest (方針C, drop-in edition).
 *
 * The legacy registry scripts/ci_test_manifest.txt required every PR to append
 * one line to its tail, so concurrent PRs collided on that single line every
 * time. New tests now register themselves in their own file under
 * scripts/ci_test_manifest.d/<name>.txt (one file, one line), and
 * scripts/check_ci_test_manifest.py reads BOTH the legacy file and every *.txt
 * in the drop-in directory, de-duplicating entries.
 *
 * This test reads the real files on disk and asserts that lines from BOTH
 * sources end up in the merged, de-duplicated entry set.
 */
import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

const SCRIPTS_DIR = resolve(__dirname, '..', '..', 'scripts')
const LEGACY_MANIFEST = join(SCRIPTS_DIR, 'ci_test_manifest.txt')
const MANIFEST_DIR = join(SCRIPTS_DIR, 'ci_test_manifest.d')

/** Non-empty, non-comment lines from one manifest file. */
function readManifestFile(path: string): string[] {
  return readFileSync(path, 'utf-8')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0 && !l.startsWith('#'))
}

/**
 * Mirror of check_ci_test_manifest.py#_read_manifest: legacy file first, then
 * every *.txt in the drop-in dir sorted by name, de-duplicated, order-preserving.
 */
function readMergedManifest(): string[] {
  const sources: string[] = []
  if (existsSync(LEGACY_MANIFEST)) sources.push(LEGACY_MANIFEST)
  if (existsSync(MANIFEST_DIR)) {
    for (const name of readdirSync(MANIFEST_DIR).filter((n) => n.endsWith('.txt')).sort()) {
      sources.push(join(MANIFEST_DIR, name))
    }
  }
  const seen = new Set<string>()
  const entries: string[] = []
  for (const src of sources) {
    for (const line of readManifestFile(src)) {
      if (seen.has(line)) continue
      seen.add(line)
      entries.push(line)
    }
  }
  return entries
}

describe('CI test manifest (legacy file + drop-in directory)', () => {
  it('has a drop-in directory with at least one *.txt entry file', () => {
    expect(existsSync(MANIFEST_DIR)).toBe(true)
    const txts = readdirSync(MANIFEST_DIR).filter((n) => n.endsWith('.txt'))
    expect(txts.length).toBeGreaterThan(0)
  })

  it('reads entries from the legacy ci_test_manifest.txt', () => {
    const legacy = readManifestFile(LEGACY_MANIFEST)
    expect(legacy.length).toBeGreaterThan(0)
    expect(readMergedManifest()).toEqual(expect.arrayContaining(legacy))
  })

  it('reads entries from the drop-in directory', () => {
    const dropInLines: string[] = []
    for (const name of readdirSync(MANIFEST_DIR).filter((n) => n.endsWith('.txt'))) {
      dropInLines.push(...readManifestFile(join(MANIFEST_DIR, name)))
    }
    expect(dropInLines.length).toBeGreaterThan(0)
    expect(readMergedManifest()).toEqual(expect.arrayContaining(dropInLines))
  })

  it('merges BOTH sources: a legacy line and a drop-in line coexist', () => {
    const merged = readMergedManifest()
    const legacy = readManifestFile(LEGACY_MANIFEST)
    // This very test registers itself via the drop-in directory.
    const selfEntry = 'src/__tests__/ciTestManifest.dropIn.test.ts'
    expect(merged).toContain(legacy[0])
    expect(merged).toContain(selfEntry)
  })

  it('collapses duplicate entries to a single occurrence', () => {
    const merged = readMergedManifest()
    const unique = new Set(merged)
    expect(merged.length).toBe(unique.size)
  })
})
