/**
 * 要望 (2026-11-05 / ELN E-90e8cfaa2891):
 *   「何か入力するたびに保存される形態であるべき。保存し終わったはずが保存失敗と出る場合がある」
 *
 * 確定前（ラリー未確定）の入力中ストロークが、次の 4 契機で失われるかを検証する。
 *   - closeTab     : ラリーを確定する前にタブを閉じた
 *   - browserCrash : ブラウザが落ちた
 *   - networkLost  : 通信が切れた
 *   - loggedOut    : ログアウトされた（無操作失効・401/403 を含む）
 *
 * 現状（この PR 以前）: localStorage のみ。localStorage の書き込みが失敗すると
 *   どの契機でも入力が失われる（＝「保存失敗」）。
 * 本 PR 後: 1 打ごとに localStorage と IndexedDB の両方へ退避するため、
 *   localStorage が失敗しても IndexedDB が残り、どの契機でも失われない。
 */
import { describe, it, expect } from 'vitest'

import {
  classifyDraftDurability,
  classifyAllDraftDurability,
  legacyDraftState,
  durableDraftState,
  type DurabilityEvent,
} from '../strokeDraftDurability'

const EVENTS: DurabilityEvent[] = ['closeTab', 'browserCrash', 'networkLost', 'loggedOut']

describe('確定前の入力が 4 契機で失われるかの判定', () => {
  it('現状 (localStorage のみ・書き込み成功): 4 契機すべてで失われない', () => {
    const state = legacyDraftState(true)
    for (const e of EVENTS) {
      const v = classifyDraftDurability(e, state)
      expect(v.lost).toBe(false)
      expect(v.recoverableFrom).toContain('localStorage')
    }
  })

  it('現状 (localStorage 書き込み失敗・IndexedDB 無し): 4 契機すべてで失われる', () => {
    // これが要望の「保存し終わったはずが保存失敗」。localStorage が容量超過 /
    // プライベートモードで書けないと、確定前の入力はどこにも残らない。
    const state = legacyDraftState(false)
    for (const e of EVENTS) {
      const v = classifyDraftDurability(e, state)
      expect(v.lost).toBe(true)
      expect(v.recoverableFrom).toHaveLength(0)
    }
  })

  it('本 PR 後 (localStorage 失敗でも IndexedDB 成功): 4 契機すべてで失われない', () => {
    const state = durableDraftState(false, true)
    for (const e of EVENTS) {
      const v = classifyDraftDurability(e, state)
      expect(v.lost).toBe(false)
      expect(v.recoverableFrom).toContain('indexedDB')
    }
  })

  it('本 PR 後 (両層成功): 4 契機すべてで失われず、両層から復元できる', () => {
    const state = durableDraftState(true, true)
    for (const e of EVENTS) {
      const v = classifyDraftDurability(e, state)
      expect(v.lost).toBe(false)
      expect(v.recoverableFrom).toEqual(
        expect.arrayContaining(['localStorage', 'indexedDB']),
      )
    }
  })

  it('両層とも失敗: 4 契機すべてで失われる', () => {
    const state = durableDraftState(false, false)
    for (const e of EVENTS) {
      expect(classifyDraftDurability(e, state).lost).toBe(true)
    }
  })
})

describe('契機ごとの個別判定', () => {
  it('closeTab: 端末に退避済みなら失われない', () => {
    expect(classifyDraftDurability('closeTab', durableDraftState(false, true)).lost).toBe(false)
  })

  it('browserCrash: 端末に退避済みなら失われない', () => {
    expect(classifyDraftDurability('browserCrash', durableDraftState(false, true)).lost).toBe(false)
  })

  it('networkLost: 確定前はサーバーに送れないが、端末退避で失われない', () => {
    const v = classifyDraftDurability('networkLost', durableDraftState(true, true))
    expect(v.lost).toBe(false)
  })

  it('loggedOut: 本人が同じ端末で再開すれば退避済みの入力を復元できる', () => {
    const v = classifyDraftDurability('loggedOut', durableDraftState(false, true))
    expect(v.lost).toBe(false)
    expect(v.reason).toContain('再ログイン')
  })
})

describe('classifyAllDraftDurability', () => {
  it('4 契機ぶんの判定を順に返す', () => {
    const all = classifyAllDraftDurability(durableDraftState(false, true))
    expect(all.map((v) => v.event)).toEqual(EVENTS)
    expect(all.every((v) => v.lost === false)).toBe(true)
  })

  it('両層失敗なら 4 契機すべて lost=true', () => {
    const all = classifyAllDraftDurability(legacyDraftState(false))
    expect(all.every((v) => v.lost === true)).toBe(true)
  })
})
