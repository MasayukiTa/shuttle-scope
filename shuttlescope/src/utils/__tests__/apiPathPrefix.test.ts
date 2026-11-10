/**
 * 共通 API クライアントの BASE_URL は既に `/api` を含む。呼び出し側が
 * `apiGet('/api/...')` と書くと実 URL が `/api/api/...` になり 404 になる。
 * モバイル CV で 4 か所起きたので、ソース全体で二重 prefix を禁止する。
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

const SRC_DIR = resolve(__dirname, '..', '..')
const DOUBLE_PREFIX = /\bapi(?:Get|Post|Put|Patch|Delete)\s*(?:<[^()]*>)?\s*\(\s*[`'"]\/api\//

function listSources(dir: string): string[] {
  const out: string[] = []
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, ent.name)
    if (ent.isDirectory()) {
      if (ent.name === 'node_modules') continue
      out.push(...listSources(full))
    } else if (/\.(ts|tsx)$/.test(ent.name) && !/\.test\.tsx?$/.test(ent.name)) {
      out.push(full)
    }
  }
  return out
}

describe('api path prefix', () => {
  it('never passes a path that already starts with /api to the api client', () => {
    const offenders: string[] = []
    for (const file of listSources(SRC_DIR)) {
      const lines = readFileSync(file, 'utf-8').split(/\r?\n/)
      lines.forEach((line, i) => {
        if (DOUBLE_PREFIX.test(line)) offenders.push(`${file}:${i + 1}`)
      })
    }
    expect(offenders).toEqual([])
  })
})
