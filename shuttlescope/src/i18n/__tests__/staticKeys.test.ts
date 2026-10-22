/**
 * 翻訳キーの取りこぼしを CI で止める。
 *
 * `t('a.b')` のように文字列リテラルで書かれたキーが ja.json / en.json に無いと、
 * 画面に `a.b` という生キーがそのまま出る (defaultValue を付けた呼び出しも、
 * 辞書に無ければ英語側や別言語で同じ穴になるので対象にする)。
 * カメラ送信・遠隔ビューワ・招待受諾のように現地で素早く使う画面ほど影響が大きい。
 *
 * 動的キー (`t(\`a.${x}\`)` など) は静的に決まらないので対象外。
 * コメント行に書かれた `t('...')` は数えない。
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync } from 'fs'
import { join, resolve, relative } from 'path'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

const SRC_DIR = resolve(__dirname, '..', '..')
// `i18n.t(` や `obj.t(` は除き、素の t( だけを拾う
const STATIC_KEY = /(?<![.\w])t\(\s*'([A-Za-z0-9_]+(?:\.[A-Za-z0-9_-]+)+)'/g
const PLURAL_SUFFIXES = ['_zero', '_one', '_two', '_few', '_many', '_other']

function listSources(dir: string): string[] {
  const out: string[] = []
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, ent.name)
    if (ent.isDirectory()) {
      if (ent.name === '__tests__' || ent.name === 'node_modules') continue
      out.push(...listSources(full))
    } else if (/\.(ts|tsx)$/.test(ent.name) && !ent.name.endsWith('.d.ts')) {
      out.push(full)
    }
  }
  return out
}

function lookup(dict: unknown, key: string): unknown {
  if (dict && typeof dict === 'object' && key in (dict as Record<string, unknown>)) {
    return (dict as Record<string, unknown>)[key]
  }
  return key.split('.').reduce<unknown>(
    (o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined),
    dict,
  )
}

function hasKey(dict: unknown, key: string): boolean {
  if (typeof lookup(dict, key) === 'string') return true
  return PLURAL_SUFFIXES.some((s) => typeof lookup(dict, key + s) === 'string')
}

function collectStaticKeys(): { keys: Map<string, string>; files: Set<string> } {
  const keys = new Map<string, string>() // key -> 最初に使っているファイル
  const files = new Set<string>() // 静的キーを1つでも使っているファイル
  for (const file of listSources(SRC_DIR)) {
    const lines = readFileSync(file, 'utf-8').split(/\r?\n/)
    for (const line of lines) {
      const head = line.trimStart()
      if (head.startsWith('//') || head.startsWith('*') || head.startsWith('/*')) continue
      for (const m of line.matchAll(STATIC_KEY)) {
        const rel = relative(SRC_DIR, file).replace(/\\/g, '/')
        files.add(rel)
        if (!keys.has(m[1])) keys.set(m[1], rel)
      }
    }
  }
  return { keys, files }
}

describe('t() の静的キーが辞書に存在する', () => {
  const { keys, files } = collectStaticKeys()

  it('走査が空振りしていない', () => {
    expect(keys.size).toBeGreaterThan(500)
  })

  it('ja.json に無いキーが無い', () => {
    const missing = [...keys].filter(([k]) => !hasKey(ja, k)).map(([k, f]) => `${k} (${f})`)
    expect(missing).toEqual([])
  })

  it('en.json に無いキーが無い', () => {
    const missing = [...keys].filter(([k]) => !hasKey(en, k)).map(([k, f]) => `${k} (${f})`)
    expect(missing).toEqual([])
  })

  it('カメラ送信・ビューワ・招待受諾の主要キーを走査が拾っている', () => {
    expect(files.has('pages/CameraSenderPage.tsx')).toBe(true)
    expect(files.has('pages/ViewerPage.tsx')).toBe(true)
    expect(files.has('pages/InvitationAcceptPage.tsx')).toBe(true)
  })
})
