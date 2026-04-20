// クラスタ設定パネル
// Settings → クラスタ タブで表示。
// cluster.config.yaml の読み書き、ノード疎通確認、負荷状況をまとめて管理する。

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Network, Server, Cpu, Zap, Plus, Trash2,
  RefreshCw, CheckCircle2, XCircle, Loader2, Save, ScanSearch,
  Play, Square, Copy, Check, Wifi,
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
  num_cpus?: number
  num_gpus?: number
  gpu_label?: string
  model_base?: string
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
  ray?: { head_address?: string; num_cpus?: number | null; num_gpus?: number | null; auto_start?: boolean }
  load_limits?: {
    max_gpu_percent?: number
    max_cpu_percent?: number
    max_concurrent_inference?: number
  }
  inference?: { max_cameras?: number }
  resources?: {
    gpu_vram_limit_gb?: number
    system_ram_limit_gb?: number
    workers_ram_limits?: Record<string, number>  // key: worker ip
  }
  task_routing?: Record<string, string>
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
  via?: 'ray' | 'icmp' | 'http' | 'none'
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
  const [rayConnecting, setRayConnecting] = useState(false)
  const [detectingWorkers, setDetectingWorkers] = useState<Record<number, boolean>>({})
  const [detectErrors, setDetectErrors] = useState<Record<number, string>>({})
  const [arpDevices, setArpDevices] = useState<Array<{ ip: string; known_label?: string }>>([])
  const [arpScanning, setArpScanning] = useState(false)
  const [startHeadLoading, setStartHeadLoading] = useState(false)
  const [startHeadMsg, setStartHeadMsg] = useState<string | null>(null)
  const [workerCmds, setWorkerCmds] = useState<Array<{ label: string; ip: string; cmd: string }>>([])
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)
  const [sshUser, setSshUser] = useState('')
  const [sshPass, setSshPass] = useState('')
  const [remoteJoinLoading, setRemoteJoinLoading] = useState<Record<number, boolean>>({})
  const [remoteJoinMsg, setRemoteJoinMsg] = useState<Record<number, string>>({})
  // 詳細設定の開閉
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [taskRouting, setTaskRouting] = useState<Record<string, string>>({
    tracknet: 'auto',
    pose: 'auto',
    yolo: 'auto',
  })

  // ── リモートデータ ────────────────────────────────────────────────────────
  const { data: remoteCfg, isLoading: cfgLoading } = useQuery({
    queryKey: ['cluster-config'],
    queryFn: () => apiGet<ClusterConfig>('/cluster/config'),
  })

  const { data: interfaces } = useQuery({
    queryKey: ['cluster-interfaces'],
    queryFn: () => apiGet<NetworkInterface[]>('/cluster/interfaces'),
  })

  const { data: hardware } = useQuery({
    queryKey: ['cluster-hardware'],
    queryFn: () => apiGet<{ system_ram_gb: number; vram_total_gb: number }>('/cluster/hardware'),
  })

  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ['cluster-status'],
    queryFn: () => apiGet<ClusterStatus>('/cluster/status'),
    refetchInterval: rayConnecting ? 1000 : 5000,
  })

  // Ray が running になったら connecting フラグを落とす
  useEffect(() => {
    if (status?.ray.status === 'running') setRayConnecting(false)
  }, [status?.ray.status])

  // ── config 読み込み後にローカル状態を初期化 ───────────────────────────────
  useEffect(() => {
    if (remoteCfg) setCfg(remoteCfg)
  }, [remoteCfg])

  // ── task_routing の初期化 ─────────────────────────────────────────────────
  useEffect(() => {
    if (remoteCfg?.task_routing) {
      setTaskRouting(remoteCfg.task_routing as Record<string, string>)
    }
  }, [remoteCfg])

  // ── 保存ミューテーション ──────────────────────────────────────────────────
  const saveMutation = useMutation({
    mutationFn: () => apiPost('/cluster/config', { config: { ...cfg, task_routing: taskRouting } }),
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

  // dGPU があるか確認（laptop GPU ボタン表示判定用）
  const hasDgpu = typeof window !== 'undefined'
    ? true  // サーバーサイドは常に true として扱い、クライアントで判断
    : false

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

  const updateWorkerRamLimit = (workerIp: string, value: number) =>
    setCfg(c => ({
      ...c,
      resources: {
        ...c.resources,
        workers_ram_limits: {
          ...(c.resources?.workers_ram_limits ?? {}),
          [workerIp]: value,
        },
      },
    }))

  const rayStartMutation = useMutation({
    mutationFn: () => apiPost<{ ok: boolean; status: string }>('/cluster/ray/start', {}),
    onSuccess: (data) => {
      if (data.status === 'connecting') setRayConnecting(true)
      refetchStatus()
    },
  })
  const rayStopMutation = useMutation({
    mutationFn: () => apiPost<{ ok: boolean; message: string }>('/cluster/ray/stop', {}),
    onSuccess: () => { refetchStatus() },
  })

  const pingWorker = async (ip: string, idx: number) => {
    if (!ip) return
    setPingResults(r => ({ ...r, [idx]: 'loading' }))
    try {
      // まず Ray ノードリストで確認（Ray 接続中なら via:"ray" で返る）
      const nodes = await apiGet<Array<{ ip: string; ping: NodePingResult }>>('/cluster/nodes')
      const found = nodes.find(n => n.ip === ip)
      if (found?.ping) {
        setPingResults(r => ({ ...r, [idx]: found.ping }))
        return
      }
      // Ray 未接続 or ノードが見つからない → ICMP ping
      const result = await apiPost<NodePingResult>('/cluster/ping', { ip, timeout: 2.0 })
      setPingResults(r => ({ ...r, [idx]: result }))
    } catch {
      setPingResults(r => ({ ...r, [idx]: { reachable: false, latency_ms: 0, via: 'icmp' } }))
    }
  }

  const scanArp = async () => {
    setArpScanning(true)
    try {
      const devices = await apiGet<Array<{ ip: string; known_label?: string }>>('/cluster/network/arp')
      setArpDevices(devices.filter(d => !('error' in d)))
    } catch { /* ignore */ } finally {
      setArpScanning(false)
    }
  }

  const addArpAsWorker = (ip: string) => {
    setCfg(c => ({
      ...c,
      network: {
        ...c.network,
        workers: [...(c.network?.workers ?? []), { id: `pc${(c.network?.workers?.length ?? 0) + 2}`, ip, label: '' }],
      },
    }))
  }

  const startRayHead = async () => {
    const nodeIp = cfg.network?.primary_ip ?? ''
    if (!nodeIp) { setStartHeadMsg('primary_ip が未設定です'); return }
    setStartHeadLoading(true)
    setStartHeadMsg(null)
    setWorkerCmds([])
    try {
      const res = await apiPost<{ ok: boolean; message: string; worker_cmds?: Array<{ label: string; ip: string; cmd: string }> }>(
        '/cluster/ray/start-head',
        { node_ip: nodeIp, port: 6379 }
      )
      setStartHeadMsg(res.ok ? 'Ray ヘッド起動完了' : res.message)
      if (res.worker_cmds?.length) setWorkerCmds(res.worker_cmds)
      if (res.ok) refetchStatus()
    } catch (e: any) {
      setStartHeadMsg(e?.message ?? 'エラー')
    } finally {
      setStartHeadLoading(false)
    }
  }

  const copyCmd = (cmd: string, idx: number) => {
    navigator.clipboard.writeText(cmd).then(() => { setCopiedIdx(idx); setTimeout(() => setCopiedIdx(null), 2000) })
  }

  const remoteRayJoin = async (workerIp: string, idx: number) => {
    if (!sshUser) { setRemoteJoinMsg(m => ({ ...m, [idx]: 'SSHユーザー名を入力してください' })); return }
    setRemoteJoinLoading(l => ({ ...l, [idx]: true }))
    setRemoteJoinMsg(m => { const n = { ...m }; delete n[idx]; return n })
    try {
      const res = await apiPost<{ ok: boolean; message: string }>(
        `/cluster/nodes/${workerIp}/ray-join`,
        { username: sshUser, password: sshPass, head_ip: cfg.network?.primary_ip ?? '', port: 6379 }
      )
      setRemoteJoinMsg(m => ({ ...m, [idx]: res.ok ? '起動完了' : res.message }))
      if (res.ok) refetchStatus()
    } catch (e: any) {
      setRemoteJoinMsg(m => ({ ...m, [idx]: e?.message ?? 'エラー' }))
    } finally {
      setRemoteJoinLoading(l => ({ ...l, [idx]: false }))
    }
  }

  const detectWorkerHardware = async (ip: string, idx: number) => {
    if (!ip) return
    setDetectingWorkers(d => ({ ...d, [idx]: true }))
    setDetectErrors(e => { const n = { ...e }; delete n[idx]; return n })
    try {
      const res = await apiPost<{
        num_cpus?: number; cpu_name?: string
        num_gpus?: number; gpu_label?: string; gpu_vram_mb?: number
        ram_gb?: number; config_updated?: boolean
      }>(`/cluster/nodes/${ip}/detect`, {})
      // 取得結果でワーカー設定を上書き
      setCfg(c => ({
        ...c,
        network: {
          ...c.network,
          workers: (c.network?.workers ?? []).map((w, i) => {
            if (i !== idx) return w
            return {
              ...w,
              ...(res.num_cpus != null ? { num_cpus: res.num_cpus } : {}),
              ...(res.num_gpus != null ? { num_gpus: res.num_gpus } : {}),
              ...(res.gpu_label ? { gpu_label: res.gpu_label } : {}),
            }
          }),
        },
      }))
    } catch (e: any) {
      const msg = e?.message ?? String(e)
      setDetectErrors(d => ({ ...d, [idx]: msg }))
    } finally {
      setDetectingWorkers(d => ({ ...d, [idx]: false }))
    }
  }

  // ── インターフェース選択オプション ────────────────────────────────────────
  const ifOptions = (interfaces ?? []).filter(i => i.ip && !i.ip.startsWith('127.'))

  // タスク分散設定の表示条件
  const showTaskRouting = cfg.mode === 'primary' && status?.ray.status === 'running'

  // ワーカー RAM 上限の表示条件
  const showWorkerRam = cfg.mode === 'primary' && workers.length > 0 && status?.ray.status === 'running'

  // タスク種別定義
  const taskTypes = [
    { key: 'tracknet', label: t('cluster.task_tracknet') },
    { key: 'pose',     label: t('cluster.task_pose') },
    { key: 'yolo',     label: t('cluster.task_yolo') },
  ]

  // タスクルーティングの選択肢を動的生成
  const buildRoutingOptions = () => {
    const opts: Array<{ value: string; label: string }> = [
      { value: 'auto', label: t('cluster.task_auto') },
      { value: 'laptop_cpu', label: t('cluster.task_laptop_cpu') },
    ]
    // dGPU オプション（laptop GPU）
    opts.push({ value: 'laptop_gpu', label: t('cluster.task_laptop_gpu') })
    // ワーカー毎のオプション
    workers.forEach(w => {
      const label = w.label || w.ip || w.id
      opts.push({ value: `${w.id}_cpu`, label: `${label} CPU` })
      if ((w.num_gpus ?? 0) > 0) {
        opts.push({ value: `${w.id}_igpu`, label: `${label} GPU` })
      }
    })
    return opts
  }

  // ── レンダリング ──────────────────────────────────────────────────────────
  const sectionCls = `${cardBg} border ${border} rounded-lg p-4 space-y-3`
  const labelCls = `text-xs font-medium ${isLight ? 'text-gray-600' : 'text-gray-400'}`
  const inputCls = `w-full text-sm px-2 py-1.5 rounded border ${border} ${
    isLight ? 'bg-white text-gray-900' : 'bg-gray-800 text-gray-100'
  } focus:outline-none focus:ring-1 focus:ring-blue-500`

  if (cfgLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="animate-spin text-blue-400" /></div>
  }

  const rayRunning = status?.ray.status === 'running'
  const needsIp = cfg.mode === 'primary' && !cfg.network?.primary_ip

  return (
    <div className="space-y-4">

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {/* HERO: Ray ステータス + 主要アクション                                  */}
      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <section className={`${cardBg} border ${border} rounded-lg p-4 space-y-3`}>
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full shrink-0 ${
              rayConnecting ? 'bg-yellow-400 animate-pulse' :
              rayRunning    ? 'bg-green-400 shadow-[0_0_6px_rgba(74,222,128,0.6)]' :
                              'bg-gray-500'
            }`} />
            <div>
              <p className={`text-sm font-semibold ${isLight ? 'text-gray-900' : 'text-white'}`}>
                Ray クラスタ
                <span className={`ml-2 text-xs font-normal ${textMuted}`}>
                  {cfg.mode === 'single' ? 'シングル' : cfg.mode === 'primary' ? 'プライマリ' : 'ワーカー'}
                </span>
              </p>
              <p className={`text-xs ${textMuted}`}>
                {rayConnecting ? '接続確認中...' :
                 rayRunning    ? `稼働中 — ${status?.ray.nodes.filter(n => n.alive).length ?? 0} ノード接続` :
                                 '停止中'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {rayRunning ? (
              <button
                onClick={() => rayStopMutation.mutate()}
                disabled={rayStopMutation.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-red-800 hover:bg-red-700 text-white disabled:opacity-50"
              >
                {rayStopMutation.isPending ? <Loader2 size={11} className="animate-spin" /> : <Square size={11} />}
                停止
              </button>
            ) : (
              <button
                onClick={startRayHead}
                disabled={startHeadLoading || needsIp}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded bg-green-700 hover:bg-green-600 text-white disabled:opacity-40"
              >
                {startHeadLoading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                Ray 起動
              </button>
            )}
            <button onClick={() => refetchStatus()} className={`${textMuted} hover:text-white`}>
              <RefreshCw size={13} />
            </button>
          </div>
        </div>

        {/* IP未設定時のインライン選択 */}
        {needsIp && (
          <div className="space-y-1.5">
            <p className="text-xs text-yellow-400 flex items-center gap-1">
              <Wifi size={11} /> このPCのIPを選んでからRayを起動してください
            </p>
            <div className="flex flex-wrap gap-1.5">
              {ifOptions.map(iface => (
                <button
                  key={iface.name}
                  onClick={() => updateNetwork('primary_ip', iface.ip)}
                  className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs border ${border} hover:border-blue-400 font-mono`}
                >
                  {iface.ip} <span className={`opacity-60 font-sans`}>{iface.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {startHeadMsg && (
          <p className={`text-xs ${startHeadMsg.includes('完了') ? 'text-green-400' : 'text-red-400'}`}>
            {startHeadMsg}
          </p>
        )}

        {/* ワーカー一覧 */}
        {cfg.mode === 'primary' && workers.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {workers.map((w, i) => {
              const pr = pingResults[i]
              return (
                <div key={i} className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs border ${border}`}>
                  <div className={`w-1.5 h-1.5 rounded-full ${
                    pr && pr !== 'loading' && pr.reachable ? 'bg-green-400' : 'bg-gray-500'
                  }`} />
                  <span>{w.label || w.ip}</span>
                  {pr === 'loading'
                    ? <Loader2 size={10} className="animate-spin text-blue-400" />
                    : pr && pr !== 'loading'
                      ? <span className={pr.reachable ? 'text-green-400' : 'text-gray-500'}>
                          {pr.reachable ? `${pr.via === 'ray' ? 'Ray' : 'ICMP'} ${pr.latency_ms}ms` : 'NG'}
                        </span>
                      : null
                  }
                  <button onClick={() => pingWorker(w.ip, i)} className={`${textMuted} hover:text-white`}>
                    <Network size={10} />
                  </button>
                </div>
              )
            })}
          </div>
        )}

        {/* 自動起動トグル */}
        {cfg.mode === 'primary' && (
          <label className={`flex items-center gap-2 text-xs cursor-pointer select-none ${textMuted}`}>
            <input
              type="checkbox"
              checked={cfg.ray?.auto_start ?? false}
              onChange={e => setCfg(c => ({ ...c, ray: { ...c.ray, auto_start: e.target.checked } }))}
              className="accent-blue-500"
            />
            アプリ起動時にRayを自動起動する
          </label>
        )}
      </section>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {/* K10 参加セクション (Ray起動後のみ表示)                                 */}
      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {cfg.mode === 'primary' && (rayRunning || workerCmds.length > 0) && cfg.network?.primary_ip && (
        <section className={`${cardBg} border ${border} rounded-lg p-4 space-y-3`}>
          <h3 className={`text-sm font-semibold ${isLight ? 'text-gray-800' : 'text-gray-200'}`}>
            ワーカーをクラスタに参加させる
          </h3>

          {/* irm ワンライナー */}
          <div className={`p-3 rounded border ${border} ${isLight ? 'bg-blue-50' : 'bg-blue-950/30'}`}>
            <p className={`text-[11px] font-medium mb-1.5 ${isLight ? 'text-blue-700' : 'text-blue-300'}`}>
              K10 の PowerShell でこれだけ打てばOK:
            </p>
            <div className="flex items-center gap-2">
              <code className="text-[11px] font-mono flex-1 break-all text-green-400">
                {`irm http://${cfg.network.primary_ip}:8765/api/cluster/ray/join-script | iex`}
              </code>
              <button
                onClick={() => copyCmd(`irm http://${cfg.network!.primary_ip}:8765/api/cluster/ray/join-script | iex`, -1)}
                className={`shrink-0 ${textMuted} hover:text-white`}
              >
                {copiedIdx === -1 ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
              </button>
            </div>
          </div>

          {/* SSH実行 (ワーカーコマンド生成後) */}
          {workerCmds.length > 0 && (
            <div className="space-y-2">
              <div className={`flex items-center gap-2 p-2 rounded border ${border}`}>
                <span className={`text-[11px] ${textMuted} shrink-0`}>SSH</span>
                <input className={`${inputCls} w-28 text-[11px]`} placeholder="ユーザー名"
                  value={sshUser} onChange={e => setSshUser(e.target.value)} />
                <input type="password" className={`${inputCls} w-28 text-[11px]`} placeholder="パスワード"
                  value={sshPass} onChange={e => setSshPass(e.target.value)} />
              </div>
              {workerCmds.map((w, idx) => (
                <div key={w.ip}>
                  <div className={`flex items-center gap-2 p-2 rounded border ${border} ${isLight ? 'bg-gray-50' : 'bg-gray-900'}`}>
                    <span className={`text-[11px] ${textMuted} shrink-0`}>{w.label}</span>
                    <code className="text-[11px] font-mono flex-1 break-all text-green-400">{w.cmd}</code>
                    <button onClick={() => copyCmd(w.cmd, idx)} className={`shrink-0 ${textMuted} hover:text-white`}>
                      {copiedIdx === idx ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                    </button>
                    <button
                      onClick={() => remoteRayJoin(w.ip, idx)}
                      disabled={remoteJoinLoading[idx]}
                      className="shrink-0 flex items-center gap-1 px-2 py-0.5 text-[11px] rounded bg-indigo-700 hover:bg-indigo-600 text-white disabled:opacity-50"
                    >
                      {remoteJoinLoading[idx] ? <Loader2 size={10} className="animate-spin" /> : <Play size={10} />}
                      SSH実行
                    </button>
                  </div>
                  {remoteJoinMsg[idx] && (
                    <p className={`text-[10px] mt-0.5 ${remoteJoinMsg[idx] === '起動完了' ? 'text-green-400' : 'text-red-400'}`}>
                      {remoteJoinMsg[idx]}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {/* 詳細設定 (折りたたみ)                                                  */}
      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className={`${cardBg} border ${border} rounded-lg overflow-hidden`}>
        <button
          onClick={() => setShowAdvanced(v => !v)}
          className={`w-full flex items-center justify-between px-4 py-3 text-sm font-medium ${
            isLight ? 'text-gray-700 hover:bg-gray-50' : 'text-gray-300 hover:bg-gray-800/50'
          } transition-colors`}
        >
          <span className="flex items-center gap-2">
            <Server size={13} />
            詳細設定（ネットワーク・ワーカー・リソース）
          </span>
          <span className={`text-xs ${textMuted} transition-transform ${showAdvanced ? 'rotate-180' : ''}`}>▼</span>
        </button>

        {showAdvanced && (
          <div className="p-4 space-y-4 border-t border-gray-700/50">

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
            const detecting = detectingWorkers[i] ?? false
            const detectErr = detectErrors[i]
            const rayRunning = status?.ray.status === 'running'
            return (
              <div key={i} className={`flex flex-col gap-1.5 p-2 rounded border ${border}`}>
                <div className="flex items-center gap-2">
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
                    title="疎通確認 (ICMP / Ray)"
                  >
                    {pr === 'loading' ? <Loader2 size={12} className="animate-spin" /> : <Network size={12} />}
                  </button>
                  {pr && pr !== 'loading' && (
                    <span className={`text-[11px] shrink-0 flex items-center gap-0.5 ${pr.reachable ? 'text-green-400' : 'text-red-400'}`}>
                      {pr.reachable ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
                      {pr.reachable
                        ? `${pr.via === 'ray' ? 'Ray' : pr.via === 'icmp' ? 'ICMP' : 'HTTP'} OK${pr.latency_ms ? ` ${pr.latency_ms}ms` : ''}`
                        : 'NG'
                      }
                    </span>
                  )}
                  <button onClick={() => removeWorker(i)} className="text-red-400 hover:text-red-300 shrink-0">
                    <Trash2 size={12} />
                  </button>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`${labelCls} w-16 shrink-0`}>{t('cluster.worker_cpus')}</span>
                  <input type="number" min={1} max={64}
                    className={`${inputCls} w-16`}
                    value={w.num_cpus ?? ''}
                    placeholder="16"
                    onChange={e => updateWorker(i, 'num_cpus', e.target.value as any)}
                  />
                  <span className={`${labelCls} w-16 shrink-0`}>{t('cluster.worker_gpus')}</span>
                  <input type="number" min={0} max={8}
                    className={`${inputCls} w-12`}
                    value={w.num_gpus ?? ''}
                    placeholder="0"
                    onChange={e => updateWorker(i, 'num_gpus', e.target.value as any)}
                  />
                  <input
                    className={inputCls}
                    placeholder="AMD Radeon 780M Graphics"
                    value={w.gpu_label ?? ''}
                    onChange={e => updateWorker(i, 'gpu_label', e.target.value)}
                  />
                  {/* Ray 接続中のみ自動検出ボタンを表示 */}
                  {rayRunning && (
                    <button
                      onClick={() => detectWorkerHardware(w.ip, i)}
                      disabled={detecting || !w.ip}
                      className="flex items-center gap-1 px-2 py-1 text-[11px] rounded bg-purple-700 hover:bg-purple-600 text-white disabled:opacity-50 shrink-0"
                      title={t('cluster.detect_hardware')}
                    >
                      {detecting
                        ? <Loader2 size={11} className="animate-spin" />
                        : <ScanSearch size={11} />}
                      {t('cluster.detect_hardware')}
                    </button>
                  )}
                </div>
                {detectErr && (
                  <p className="text-[11px] text-red-400">{detectErr}</p>
                )}
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

      {/* ── リソース上限 ─────────────────────────────────────────────────── */}
      <section className={sectionCls}>
        <h3 className={`text-sm font-semibold flex items-center gap-2 ${isLight ? 'text-gray-800' : 'text-gray-200'}`}>
          <Zap size={14} /> {t('cluster.resources_section')}
        </h3>
        <p className={`text-[11px] ${textMuted}`}>{t('cluster.limit_auto_hint')}</p>
        <div className="space-y-3">
          {/* ノートPC 固有のスライダー（常時表示） */}
          {[
            { key: 'gpu_vram_limit_gb',   label: t('cluster.gpu_vram_limit'),   max: Math.max(hardware?.vram_total_gb ?? 16, 16) },
            { key: 'system_ram_limit_gb', label: t('cluster.system_ram_limit'), max: Math.max(hardware?.system_ram_gb ?? 32, 16) },
          ].map(({ key, label, max }) => {
            const val = (cfg.resources as any)?.[key] ?? 0
            return (
              <div key={key} className="flex items-center gap-3">
                <span className={`${labelCls} w-44 shrink-0`}>{label}</span>
                <input
                  type="range" min={0} max={max} step={1} value={val}
                  onChange={e => setCfg(c => ({
                    ...c,
                    resources: { ...c.resources, [key]: Number(e.target.value) },
                  }))}
                  className="flex-1 accent-blue-500"
                />
                <span className="text-sm w-12 text-right">
                  {val === 0 ? '自動' : `${val}GB`}
                </span>
              </div>
            )
          })}

          {/* ワーカー別 RAM 上限（Ray 接続中かつワーカーが存在する場合のみ） */}
          {showWorkerRam && workers.map((w, i) => {
            const workerIp = w.ip
            const workerLabel = w.label || w.ip || `Worker ${i + 1}`
            const val = cfg.resources?.workers_ram_limits?.[workerIp] ?? 0
            return (
              <div key={`worker_ram_${workerIp}`} className="flex items-center gap-3">
                <span className={`${labelCls} w-44 shrink-0`}>
                  {t('cluster.worker_ram_limit', { label: workerLabel })}
                </span>
                <input
                  type="range" min={0} max={64} step={1} value={val}
                  onChange={e => updateWorkerRamLimit(workerIp, Number(e.target.value))}
                  className="flex-1 accent-blue-500"
                />
                <span className="text-sm w-12 text-right">
                  {val === 0 ? '自動' : `${val}GB`}
                </span>
              </div>
            )
          })}
        </div>
      </section>

      {/* ── タスク分散設定（Ray 接続中かつ primary モードのみ） ──────────── */}
      {showTaskRouting && (
        <section className={sectionCls}>
          <h3 className={`text-sm font-semibold flex items-center gap-2 ${isLight ? 'text-gray-800' : 'text-gray-200'}`}>
            <Zap size={14} /> {t('cluster.task_routing_section')}
          </h3>
          <div className="space-y-3">
            {taskTypes.map(({ key, label }) => {
              const routingOptions = buildRoutingOptions()
              const currentValue = taskRouting[key] ?? 'auto'
              return (
                <div key={key} className="space-y-1">
                  <span className={`${labelCls}`}>{label}</span>
                  <div className="flex flex-wrap gap-1">
                    {routingOptions.map(opt => (
                      <button
                        key={opt.value}
                        onClick={() => setTaskRouting(r => ({ ...r, [key]: opt.value }))}
                        className={`px-2 py-1 rounded text-xs border transition-colors ${
                          currentValue === opt.value
                            ? 'border-blue-500 bg-blue-600 text-white'
                            : `border-gray-600 ${isLight ? 'text-gray-700 hover:border-gray-400' : 'text-gray-300 hover:border-gray-500'}`
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

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
              {status.ray.status === 'running' ? (
                <button
                  onClick={() => rayStopMutation.mutate()}
                  disabled={rayStopMutation.isPending}
                  className="text-xs px-2 py-0.5 rounded border border-red-600 text-red-400 hover:bg-red-900/30 disabled:opacity-50 flex items-center gap-1"
                >
                  {rayStopMutation.isPending ? <Loader2 size={10} className="animate-spin" /> : null}
                  {rayStopMutation.isPending ? t('cluster.ray_stopping') : t('cluster.ray_stop')}
                </button>
              ) : rayConnecting ? (
                <span className="text-xs px-2 py-0.5 rounded border border-blue-600 text-blue-400 flex items-center gap-1">
                  <Loader2 size={10} className="animate-spin" />
                  {t('cluster.ray_connecting')}
                </span>
              ) : (
                <button
                  onClick={() => rayStartMutation.mutate()}
                  disabled={rayStartMutation.isPending}
                  className="text-xs px-2 py-0.5 rounded border border-blue-600 text-blue-400 hover:bg-blue-900/30 disabled:opacity-50 flex items-center gap-1"
                >
                  {rayStartMutation.isPending ? <Loader2 size={10} className="animate-spin" /> : null}
                  {rayStartMutation.isPending ? t('cluster.ray_starting') : t('cluster.ray_start')}
                </button>
              )}
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
        )}
      </div>

    </div>
  )
}
