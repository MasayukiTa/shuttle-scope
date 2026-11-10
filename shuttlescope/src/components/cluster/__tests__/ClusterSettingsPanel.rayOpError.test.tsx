/**
 * audit item 602: when POST /cluster/ray/start fails, ClusterSettingsPanel must
 * surface an explicit error instead of silently snapping the start button back.
 * rayStartMutation.onError sets rayOpError to the rejection message, and the panel
 * renders a role="alert" element whose text is t('cluster.ray_op_error', { message }).
 *
 * This replaces the deleted ClusterSettingsPanel.rayOpError.h14.test.tsx, whose mocked
 * render could not find the Ray start control ("Unable to find cluster.ray_start"). The
 * start button only renders inside the cluster-status section, which itself lives inside
 * the collapsible advanced-settings block (gated by the cluster_showAdvanced localStorage
 * flag) and requires the /cluster/status query to resolve with ray.status neither
 * 'running' nor the connecting state. This test expands the advanced block and feeds that
 * status so the real control appears, then clicks it with apiPost rejecting for
 * /cluster/ray/start and asserts the cluster.ray_op_error alert text.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/i18n'

// Only the HTTP verbs the component drives are stubbed; everything else the module
// exports is irrelevant to this panel.
const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: (...a: unknown[]) => apiPost(...a),
  apiDelete: vi.fn(),
  newIdempotencyKey: () => 'k',
}))

// useCardTheme internally calls useIsLightMode, so stubbing this one hook covers both.
vi.mock('@/hooks/useIsLightMode', () => ({ useIsLightMode: () => false }))

import { ClusterSettingsPanel } from '../ClusterSettingsPanel'

// /cluster/status with Ray not running and not connecting: the start control renders.
const STATUS_RAY_OFF = {
  mode: 'single',
  node_id: 'node-1',
  load: {
    cpu_percent: 10,
    gpu_percent: 20,
    active_tasks: 0,
    max_concurrent_inference: 2,
    cpu_limit: 90,
    gpu_limit: 90,
    cpu_ok: true,
    gpu_ok: true,
    slots_ok: true,
  },
  ray: { status: 'off', nodes: [] },
}

function mockGet(path: string) {
  if (path === '/cluster/status') return Promise.resolve(STATUS_RAY_OFF)
  if (path === '/cluster/config') return Promise.resolve({ mode: 'single' })
  if (path === '/cluster/interfaces') return Promise.resolve([])
  if (path === '/cluster/hardware') return Promise.resolve({ system_ram_gb: 16, vram_total_gb: 8 })
  return Promise.resolve({})
}

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ClusterSettingsPanel />
    </QueryClientProvider>,
  )
}

describe('ClusterSettingsPanel Ray start failure (audit 602)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockImplementation((path: string) => mockGet(path))
    // The cluster-status section with the Ray start control is inside the collapsible
    // advanced-settings block; expand it so the control renders.
    localStorage.setItem('cluster_showAdvanced', '1')
  })

  it('shows the cluster.ray_op_error alert when POST /cluster/ray/start rejects', async () => {
    apiPost.mockImplementation((path: string) => {
      if (path === '/cluster/ray/start') return Promise.reject(new Error('start boom'))
      return Promise.resolve({ ok: true })
    })

    renderPanel()

    // Wait for the status section (gated by the resolved /cluster/status query) to render,
    // then locate the real Ray start control inside it.
    const statusHeading = await screen.findByRole('heading', {
      name: i18n.t('cluster.status_section'),
    })
    const statusSection = statusHeading.closest('section') as HTMLElement
    const startBtn = await within(statusSection).findByRole('button', {
      name: i18n.t('cluster.ray_start'),
    })

    await act(async () => {
      fireEvent.click(startBtn)
    })

    // The POST that we make reject must target /cluster/ray/start with an empty body.
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/cluster/ray/start', {}))

    // rayStartMutation.onError must surface the failure as an explicit alert whose text is
    // t('cluster.ray_op_error', { message }) with the rejection message interpolated.
    const alert = await within(statusSection).findByRole('alert')
    expect(alert).toHaveTextContent(
      i18n.t('cluster.ray_op_error', { message: 'start boom' }),
    )
    // Sanity: the interpolated rejection message is actually present.
    expect(alert).toHaveTextContent('start boom')
  })
})
