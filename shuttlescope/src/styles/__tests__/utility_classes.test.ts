/**
 * .num-cell / .cell-name-clip / button[data-tile] の CSS 規約テスト。
 *
 * jsdom は @media クエリと :is/@supports を完全には評価しないが、
 * クラス本体ルールが globals.css に存在する事を構造的に確認する。
 *
 * これらクラス名はリポジトリ全体で大量に使われており、誤って削除すると
 * 解析テーブル全体の桁揃え / 名前 truncate が一斉崩壊する。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const cssPath = resolve(__dirname, '..', 'globals.css')
const css = readFileSync(cssPath, 'utf-8')

describe('globals.css utility classes', () => {
  it('.num-cell が tabular-nums + nowrap を提供する', () => {
    // セレクタ + プロパティが同一ブロックに入っていることを正規表現で確認
    const block = css.match(/\.num-cell\s*\{[^}]+\}/)
    expect(block).toBeTruthy()
    expect(block![0]).toMatch(/font-variant-numeric:\s*tabular-nums/)
    expect(block![0]).toMatch(/white-space:\s*nowrap/)
  })

  it('.cell-name-clip が xs/md/lg で max-width を切替える', () => {
    // 基本 (xs) ブロック
    const base = css.match(/\.cell-name-clip\s*\{[^}]+\}/)
    expect(base).toBeTruthy()
    expect(base![0]).toMatch(/max-width:\s*14ch/)
    expect(base![0]).toMatch(/text-overflow:\s*ellipsis/)
    // md (>= 768) と lg (>= 1024) のメディアクエリで上書きされている
    expect(css).toMatch(/@media\s*\(min-width:\s*768px\)\s*\{[^}]*\.cell-name-clip\s*\{[^}]*max-width:\s*22ch/)
    expect(css).toMatch(/@media\s*\(min-width:\s*1024px\)\s*\{[^}]*\.cell-name-clip\s*\{[^}]*max-width:\s*28ch/)
  })

  it('button[data-tile="true"] が iOS フォント耐性ルールを保持している', () => {
    const block = css.match(/button\[data-tile="true"\]\s*\{[^}]+\}/)
    expect(block).toBeTruthy()
    expect(block![0]).toMatch(/font-size:\s*16px\s*!important/)
    expect(block![0]).toMatch(/min-height:\s*44px/)
    expect(block![0]).toMatch(/touch-action:\s*manipulation/)
  })

  it('button[data-tile="hit-zone"] は 44x44 を保証する (WCAG 2.5.5)', () => {
    const block = css.match(/button\[data-tile="hit-zone"\]\s*\{[^}]+\}/)
    expect(block).toBeTruthy()
    expect(block![0]).toMatch(/min-width:\s*44px/)
    expect(block![0]).toMatch(/min-height:\s*44px/)
  })
})
