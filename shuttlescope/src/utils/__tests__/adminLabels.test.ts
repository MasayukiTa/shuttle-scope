// 管理画面の内部コード → 日本語ラベル。バックエンドが記録する全コードにラベルがあることを固定する
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import i18n from '@/i18n'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'
import { auditActionLabel, securityEventLabel, severityLabel } from '../adminLabels'

const t = (key: string) => i18n.t(key)
// vitest は shuttlescope/ をカレントにして走る (jsdom 下では import.meta.url が file: にならない)
const BACKEND = resolve(process.cwd(), 'backend')

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (name === '__pycache__' || name === '.venv' || name === 'node_modules') continue
    const st = statSync(p)
    if (st.isDirectory()) {
      if (p.split(sep).includes('tests')) continue
      walk(p, out)
    } else if (name.endsWith('.py')) {
      out.push(p)
    }
  }
  return out
}

/** バックエンドが監査ログに書く操作コードを、ソースから拾う */
function backendAuditActions(): Set<string> {
  const codes = new Set<string>()
  const patterns = [
    /log_access\(\s*(?:\w+\s*,\s*)?(?:action\s*=\s*)?["']([a-z_0-9]+)["']/g,
    /_audit\(\s*(?:\w+\s*,\s*)?["']([a-z_0-9]+)["']/g,
  ]
  for (const file of walk(BACKEND)) {
    const src = readFileSync(file, 'utf-8')
    for (const re of patterns) {
      for (const m of src.matchAll(re)) codes.add(m[1])
    }
  }
  return codes
}

describe('adminLabels', () => {
  it('バックエンドが記録する操作コードの全てに日本語ラベルがある', () => {
    const codes = backendAuditActions()
    expect(codes.size).toBeGreaterThan(40) // 拾えていること自体の検算 (2026-10 時点で 60 超)
    const missing = [...codes].filter((c) => auditActionLabel(t, c) === c)
    expect(missing, `ラベル未登録の操作コード: ${missing.join(', ')}`).toEqual([])
  })

  it('代表的なコードが読める日本語になる', () => {
    expect(auditActionLabel(t, 'admin_audit_logs_viewed')).toBe('監査ログの閲覧')
    expect(auditActionLabel(t, 'login_failed')).toBe('ログイン失敗')
    expect(securityEventLabel(t, 'probe_attempt')).toBe('不審なパスの探索')
    expect(severityLabel(t, 'warn')).toBe('警告')
  })

  it('未登録のコードは元の文字列を返す (黙って空にしない)', () => {
    expect(auditActionLabel(t, 'brand_new_action')).toBe('brand_new_action')
    expect(securityEventLabel(t, 'brand_new_event')).toBe('brand_new_event')
  })

  it('ja / en で同じコードが揃っている', () => {
    const keys = (o: unknown) => Object.keys(o as Record<string, string>).sort()
    const jaAuth = (ja as unknown as { auth: { audit_log: { action_names: object } } }).auth.audit_log.action_names
    const enAuth = (en as unknown as { auth: { audit_log: { action_names: object } } }).auth.audit_log.action_names
    expect(keys(enAuth)).toEqual(keys(jaAuth))
    const jaSec = (ja as unknown as { security_log: { event_names: object; severity: object } }).security_log
    const enSec = (en as unknown as { security_log: { event_names: object; severity: object } }).security_log
    expect(keys(enSec.event_names)).toEqual(keys(jaSec.event_names))
    expect(keys(enSec.severity)).toEqual(keys(jaSec.severity))
  })
})
