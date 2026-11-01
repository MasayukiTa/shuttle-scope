/**
 * Audit #493: Camera / Viewer join forms associate each visible label with its
 * input, so the accessible name comes from the label (not the placeholder).
 *
 * The fix adds matching htmlFor / id pairs to every label+input in the join
 * forms of CameraSenderPage and ViewerPage. Placeholders stay as input hints
 * only and no longer stand in for the accessible name.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const SRC = resolve(__dirname, '..', '..')

function labelHasFor(src: string, forId: string): boolean {
  return new RegExp(`<label htmlFor="${forId}"`).test(src)
}
function inputHasId(src: string, id: string): boolean {
  return new RegExp(`id="${id}"`).test(src)
}

describe('#493 CameraSenderPage join form labels are associated', () => {
  const src = readFileSync(resolve(SRC, 'pages', 'CameraSenderPage.tsx'), 'utf-8')
  for (const id of ['cs-join-code', 'cs-join-password', 'cs-join-device']) {
    it(`label and input share id ${id}`, () => {
      expect(labelHasFor(src, id)).toBe(true)
      expect(inputHasId(src, id)).toBe(true)
    })
  }
})

describe('#493 ViewerPage join form labels are associated', () => {
  const src = readFileSync(resolve(SRC, 'pages', 'ViewerPage.tsx'), 'utf-8')
  for (const id of ['viewer-join-code', 'viewer-join-password', 'viewer-join-name']) {
    it(`label and input share id ${id}`, () => {
      expect(labelHasFor(src, id)).toBe(true)
      expect(inputHasId(src, id)).toBe(true)
    })
  }
})
