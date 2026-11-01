/**
 * Audit #577: YOLO reset failure must show a generic, production-safe message —
 * not HTTP status, endpoint, restart advice, or raw exception detail.
 *
 * handleYoloReset (src/hooks/annotator/useCVJobs.ts) now calls
 * notifyError(i18n.t('common_ui.yolo_reset_failed')) in its catch, and keeps the
 * HTTP status / exception message to console only. This test pins:
 *
 *   1. the yolo_reset_failed string exists in BOTH locales,
 *   2. it is the agreed user-facing wording (results not changed, retry),
 *   3. it leaks none of: HTTP status token, the DELETE endpoint, restart advice,
 *      or interpolation of a raw error message.
 *
 * If a regression re-introduces status/endpoint/exception detail into the
 * user-facing message, this test fails.
 */
import { describe, it, expect } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

const jaMsg = (ja as any).common_ui.yolo_reset_failed as string
const enMsg = (en as any).common_ui.yolo_reset_failed as string

describe('項目577 YOLOリセット失敗メッセージは一般化されている', () => {
  it('ja/en 両方に文字列キーが存在する', () => {
    expect(typeof jaMsg).toBe('string')
    expect(jaMsg.length).toBeGreaterThan(0)
    expect(typeof enMsg).toBe('string')
    expect(enMsg.length).toBeGreaterThan(0)
  })

  it('内部情報 (HTTP status / endpoint / 再起動指示 / 生エラー) を露出しない', () => {
    for (const msg of [jaMsg, enMsg]) {
      // HTTP method / status token (DELETE as a method is upper-case; plain
      // "delete" as an English verb in the wording is allowed).
      expect(msg).not.toMatch(/status\s*=|HTTP\s*\d/)
      expect(msg).not.toMatch(/\bstatus\b/)
      expect(msg).not.toMatch(/DELETE\b/)
      expect(msg).not.toMatch(/\/yolo\/results|endpoint/i)
      expect(msg).not.toMatch(/再起動|restart/i)
      expect(msg).not.toMatch(/詳細\s*:|\$\{|detail:/i)
    }
  })

  it('結果は変更されていない / 再試行の意図を伝える', () => {
    expect(jaMsg).toContain('変更されていません')
    expect(enMsg.toLowerCase()).toContain('not changed')
    expect(enMsg.toLowerCase()).toMatch(/try again|retry/)
  })
})
