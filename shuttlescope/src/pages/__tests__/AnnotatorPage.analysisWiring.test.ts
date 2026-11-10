/**
 * #784 の配線回帰テスト。
 *
 * AnalysisModePanel は `recentRallyResults` prop を受けて直近ラリーの勝敗を描くが、
 * desktop / mobile 双方の AnnotatorPage 呼び出しがこの prop を渡し忘れると、既定値
 * `[]` で常に「データなし」になり、実装済みに見えて dead display になる。
 *
 * AnnotatorPage 全体の mount は重く環境依存が大きいため、ここでは source を読み、
 * AnalysisModePanel の各呼び出しが recentRallyResults を store から配線していること
 * を静的に固定する。prop を外すと件数が合わず落ちる。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(here, '../AnnotatorPage.tsx'), 'utf-8')

describe('AnnotatorPage の AnalysisModePanel 配線 (#784)', () => {
  it('AnalysisModePanel の呼び出し回数と同数だけ recentRallyResults を配線している', () => {
    const callCount = (pageSource.match(/<AnalysisModePanel\b/g) ?? []).length
    const wiredCount = (
      pageSource.match(/recentRallyResults=\{store\.recentRallyResults\}/g) ?? []
    ).length
    expect(callCount).toBeGreaterThanOrEqual(2)
    expect(wiredCount).toBe(callCount)
  })
})
