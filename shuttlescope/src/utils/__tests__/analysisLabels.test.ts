// 分析カードの内部コード (ショット種別・状態キー) が日本語ラベルになることを固定するテスト
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import i18n from '@/i18n'
import { shotLabel, stateKeyLabel } from '../analysisLabels'

const t = (key: string) => i18n.t(key)

describe('shotLabel', () => {
  it('ショット種別コードを日本語にする', () => {
    expect(shotLabel(t, 'push_rush')).toBe('プッシュ/ラッシュ')
    expect(shotLabel(t, 'around_head')).toBe('ラウンドヘッド')
    expect(shotLabel(t, 'half_smash')).toBe('ハーフスマッシュ')
    expect(shotLabel(t, 'cross_net')).toBe('クロスネット')
  })

  it('serve / net のようなバケット名も日本語にする', () => {
    expect(shotLabel(t, 'serve')).toBe('サーブ系')
    expect(shotLabel(t, 'net')).toBe('ネット前')
  })

  it('未知のコードは黙って消さず元の文字列を返す。空は —', () => {
    expect(shotLabel(t, 'unknown_shot_zzz')).toBe('unknown_shot_zzz')
    expect(shotLabel(t, null)).toBe('—')
    expect(shotLabel(t, undefined)).toBe('—')
    expect(shotLabel(t, '')).toBe('—')
  })
})

describe('stateKeyLabel', () => {
  it("'early|second|medium|receiver' を日本語の並びにする", () => {
    expect(stateKeyLabel(t, 'early|second|medium|receiver')).toBe(
      '序盤 / 第2セット / 中くらいのラリー / レシーバー',
    )
  })

  it('知らないトークンはそのまま残す', () => {
    expect(stateKeyLabel(t, 'early|zzz')).toBe('序盤 / zzz')
    expect(stateKeyLabel(t, null)).toBe('—')
  })

  it('バックエンドの状態定義 (state_spec.py の Literal) の全値にラベルがある', () => {
    const src = readFileSync(
      resolve(process.cwd(), 'backend/analysis/state_spec.py'),
      'utf-8',
    )
    const wanted = new Set<string>()
    for (const name of ['ScorePhase', 'SetPhase', 'RallyBucket', 'PlayerRole']) {
      const m = src.match(new RegExp(`^${name}\\s*=\\s*Literal\\[([^\\]]+)\\]`, 'm'))
      expect(m, `${name} の定義が見つからない`).toBeTruthy()
      for (const v of m![1].matchAll(/"([a-z_]+)"/g)) wanted.add(v[1])
    }
    expect(wanted.size).toBeGreaterThanOrEqual(12)
    for (const token of wanted) {
      const label = stateKeyLabel(t, token)
      expect(label, `状態トークン ${token}`).not.toBe(token)
    }
  })
})
