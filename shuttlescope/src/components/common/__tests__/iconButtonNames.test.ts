/**
 * アイコンだけの <button> にアクセシブル名があることを CI で保証する。
 *
 * MIcon は既定で aria-hidden="true" なので、`<button><MIcon/></button>` は
 * 支援技術上「名前の無いボタン」になる (監査 #566)。aria-label / title /
 * aria-labelledby のいずれかを付けるか、IconButton を使う。
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync } from 'fs'
import { join, resolve, relative } from 'path'

const SRC_DIR = resolve(__dirname, '..', '..', '..')

function listTsx(dir: string): string[] {
  const out: string[] = []
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, ent.name)
    if (ent.isDirectory()) {
      if (ent.name === '__tests__' || ent.name === 'node_modules') continue
      out.push(...listTsx(full))
    } else if (ent.name.endsWith('.tsx')) {
      out.push(full)
    }
  }
  return out
}

/** `<button` の開始タグ終端 ('>' / 波括弧と引用符の外) の位置。見つからなければ -1 */
export function openTagEnd(s: string, from: number): number {
  let depth = 0
  let quote: string | null = null
  for (let k = from; k < s.length; k++) {
    const c = s[k]
    if (quote) {
      if (c === quote && s[k - 1] !== '\\') quote = null
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; continue }
    if (c === '{') depth++
    else if (c === '}') depth--
    else if (c === '>' && depth === 0 && s[k - 1] !== '=') return k
  }
  return -1
}

/** アイコンだけで名前の無い <button> の位置 (file:line) を返す */
export function findUnnamedIconButtons(source: string): number[] {
  const lines: number[] = []
  let idx = 0
  while ((idx = source.indexOf('<button', idx)) !== -1) {
    const start = idx
    idx += 7
    if (!/[\s>]/.test(source[idx] ?? '')) continue
    const end = openTagEnd(source, idx)
    if (end < 0) continue
    const open = source.slice(start, end + 1)
    if (open.endsWith('/>')) continue
    const close = source.indexOf('</button>', end)
    if (close < 0) continue
    const inner = source.slice(end + 1, close)
    if (!/<MIcon\b/.test(inner)) continue
    // MIcon と、アイコンを切り替えるだけの `{cond ? <A/> : <B/>}` / `{cond && <A/>}` を除いて何も残らなければ icon-only
    let rest = inner.replace(/<MIcon\b[^>]*?\/>/g, '')
    rest = rest.replace(/\{[^{}]*\?\s*:\s*\}/g, '').replace(/\{[^{}]*&&\s*\}/g, '')
    if (rest.trim() !== '') continue
    if (/aria-label|title=|aria-labelledby/.test(open)) continue
    if (/ariaLabel/.test(inner)) continue
    lines.push(source.slice(0, start).split('\n').length)
  }
  return lines
}

describe('アイコン専用ボタンのアクセシブル名', () => {
  it('検出器が名前の無いアイコンボタンを見つける', () => {
    const bad = `<button onClick={() => go()}>\n  <MIcon name="close" size={12} />\n</button>`
    expect(findUnnamedIconButtons(bad)).toEqual([1])
    const toggled = `<button onClick={f}>{on ? <MIcon name="a" /> : <MIcon name="b" />}</button>`
    expect(findUnnamedIconButtons(toggled)).toEqual([1])
  })

  it('名前または文言のあるボタンは対象にしない', () => {
    expect(findUnnamedIconButtons(`<button aria-label="x"><MIcon name="close" /></button>`)).toEqual([])
    expect(findUnnamedIconButtons(`<button title={t('a.b')}><MIcon name="close" /></button>`)).toEqual([])
    expect(findUnnamedIconButtons(`<button><MIcon name="close" />{t('a.b')}</button>`)).toEqual([])
  })

  it('src 配下に名前の無いアイコン専用ボタンが無い', () => {
    const offenders: string[] = []
    for (const file of listTsx(SRC_DIR)) {
      const src = readFileSync(file, 'utf-8')
      for (const line of findUnnamedIconButtons(src)) {
        offenders.push(`${relative(SRC_DIR, file).replace(/\\/g, '/')}:${line}`)
      }
    }
    expect(offenders).toEqual([])
  })
})
