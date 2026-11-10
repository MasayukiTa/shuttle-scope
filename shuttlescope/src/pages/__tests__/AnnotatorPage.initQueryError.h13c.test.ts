/**
 * #646 の回帰テスト。
 *
 * 通常 Annotator (`/annotator/:matchId`) は初期化に annotation-state と
 * sets の 2 つの query を使うが、以前は `data` だけを受け isError を
 * 無視していたため、query が通信断・401/403・5xx で失敗すると
 * initError に入らず「読み込み中…」のまま永続停止していた。
 *
 * AnnotatorPage 全体の mount は重く環境依存が大きいため、#784 と同じく
 * source を読み、両 query の失敗が initError へ配線され再試行で refetch
 * されることを静的に固定する。配線を外すと落ちる。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(here, '../AnnotatorPage.tsx'), 'utf-8')

describe('AnnotatorPage の query 失敗 -> initError 配線 (#646)', () => {
  it('annotation-state / sets query の isError と error を受け取っている', () => {
    expect(pageSource).toMatch(/isError:\s*annotationStateIsError/)
    expect(pageSource).toMatch(/error:\s*annotationStateError/)
    expect(pageSource).toMatch(/isError:\s*setsIsError/)
    expect(pageSource).toMatch(/error:\s*setsError/)
  })

  it('query 失敗を setInitError へ入れる effect がある', () => {
    expect(pageSource).toMatch(/if \(!annotationStateIsError && !setsIsError\) return/)
    expect(pageSource).toMatch(/annotator\.ui\.load_failed/)
  })

  it('再試行ボタンが失敗した query を refetch する', () => {
    expect(pageSource).toMatch(/if \(annotationStateIsError\) void refetchAnnotationState\(\)/)
    expect(pageSource).toMatch(/if \(setsIsError\) void refetchSets\(\)/)
  })
})
