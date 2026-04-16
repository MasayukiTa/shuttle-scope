// クラスタ設定パネル
// Settings → クラスタ タブで表示。
// cluster.config.yaml の読み書き、ノード疎通確認、負荷状況をまとめて管理する。

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Network, Server, Cpu, Zap, Plus, Trash2,
  RefreshCw, CheckCircle2, XCircle, Loader2, Save,
} from 'lucide-react'
import { apiGet, apiPost } from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useCardTheme } from '@/hooks/useCardTheme'

// ────────────────────────────────────────────────────────────────────────────
// 型定義
// ────────────────────────────────────────────────────────────────────────────

interface WorkerNode {
  id: string
  ip: string
  label: string
}

interface ClusterConfig {
  mode: 'single' | 'primary' | 'worker'
  node?: { role?: string; id?: string }
  network?: {
    cluster_interface?: string
    fallback_interface?: string
    client_interface?: string
    primary_ip?: string
    workers?: WorkerNode[]
  }
  ray?: { head_address?: string; num_cpus?: number | null; num_gpus?: number | null }
  load_limits?: {
    max_gpu_percent?: number
    max_cpu_percent?: number
    max_concurrent_inference?: number
  }
  inference?: { max_cameras?: number }
}

interface NetworkInterface {
  name: string
  ip: string
  is_up: string
  speed_mbps: string
}

interface ClusterStatus {
  mode: string
  node_id: string
  load: {
    cpu_percent: number
    gpu_percent: number
    active_tasks: number
    max_concurrent_inference: number
    cpu_limit: number
    gpu_limit: number
    cpu_ok: boolean
    gpu_ok: boolean
    slots_ok: boolean
  }
  ray: { status: string; nodes: Array<{ node_id: string; alive: boolean }> }
}

interface NodePingResult {
  reachable: boolean
  latency_ms: number
  error?: string
}

// ────────────────────────────────────────────────────────────────────────────
// サブコンポーネント: ステータスバッジ
// ────────────────────────────────────────────────────────────────────────────

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full font-medium ${
      ok ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'
    }`}>
      {ok ? <CheckCircle2 size={10} /> : <XCircle size={10} />}
      {label}
    </span>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// サブコンポーネント: ゲージバー
// ────────────────────────────────────────────────────────────────────────────

function GaugeBar({ value, limit, label }: { value: number; limit: number; label: string }) {
  const pct = Math.min(100, Math.round(value))
  const over = value >= limit
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-[11px] text-gray-400">
        <span>{label}</span>
        <span className={over ? 'text-red-400 font-medium' : ''}>{pct}% / {limit}%</span>
      </div>
      <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${over ? 'bg-red-500' : 'bg-blue-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// メインパネル
// ────────────────────────────────────────────────────────────────────────────

export function ClusterSettingsPanel() {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const { cardBg, border, textMuted } = useCardTheme()

  // ── ローカル状態 ──────────────────────────────────────────────────────────
  const [cfg, setCfg] = useState<ClusterConfig>({ mode: 'single' })
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [pingResults, setPingResults] = useState<Record<string, NodePingResult | 'loading'>>({})

  // ── リモートデータ ────────────────────────────────────────────────────────
  const { data: remoteCfg, isLoading: cfgLoading } = useQuery({
    queryKey: ['cluster-config'],
    queryFn: () => apiGet<ClusterConfig>('/cluster/config'),
  })

  const { data: interfaces } = useQuery({
    queryKey: ['cluster-interfaces'],
    queryFn: () => apiGet<NetworkInterface[]>('/cluster/interfaces'),
  })

  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ['cluster-status'],
    queryFn: () => apiGet<ClusterStatus>('/cluster/status'),
    refetchInterval: 5000,
  })

  // ── config 読み込み後にローカル状態を初期化 ───────────────────────────────
  useEffect(() => {
    if (remoteCfg) setCfg(remoteCfg)
  }, [remoteCfg])

  // ── 保存ミューテーション ──────────────────────────────────────────────────
  const saveMutation = useMutation({
    mutationFn: () => apiPost('/cluster/config', { config: cfg }),
    onSuccess: () => {
      setSaveMsg(t('cluster.save_ok'))
      setTimeout(() => setSaveMsg(null), 3000)
    },
    onError: () => setSaveMsg(t('cluster.save_error')),
  })

  // ── ヘルパー ──────────────────────────────────────────────────────────────
  const updateNetwork = (key: string, value: string) =>
    setCfg(c => ({ ...c, network: { ...c.network, [key]: value } }))

  const updateLimit = (key: string, value: number) =>
    setCfg(c => ({ ...c, load_limits: { ...c.load_limits, [key]: value } }))

  const workers = cfg.network?.workers ?? []

  const addWorker = () =>
    setCfg(c => ({
      ...c,
      network: {
        ...c.network,
        workers: [...(c.network?.workers ?? []), { id: '', ip: '', label: '' }],
      },
    }))

  const removeWorker = (i: number) =>
    setCfg(c => ({
      ...c,
      network: {
        ...c.network,
        workers: (c.network?.workers ?? []).filter((_, idx) => idx !== i),
      },
    }))

  const updateWorker = (i: number, key: keyof WorkerNode, val: string) =>
    setCfg(c => ({
      ...c,
      network: {
        ...c.network,
        workers: (c.network?.workers ?? []).map((w, idx) =>
          idx === i ? { ...w, [key]: val } : w
        ),
      },
    }))

  const pingWorker = async (ip: string, idx: number) => {
    setPingResults(r => ({ ...r, [idx]: 'loading' }))
    try {
      const res = await apiPost<NodePingResult>('/cluster/ping', { ip, port: 8765, timeout: 2 })
      setPingResults(r => ({ ...r, [idx]: res }))
    } catch {
      setPingResults(r => ({ ...r, [idx]: { reachable: false, latency_ms: 0 } }))
    }
  }

  // ── インターフェース選択オプション ────────────────────────────────────────
  const ifOptions = interfaces ?? []

  // ── レンダリング ──────────────────────────────────────────────────────────
  const sectionCls = `${cardBg} border ${border} rounded-lg p-4 space-y-3`
  const labelCls = `text-xs font-medium ${isLight ? 'text-gray-600' : 'text-gray-400'}`
  const inputCls = `w-full text-sm px-2 py-1.5 rounded border ${border} ${
    isLight ? 'bg-white text-gray-900' : 'bg-gray-800 text-gray-100'
  } focus:outline-none focus:ring-1 focus:ring-blue-500`

  if (cfgLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="animate-spin text-blue-400" /></div>
  }

  return (
    <div className="space-y-4 max-w-2xl">

      {/* ── 動作モード ──────────────────────────────────────────────────── */}
      <section className={sectionCls}>
        <h3 className={`text-sm font-semibold flex items-center gap-2 ${isLight ? 'text-gray-800' : 'text-gray-200'}`}>
          <Server size={14} /> {t('cluster.mode_label')}
        </h3>
        <div className="flex gap-2">
          {(['single', 'primary', 'worker'] as const).map(m => (
            <button
              key={m}
              onClick={() => setCfg(c => ({ ...c, mode: m }))}
              className={`px-3 py-1.5 rounded text-sm border transition-colors ${
                cfg.mode === m
                  ? 'border-blue-500 bg-blue-600 text-white'
                  : `border-gray-600 ${isLight ? 'text-gray-700 hover:border-gray-400' : 'text-gray-300 hover:border-gray-500'}`
              }`}
            >
              {t(`cluster.mode_${m}`)}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className={labelCls}>{t('cluster.node_id')}</span>
          <input
            className={`${inputCls} w-40`}
            value={cfg.node?.id ?? 'pc1'}
            onChange={e => setCfg(c => ({ ...c, node: { ...c.node, id: e.target.value } }))}
          />
        </div>
      </section>

      {/* ── ネットワーク割り当て ─────────────────────────────────────────── */}
      {cfg.mode !== 'single' && (
        <section className={sectionCls}>
          <h3 className={`text-sm font-semibold flex items-center gap-2 ${isLight ? 'text-gray-800' : 'text-gray-200'}`}>
            <Network size={14} /> {t('cluster.network_section')}
          </h3>

          {[
            { key: 'cluster_interface',  label: t('cluster.cluster_if') },
            { key: 'fallback_interface', label: t('cluster.fallback_if') },
            { key: 'client_interface',   label: t('cluster.client_if') },
          ].map(({ key, label }) => (
            <div key={key} className="flex items-center gap-2">
              <span className={`${labelCls} w-36 shrink-0`}>{label}</span>
              <select
                className={inputCls}
                value={(cfg.network as any)?.[key] ?? ''}
                onChange={e => updateNetwork(key, e.target.value)}
              >
                <option value="">{t('cluster.if_placeholder')}</option>
                {ifOptions.map(iface => (
                  <option key={iface.name} value={iface.name}>
                    {iface.name} {iface.ip ? `(${iface.ip})` : ''} {iface.speed_mbps !== '0' ? `${iface.speed_mbps}Mbps` : ''}
                  </option>
                ))}
              </select>
            </div>
          ))}

          <div className="flex items-center gap-2">
            <span className={`${labelCls} w-36 shrink-0`}>{t('cluster.primary_ip')}</span>
            <input
              className={inputCls}
              placeholder="192.168.100.1"
              value={cfg.network?.primary_ip ?? ''}
              onChange={e => updateNetwork('primary_ip', e.target.value)}
            />
          </div>
        </section>
      )}

      {/* ── ワーカーノード ───────────────────────────────────────────────── */}
      {cfg.mode === 'primary' && (
        <section className={sectionCls}>
          <div className="flex items-center justify-between">
            <h3 className={`text-sm font-semibold flex items-center gap-2 ${isLight ? 'text-gray-800' : 'text-gray-200'}`}>
              <Cpu size={14} /> {t('cluster.workers_section')}
            </h3>
            <button
              onClick={addWorker}
              className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
            >
              <Plus size={12} /> {t('cluster.add_worker')}
            </button>
          </div>

          {workers.length === 0 && (
            <p className={`text-xs ${textMuted}`}>ワーカーノードがありません</p>
          )}

          {workers.map((w, i) => {
            const pr = pingResults[i]
            return (
              <div key={i} className={`flex items-center gap-2 p-2 rounded border ${border}`}>
                <input
                  className={`${inputCls} w-16`}
                  placeholder="pc2"
                  value={w.id}
                  onChange={e => updateWorker(i, 'id', e.target.value)}
                />
                <input
                  className={`${inputCls} w-32`}
                  placeholder="192.168.100.2"
                  value={w.ip}
                  onChange={e => updateWorker(i, 'ip', e.target.value)}
                />
                <input
                  className={inputCls}
                  placeholder="GMKtec K10"
                  value={w.label}
                  onChange={e => updateWorker(i, 'label', e.target.value)}
                />
                <button
                  onClick={() => pingWorker(w.ip, i)}
                  disabled={!w.ip}
                  className="text-xs text-blue-400 hover:text-blue-300 shrink-0"
                  title={t('cluster.test')}
                >
                  {pr === 'loading' ? <Loader2 size={12} className="animate-spin" /> : <Network size={12} />}
                </button>
                {pr && pr !== 'loading' && (
                  <span className={`text-[11px] shrink-0 ${pr.reachable ? 'text-green-400' : 'text-red-400'}`}>
                    {pr.reachable ? `${pr.latency_ms}ms` : 'NG'}
                  </span>
                )}
                <button onClick={() => removeWorker(i)} className="text-red-400 hover:text-red-300 shrink-0">
                  <Trash2 size={12} />
                </button>
              </div>
            )
          })}
        </section>
      )}

      {/* ── 負荷制限 ─────────────────────────────────────────────────────── */}
      <section className={sectionCls}>
        <h3 className={`text-sm font-semibold flex items-center gap-2 ${isLight ? 'text-gray-800' : 'text-gray-200'}`}>
          <Zap size={14} /> {t('cluster.load_section')}
        </h3>
        <div className="space-y-3">
          {[
            { key: 'max_gpu_percent', label: t('cluster.max_gpu'), min: 30, max: 100 },
            { key: 'max_cpu_percent', label: t('cluster.max_cpu'), min: 30, max: 100 },
            { key: 'max_concurrent_inference', label: t('cluster.max_inf'), min: 1, max: 16 },
          ].map(({ key, label, min, max }) => {
            const val = (cfg.load_limits as any)?.[key] ?? (key === 'max_concurrent_inference' ? 4 : 80)
            return (
              <div key={key} className="flex items-center gap-3">
                <span className={`${labelCls} w-36 shrink-0`}>{label}</span>
                <input
                  type="range" min={min} max={max} value={val}
                  onChange={e => updateLimit(key, Number(e.target.value))}
                  className="flex-1 accent-blue-500"
                />
                <span className="text-sm w-8 text-right">{val}</span>
              </div>
            )
          })}
        </div>
      </section>

      {/* ── クラスタステータス ────────────────────────────────────────────── */}
      <section className={sectionCls}>
        <div className="flex items-center justify-between">
          <h3 className={`text-sm font-semibold flex items-center gap-2 ${isLight ? 'text-gray-800' : 'text-gray-200'}`}>
            {t('cluster.status_section')}
          </h3>
          <button
            onClick={() => refetchStatus()}
            className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
          >
            <RefreshCw size={11} /> {t('cluster.refresh')}
          </button>
        </div>

        {status ? (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <span className={`text-xs ${textMuted}`}>
                {status.node_id} ({status.mode})
              </span>
              <StatusBadge
                ok={status.ray.status === 'running'}
                label={
                  status.ray.status === 'running' ? t('cluster.ray_running') :
                  status.ray.status === 'off'     ? t('cluster.ray_off') :
                                                    t('cluster.ray_stopped')
                }
              />
            </div>
            <GaugeBar
              value={status.load.cpu_percent}
              limit={status.load.cpu_limit}
              label={t('cluster.cpu_usage')}
            />
            <GaugeBar
              value={status.load.gpu_percent}
              limit={status.load.gpu_limit}
              label={t('cluster.gpu_usage')}
            />
            <div className={`text-xs ${textMuted}`}>
              {t('cluster.active_tasks')}: {status.load.active_tasks} / {status.load.max_concurrent_inference}
            </div>
          </div>
        ) : (
          <p className={`text-xs ${textMuted}`}>ステータス取得中...</p>
        )}
      </section>

      {/* ── 保存ボタン ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 text-white text-sm disabled:opacity-50"
        >
          {saveMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          {t('cluster.save')}
        </button>
        {saveMsg && (
          <span className={`text-xs ${saveMsg.includes('失敗') ? 'text-red-400' : 'text-green-400'}`}>
            {saveMsg}
          </span>
        )}
      </div>

    </div>
  )
}
