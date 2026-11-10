/**
 * 設定「アカウント」タブに『チュートリアルをもう一度見る』入口が出て、
 * 押すとチュートリアルが始まることを実コンポーネントで確かめる (muse T009)。
 *
 * 症状: 初回の自動表示を終えたアカウントでは再生の入口が設定画面に見つからない。
 * 修正: 全ロールが見られるアカウント設定タブに TutorialReplaySection を置く。
 *
 * useTutorial はモックせず実物を使い、再生ボタン押下で openTutorial が発火
 * (= useTutorialChannel が tutorial id を返す) ことを検証する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { UserRole } from '@/types'
import ja from '@/i18n/ja.json'
import { useTutorialChannel, closeTutorial } from '@/components/tutorial/useTutorial'
import { TUTORIALS } from '@/components/tutorial/tutorials'

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
  sync_device_id: 'dev-1',
  sync_folder_path: 'C:/sync',
  cuda_device_index: 0,
  ngrok_authtoken: '',
  openvino_device: 'CPU',
  tracknet_backend: 'cpu',
  tracknet_enabled: false,
  tracknet_max_cpu_pct: 50,
  tracknet_mode: 'off',
  tunnel_provider: 'none',
  turn_credential: '',
  turn_enabled: false,
  turn_static_auth_secret: '',
  turn_url: '',
  turn_username: '',
  video_transport: 'webrtc',
  yolo_enabled: false,
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

// API: /tutorials/state は空配列、replay POST は成功扱い。useTutorial は実物。
vi.mock('@/api/client', () => ({
  apiGet: vi.fn(async () => ({ success: true, data: [] })),
  apiPost: vi.fn(async () => ({ success: true, data: {} })),
  apiPut: vi.fn(async () => ({ success: true, data: {} })),
  apiDelete: vi.fn(async () => ({ success: true, data: {} })),
  newIdempotencyKey: () => 'test-key',
}))
vi.mock('@/api/benchmark', () => ({
  getDevices: vi.fn(async () => []),
  runBenchmark: vi.fn(),
  cancelJob: vi.fn(),
  getJob: vi.fn(),
}))
vi.mock('@/api/db', () => ({
  getDbStats: vi.fn(async () => ({})),
  runDbMaintenance: vi.fn(),
  setAutoVacuum: vi.fn(),
}))

// 重い子コンポーネントは描画を簡略化 (この検証には不要)
vi.mock('@/components/cluster/ClusterSettingsPanel', () => ({ ClusterSettingsPanel: () => null }))
vi.mock('@/components/auth/PasswordChangeCard', () => ({ PasswordChangeCard: () => null }))
vi.mock('@/components/auth/ConsentManagementCard', () => ({ ConsentManagementCard: () => null }))
vi.mock('@/components/benchmark/DeviceSelector', () => ({ DeviceSelector: () => null }))
vi.mock('@/components/benchmark/TargetSelector', () => ({ TargetSelector: () => null }))
vi.mock('@/components/benchmark/ResultMatrix', () => ({ ResultMatrix: () => null }))
vi.mock('@/components/benchmark/BenchmarkProgress', () => ({ BenchmarkProgress: () => null }))
vi.mock('qrcode', () => ({ default: { toDataURL: vi.fn(async () => '') } }))

import { SettingsPage } from '../SettingsPage'

const sp = (ja as unknown as { auto: { SettingsPage: Record<string, string> } }).auto.SettingsPage
const accountTabLabel = sp.k33 // アカウント
const playLabel = sp.k45 // 再生

// useTutorialChannel を購読して現在の tutorial id を data 属性に出すプローブ
function ChannelProbe() {
  const ch = useTutorialChannel()
  return <div data-testid="tutorial-channel" data-channel={ch ?? ''} />
}

async function renderAccountTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const result = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SettingsPage />
        <ChannelProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  const tabBtn = Array.from(result.container.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === accountTabLabel,
  )
  expect(tabBtn, 'アカウントタブのボタンが見つかること').toBeTruthy()
  fireEvent.click(tabBtn!)
  await waitFor(() => {
    expect(result.container.querySelector('[data-tutorial="settings.tutorialReplay"]')).not.toBeNull()
  })
  return result
}

describe('SettingsPage アカウントタブ チュートリアル再生入口 (T009)', () => {
  beforeEach(() => {
    mockRole = 'player'
    closeTutorial()
  })

  it('アカウントタブに再生セクションが表示される (全ロール)', async () => {
    const { container } = await renderAccountTab()
    const section = container.querySelector('[data-tutorial="settings.tutorialReplay"]')
    expect(section).not.toBeNull()
    // 見出し「チュートリアル」
    expect(section!.textContent ?? '').toContain(sp.k42)
  })

  it('再生ボタンを押すとチュートリアルが始まる (openTutorial 発火)', async () => {
    const { container, getByTestId } = await renderAccountTab()
    const section = container.querySelector('[data-tutorial="settings.tutorialReplay"]')!
    // 再生前はチャンネルは空
    expect(getByTestId('tutorial-channel').getAttribute('data-channel')).toBe('')
    // セクション内の「再生」ボタンを押す
    const playBtn = Array.from(section.querySelectorAll('button')).find(
      (b) => b.textContent?.trim().includes(playLabel),
    )
    expect(playBtn, '再生ボタンが見つかること').toBeTruthy()
    fireEvent.click(playBtn!)
    await waitFor(() => {
      const ch = getByTestId('tutorial-channel').getAttribute('data-channel')
      expect(ch && ch.length > 0, 'クリック後にチュートリアルが開始されること').toBe(true)
      // 開始された id は既知の TUTORIALS のいずれか
      expect(Object.keys(TUTORIALS)).toContain(ch)
    })
  })
})
