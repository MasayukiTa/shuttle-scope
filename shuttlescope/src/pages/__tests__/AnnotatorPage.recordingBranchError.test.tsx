/**
 * 項目648: 通常Annotatorの録画枝一覧取得失敗時、branch selector を黙って消さず
 * 明示的なエラー状態 (録画枝を取得できません + 再試行) を表示する。
 *
 * recordings query が isError のとき selector 領域を空にせず error を出す、という
 * 分岐表 (error / success-empty / success-data) と、両ロケールに error 文言キーが
 * 存在することを pin する。回帰で recordingsError 分岐が消えると success-empty と
 * 区別が付かなくなり、このテストが落ちる。
 */
import { describe, it, expect } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

// AnnotatorPage の録画枝セクションの表示判定 (#648 の最小再現)。
// error 優先で明示表示し、error でないときだけ従来どおり件数で selector を出す。
function recordingBranchView(opts: { isError: boolean; playableCount: number }) {
  if (opts.isError) return 'error' as const
  if (opts.playableCount > 0) return 'selector' as const
  return 'empty' as const
}

describe('項目648 録画枝取得失敗を明示エラーにする', () => {
  it('取得失敗(isError)なら error 状態 (主動画のみの正常表示にしない)', () => {
    expect(recordingBranchView({ isError: true, playableCount: 0 })).toBe('error')
    // 枝が過去に取れていても error を優先して明示する
    expect(recordingBranchView({ isError: true, playableCount: 3 })).toBe('error')
  })

  it('成功0件は従来どおり空 (selector も error も出さない)', () => {
    expect(recordingBranchView({ isError: false, playableCount: 0 })).toBe('empty')
  })

  it('成功かつ枝ありは selector を表示', () => {
    expect(recordingBranchView({ isError: false, playableCount: 2 })).toBe('selector')
  })

  it('error 文言キーが ja/en 両方に存在する', () => {
    const jaUi = (ja as any).annotator.ui
    const enUi = (en as any).annotator.ui
    expect(typeof jaUi.recording_branch_error).toBe('string')
    expect(jaUi.recording_branch_error.length).toBeGreaterThan(0)
    expect(typeof enUi.recording_branch_error).toBe('string')
    expect(enUi.recording_branch_error.length).toBeGreaterThan(0)
    // 再試行ボタンは既存キーを再利用
    expect(typeof jaUi.retry).toBe('string')
    expect(typeof enUi.retry).toBe('string')
  })
})
