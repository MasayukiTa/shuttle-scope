/**
 * Regression guard for the mobile table leak.
 *
 * In src/styles/globals.css section (3), the `@media (max-width: 767px)` rule
 * `table:not(.scroll-shell table) { display: block }` used to win on specificity
 * over Tailwind's `.hidden { display: none }`, so a desktop-only table marked
 * `hidden md:table` (e.g. MatchListPage) was forced visible as a block on phones
 * and showed below the card list. The fix excludes intentionally hidden tables
 * (`.hidden` / `[hidden]`) from that block rule.
 *
 * This test reads globals.css on disk and asserts the mobile table rule still
 * carries the `.hidden` / `[hidden]` exclusion, so the leak cannot regress.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const CSS = readFileSync(
  resolve(__dirname, '..', 'globals.css'),
  'utf-8',
)

/** Extract the body of the first `@media (max-width: 767px)` block that styles a raw table. */
function mobileTableBlock(): string {
  // All the table block-化 rules live inside @media (max-width: 767px).
  const idx = CSS.indexOf('table:not(.scroll-shell table)')
  expect(idx).toBeGreaterThan(-1)
  return CSS.slice(idx, idx + 400)
}

describe('globals.css mobile table rule (hidden-table leak guard)', () => {
  it('block-化 rule targets raw tables', () => {
    expect(CSS).toContain('table:not(.scroll-shell table)')
  })

  it('excludes .hidden tables so Tailwind `.hidden { display: none }` is not overridden', () => {
    const block = mobileTableBlock()
    // The selector that sets `display: block` must also exclude `.hidden`.
    expect(block).toContain('table:not(.scroll-shell table):not(.hidden)')
  })

  it('also excludes [hidden] tables', () => {
    const block = mobileTableBlock()
    expect(block).toContain(':not([hidden])')
  })

  it('every table block-化 selector in globals.css carries the .hidden exclusion', () => {
    // Match selectors of the form `table:not(.scroll-shell table)...` that are
    // immediately followed (same selector list) by a block/table display switch.
    const selectors = CSS.match(/table:not\(\.scroll-shell table\)[^\{,]*/g) ?? []
    expect(selectors.length).toBeGreaterThan(0)
    for (const sel of selectors) {
      expect(sel).toContain(':not(.hidden)')
      expect(sel).toContain(':not([hidden])')
    }
  })
})
