/**
 * 設定「データ管理」タブの同期/インポート系 CTA をロールでガード (項目500)
 *
 * 製品ルール: エクスポート / インポート / クラウドパッケージ / 競合レビュー /
 * JSON パッケージ インポートの各セクションは、バックエンドで require_analyst
 * (analyst / admin のみ) が掛かった API を呼ぶ。したがって player / coach には
 * これらの CTA を一切表示しない (fail closed)。analyst / admin では従来どおり表示する。
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
vi.mock('@/components/tutorial/useTutorial', () => ({
  replayTutorial: vi.fn(async () => false),
  useTutorialState: () => ({ state: [], loading: false, refresh: vi.fn(), loadError: null }),
  useAutoTutorial: vi.fn(),
}))

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

// 重い子コンポーネントは描画を簡略化 (ロールガードの検証には不要)
vi.mock('@/components/cluster/ClusterSettingsPanel', () => ({ ClusterSettingsPanel: () => null }))
vi.mock('@/components/auth/PasswordChangeCard', () => ({ PasswordChangeCard: () => null }))
vi.mock('@/components/auth/ConsentManagementCard', () => ({ ConsentManagementCard: () => null }))
vi.mock('@/components/benchmark/DeviceSelector', () => ({ DeviceSelector: () => null }))
vi.mock('@/components/benchmark/TargetSelector', () => ({ TargetSelector: () => null }))
vi.mock('@/components/benchmark/ResultMatrix', () => ({ ResultMatrix: () => null }))
vi.mock('@/components/benchmark/BenchmarkProgress', () => ({ BenchmarkProgress: () => null }))
vi.mock('qrcode', () => ({ default: { toDataURL: vi.fn(async () => '') } }))

import { SettingsPage } from '../SettingsPage'

const ui = (ja as unknown as { settings: { ui: Record<string, string> } }).settings.ui
const dataTabLabel = (ja as unknown as { auto: { SettingsPage: Record<string, string> } }).auto.SettingsPage.k32

async function renderDataTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const result = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  // 「データ管理」タブへ切り替え
  const tabBtn = Array.from(result.container.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === dataTabLabel,
  )
  expect(tabBtn, 'データ管理タブのボタンが見つかること').toBeTruthy()
  fireEvent.click(tabBtn!)
  await waitFor(() => {
    // データ管理タブのいずれかの要素が描画されるまで待つ
    expect(result.container.textContent).toBeTruthy()
  })
  return result
}

describe('SettingsPage データ管理タブ ロールガード (項目500)', () => {
  beforeEach(() => {
    mockRole = 'player'
  })

  it.each(['player', 'coach'] as UserRole[])(
    '%s: エクスポート/インポート/JSONパッケージインポートを表示しない',
    async (r) => {
      mockRole = r
      const { container } = await renderDataTab()
      expect(container.querySelector('[data-tutorial="settings.export"]')).toBeNull()
      expect(container.querySelector('[data-tutorial="settings.import"]')).toBeNull()
      expect(container.textContent ?? '').not.toContain(ui.json_package_import)
    },
    20000,
  )

  it.each(['analyst', 'admin'] as UserRole[])(
    '%s: エクスポート/インポート/JSONパッケージインポートを従来どおり表示する',
    async (r) => {
      mockRole = r
      const { container } = await renderDataTab()
      expect(container.querySelector('[data-tutorial="settings.export"]')).not.toBeNull()
      expect(container.querySelector('[data-tutorial="settings.import"]')).not.toBeNull()
      expect(container.textContent ?? '').toContain(ui.json_package_import)
    },
    20000,
  )
})
