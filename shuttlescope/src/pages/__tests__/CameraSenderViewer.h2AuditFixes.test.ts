/**
 * Audit h2 fixes (#481, #483).
 *
 * #481 CameraSenderPage: the local SessionBadge no longer receives the device
 *      name through a prop named `role`; it takes an explicit `deviceName` prop
 *      so the code matches the label it renders (camera_sender.role_display).
 * #483 ViewerPage: the waiting-screen hint no longer claims phones are summary
 *      only / show no video, since no device-type gate is implemented.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

const SRC = resolve(__dirname, '..', '..')

function k13(dict: Record<string, any>): string {
  return dict.auto.ViewerPage.k13 as string
}

describe('#483 viewer phone-summary claim removed', () => {
  it('key still present in both locales', () => {
    expect(typeof k13(ja as any)).toBe('string')
    expect(typeof k13(en as any)).toBe('string')
  })

  it('ja copy drops the summary-only / no-video claim', () => {
    const s = k13(ja as any)
    expect(s).not.toContain('要約だけ')
    expect(s).not.toContain('映像を表示せず')
  })

  it('en copy drops the summary-only / no-video claim', () => {
    const s = k13(en as any).toLowerCase()
    expect(s).not.toContain('summary only')
    expect(s).not.toContain('without video')
  })
})

describe('#481 SessionBadge uses deviceName prop (no role mislabel)', () => {
  const src = readFileSync(resolve(SRC, 'pages', 'CameraSenderPage.tsx'), 'utf-8')

  it('SessionBadge signature takes deviceName', () => {
    expect(src).toContain('function SessionBadge({ sessionCode, deviceName }')
    expect(src).not.toContain('function SessionBadge({ sessionCode, role }')
  })

  it('call site passes deviceName, not role', () => {
    expect(src).toContain('deviceName={savedDeviceNameRef.current || getDeviceTypeLabel()}')
    expect(src).not.toContain('role={savedDeviceNameRef.current || getDeviceTypeLabel()}')
  })
})
