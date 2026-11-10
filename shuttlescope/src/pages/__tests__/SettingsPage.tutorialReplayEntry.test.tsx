/**
 * 設定「アカウント」タブのチュートリアル再生エントリ (T009 / 仙台大学要望3)
 *
 * 症状: 初回自動表示を終えたアカウントでは、チュートリアル再生の入口が
 * 設定画面に見つからない。従来は再生セクションが「データ管理」タブの奥にしか
 * なく、player / coach / LLM 専用ユーザからは到達しにくかった。
 *
 * 本テスト: 全ロールが常に見る account タブに再生エントリが出ること、
 * その「再生」ボタンを押すとチュートリアルが始まることを実コンポーネントで確かめる。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { UserRole } from '@/types'
import ja from '@/i18n/ja.json'

let mockRole: UserRole | null = 'player'

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    teamName: 'チームA',
    displayName: 'テスト ユーザー',
    userId: 1,
    clearRole: vi.fn(),
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole)),
  }),
}))

const settings = {
  sync_device_id: 'dev-1', sync_folder_path: 'C:/sync', cuda_device_index: 0,
  ngrok_authtoken: '', openvino_device: 'CPU', tracknet_backend: 'cpu',
  tracknet_enabled: false, tracknet_max_cpu_pct: 50, tracknet_mode: 'off',
  tunnel_provider: 'none', turn_credential: '', turn_enabled: false,
  turn_static_auth_secret: '', turn_url: '', turn_username: '',
  video_transport: 'webrtc', yolo_enabled: false,
}

vi.mock('@/hooks/useSettings', () => ({
  useSettings: () => ({ settings, updateSettings: vi.fn(), loading: false, saveFailed: false }),
}))
vi.mock('@/hooks/useCardTheme', () => ({
  useCardTheme: () => ({ card: '', textHeading: '', textSecondary: '', textMuted: '', textFaint: '', isLight: true }),
}))
vi.mock('@/hooks/useIsLightMode', () => ({ useIsLightMode: () => true }))
vi.mock('@/hooks/useTheme', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }))
vi.mock('@/store/annotationStore', () => ({ useAnnotationStore: () => 0 }))

// 実コンポーネント検証: useTutorial はモックせず実物を使う。
// replayTutorial は apiPost('/tutorials/{id}/replay') を呼ぶので、
// apiPost の呼び出しで「再生が始まった」ことを確かめる。
const apiPostMock = vi.fn(async () => ({ success: true, data: {} }))
const apiGetMock = vi.fn(async () => ({ success: true, data: [] }))
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGetMock(...(a as [])),
  apiPost: (...a: unknown[]) => apiPostMock(...(a as [])),
  apiPut: vi.fn(async () => ({ success: true, data: {} })),
  apiDelete: vi.fn(async () => ({ success: true, data: {} })),
  newIdempotencyKey: () => 'test-key',
}))
vi.mock('@/api/benchmark', () => ({
  getDevices: vi.fn(async () => []), runBenchmark: vi.fn(), cancelJob: vi.fn(), getJob: vi.fn(),
}))
vi.mock('@/api/db', () => ({
  getDbStats: vi.fn(async () => ({})), runDbMaintenance: vi.fn(), setAutoVacuum: vi.fn(),
}))

vi.mock('@/components/cluster/ClusterSettingsPanel', () => ({ ClusterSettingsPanel: () => null }))
vi.mock('@/components/auth/PasswordChangeCard', () => ({ PasswordChangeCard: () => null }))
vi.mock('@/components/auth/ConsentManagementCard', () => ({ ConsentManagementCard: () => null }))
vi.mock('@/components/benchmark/DeviceSelector', () => ({ DeviceSelector: () => null }))
vi.mock('@/components/benchmark/TargetSelector', () => ({ TargetSelector: () => null }))
vi.mock('@/components/benchmark/ResultMatrix', () => ({ ResultMatrix: () => null }))
vi.mock('@/components/benchmark/BenchmarkProgress', () => ({ BenchmarkProgress: () => null }))
vi.mock('qrcode', () => ({ default: { toCanvas: vi.fn(async () => undefined), toDataURL: vi.fn(async () => '') } }))

import { SettingsPage } from '../SettingsPage'

const auto = (ja as unknown as { auto: { SettingsPage: Record<string, string> } }).auto.SettingsPage
const replaySectionTitle = auto.k42 // チュートリアル

async function renderAccountTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const result = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  // player ロールの初期タブは account。追加の切り替えは不要。
  await waitFor(() => { expect(result.container.textContent).toBeTruthy() })
  return result
}

describe('SettingsPage account タブのチュートリアル再生入口 (T009)', () => {
  beforeEach(() => {
    mockRole = 'player'
    apiPostMock.mockClear()
    apiGetMock.mockClear()
  })

  it.each(['player', 'coach', 'analyst', 'admin'] as UserRole[])(
    '%s: account タブに再生エントリ (settings.tutorialReplay) が表示される',
    async (r) => {
      mockRole = r
      const { container } = await renderAccountTab()
      const section = container.querySelector('[data-tutorial="settings.tutorialReplay"]')
      expect(section, 'account タブに再生セクションがあること').not.toBeNull()
      expect(container.textContent ?? '').toContain(replaySectionTitle)
    },
    20000,
  )

  it('再生ボタンを押すとチュートリアルが始まる (replay API が呼ばれる)', async () => {
    mockRole = 'player'
    const { container } = await renderAccountTab()
    const section = container.querySelector('[data-tutorial="settings.tutorialReplay"]') as HTMLElement
    expect(section).not.toBeNull()
    // セクション内の最初の「再生」ボタンを押す
    const replayBtn = Array.from(section.querySelectorAll('button')).find(
      (b) => b.textContent?.includes(auto.k45),
    )
    expect(replayBtn, '再生ボタンがあること').toBeTruthy()
    fireEvent.click(replayBtn!)
    await waitFor(() => {
      const called = apiPostMock.mock.calls.some(
        (c) => typeof c[0] === 'string' && /\/tutorials\/.+\/replay/.test(c[0] as string),
      )
      expect(called, 'replayTutorial が /tutorials/{id}/replay を呼ぶこと').toBe(true)
    }, { timeout: 5000 })
  }, 20000)
})
