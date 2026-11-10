/**
 * (2) AnnotatorPage と LiveInputPage が入力経路から mid-rally autosave を実際に呼ぶことを確かめる。
 *
 * 両ページは巨大で実レンダーは重いため、ソースを読んで
 * useMidRallyAutosave を import して呼んでいることを検証する (配線が落ちたら気づく)。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

function readPage(rel: string): string {
  return readFileSync(resolve(__dirname, '..', rel), 'utf-8')
}

describe('mid-rally autosave wiring', () => {
  it('AnnotatorPage が useMidRallyAutosave を import して呼ぶ', () => {
    const src = readPage('AnnotatorPage.tsx')
    expect(src).toMatch(/from '@\/utils\/midRallyAutosave'/)
    expect(src).toMatch(/useMidRallyAutosave\(/)
  })

  it('LiveInputPage が useMidRallyAutosave を import して呼ぶ', () => {
    const src = readPage('LiveInputPage.tsx')
    expect(src).toMatch(/from '@\/utils\/midRallyAutosave'/)
    expect(src).toMatch(/useMidRallyAutosave\(/)
  })
})
