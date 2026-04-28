import { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { setLanguage, SUPPORTED_LANGS, type SupportedLang } from '@/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Edit2, Trash2, CheckCircle, CheckCircle2, AlertCircle, Play, Square, Cpu, Zap, ToggleLeft, ToggleRight, Wifi, WifiOff, Share2, Bookmark, Copy, Globe, Power, PowerOff, Download, Upload, HardDrive, FileArchive, Eye, Sun, Moon, ChevronUp, ChevronDown, ChevronsUpDown, Search, X, RotateCcw, Loader2, LogOut, ScrollText } from 'lucide-react'
import QRCode from 'qrcode'
import { apiGet, apiPost, apiPut, apiDelete, newIdempotencyKey } from '@/api/client'
import { Player, TeamHistoryEntry, SharedSession, NetworkDiagnostics } from '@/types'
import { useAuth } from '@/hooks/useAuth'
import { useSettings } from '@/hooks/useSettings'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTheme } from '@/hooks/useTheme'
import { ClusterSettingsPanel } from '@/components/cluster/ClusterSettingsPanel'
import { PasswordChangeCard } from '@/components/auth/PasswordChangeCard'
import { DeviceSelector } from '@/components/benchmark/DeviceSelector'
import { TargetSelector } from '@/components/benchmark/TargetSelector'
import { ResultMatrix } from '@/components/benchmark/ResultMatrix'
import { BenchmarkProgress } from '@/components/benchmark/BenchmarkProgress'
import {
  getDevices,
  runBenchmark,
  cancelJob,
  getJob,
  ComputeDevice,
  BenchmarkJob,
  BenchmarkTarget,
} from '@/api/benchmark'
import { getDbStats, runDbMaintenance, setAutoVacuum, DbStats } from '@/api/db'

type PlayerSortKey = 'name' | 'team' | 'nationality' | 'world_ranking' | 'is_target'
type BenchmarkItem = { fps: number; avg_ms: number; p95_ms: number; backend: string; samples: number } | { error: string }

interface PlayerFormData {
  name: string
  name_en: string
  team: string
  nationality: string
  dominant_hand: 'R' | 'L'
  birth_year: string
  world_ranking: string
  is_target: boolean
  notes: string
}

const defaultPlayerForm = (): PlayerFormData => ({
  name: '',
  name_en: '',
  team: '',
  nationality: '',
  dominant_hand: 'R',
  birth_year: '',
  world_ranking: '',
  is_target: false,
  notes: '',
})

/** URL + QRコード + コピーボタンをまとめた小コンポーネント */
function LanUrlCard({ url, hint }: { url: string; hint: string }) {
  const { t } = useTranslation()

  const isLight = useIsLightMode()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!canvasRef.current || !url) return
    QRCode.toCanvas(canvasRef.current, url, {
      width: 140,
      margin: 1,
      color: {
        dark: isLight ? '#1e293b' : '#0f172a',
        light: isLight ? '#ffffff' : '#f8fafc',
      },
    }).catch(() => {})
  }, [url, isLight])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = url
      ta.style.cssText = 'position:fixed;opacity:0;'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex items-start gap-3">
      <canvas ref={canvasRef} className={`rounded flex-shrink-0 ${isLight ? 'border border-gray-200' : ''}`} />
      <div className="min-w-0 space-y-1.5">
        <p className={`text-xs ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>{hint}</p>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-mono ${isLight ? 'text-green-700' : 'text-green-300'} break-all`}>{url}</span>
          <button
            onClick={handleCopy}
            className={`flex-shrink-0 p-1 rounded ${isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
            title={t('auto.SettingsPage.k21')}
          >
            {copied ? <CheckCircle size={12} className="text-green-500" /> : <Copy size={12} />}
          </button>
        </div>
      </div>
    </div>
  )
}

export function SettingsPage() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const { role, teamName, displayName, userId, clearRole } = useAuth()

  const { data: healthData } = useQuery<{ public_mode?: boolean }>({
    queryKey: ['health'],
    queryFn: () => apiGet('/health'),
    staleTime: 60_000,
  })
  const isPublicMode = healthData?.public_mode === true

  const [showPlayerForm, setShowPlayerForm] = useState(false)
  const [editingPlayer, setEditingPlayer] = useState<Player | null>(null)
  const [playerForm, setPlayerForm] = useState<PlayerFormData>(defaultPlayerForm())
  const [activeTab, setActiveTab] = useState<'players' | 'review' | 'tracknet' | 'sharing' | 'data' | 'cluster' | 'account'>(() => ((role === 'analyst' || role === 'coach' || role === 'admin') ? 'players' : 'account'))
  // 選手ロールは 選手管理・要レビュー タブを閲覧不可（個人情報保護）
  // コーチロールは自チーム選手のみ管理可能
  // adminロールは全選手を管理可能
  const canManagePlayers = role === 'analyst' || role === 'coach' || role === 'admin'
  const coachTeamFilter = role === 'coach' ? (teamName ?? '') : null
  // ロール切替用モーダル
  // ロール変更で閲覧権限が失われた場合はタブを退避
  useEffect(() => {
    if (!canManagePlayers && (activeTab === 'players' || activeTab === 'review')) {
      setActiveTab('account')
    }
    if (role !== 'admin' && (activeTab === 'tracknet' || activeTab === 'sharing' || activeTab === 'cluster')) {
      setActiveTab('data')
    }
  }, [canManagePlayers, role, activeTab])

  // 選手リスト: 検索・ソート（クライアントサイド、端末ごとに独立）
  const playerSearchRef = useRef<HTMLInputElement>(null)
  const [playerSearch, setPlayerSearch] = useState('')
  const [targetOnly, setTargetOnly] = useState(false)
  // ソート状態は端末ごとに localStorage に永続化
  const [playerSortKey, setPlayerSortKey] = useState<PlayerSortKey>(
    () => (localStorage.getItem('shuttlescope.playerSort.key') as PlayerSortKey) ?? 'name'
  )
  const [playerSortDir, setPlayerSortDir] = useState<'asc' | 'desc'>(
    () => (localStorage.getItem('shuttlescope.playerSort.dir') as 'asc' | 'desc') ?? 'asc'
  )
  // インライン削除確認中の選手ID
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
  // クリップボードコピー済みの選手ID（一時表示用）
  const [copiedPlayerId, setCopiedPlayerId] = useState<number | null>(null)
  const { settings: appSettings, updateSettings, loading: settingsLoading } = useSettings()
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null)
  const navigate = useNavigate()

  async function handleLogout() {
    try {
      await apiPost('/auth/logout', {})
    } catch {
      // continue and clear the client session even if logout logging fails
    } finally {
      clearRole()
      navigate('/', { replace: true })
    }
  }

  // データ管理タブ用状態
  const [exportMatchIds, setExportMatchIds] = useState<string>('')
  const [exportSince, setExportSince] = useState<string>('')
  const [exportMode, setExportMode] = useState<'match' | 'change_set'>('match')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPreview, setImportPreview] = useState<any>(null)
  const [importPreviewLoading, setImportPreviewLoading] = useState(false)
  const [importResult, setImportResult] = useState<any>(null)
  const [importRunning, setImportRunning] = useState(false)
  const [backupResult, setBackupResult] = useState<string | null>(null)
  const [backupRunning, setBackupRunning] = useState(false)

  // CV ベンチマーク（旧）
  const [benchmarkRunning, setBenchmarkRunning] = useState(false)
  const [benchmarkResult, setBenchmarkResult] = useState<{ yolo: BenchmarkItem; tracknet: BenchmarkItem; tracking?: BenchmarkItem } | null>(null)

  // 新ベンチマーク UI 用ステート
  const [bmDevices, setBmDevices] = useState<ComputeDevice[]>([])
  const [bmSelectedDevices, setBmSelectedDevices] = useState<string[]>([])
  const [bmTargets, setBmTargets] = useState<BenchmarkTarget[]>(['tracknet'])
  const [bmNFrames, setBmNFrames] = useState(30)
  const [bmJobId, setBmJobId] = useState<string | null>(null)
  const bmJobIdRef = useRef<string | null>(null)
  const [bmJob, setBmJob] = useState<BenchmarkJob | null>(null)
  const [bmRunning, setBmRunning] = useState(false)
  const [bmDetecting, setBmDetecting] = useState(false)
  const [bmError, setBmError] = useState<string | null>(null)
  const [cvBatchConfirm, setCvBatchConfirm] = useState<{
    label: string
    estimatedHours: number
    onConfirm: () => void
  } | null>(null)

  // 選手一覧取得
  const { data: playersData } = useQuery({
    queryKey: ['players'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players'),
  })

  // V4-U-003: 要レビュー選手取得
  const { data: reviewPlayersData } = useQuery({
    queryKey: ['players-needs-review'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players/needs_review'),
    enabled: activeTab === 'review',
  })

  // TrackNetモデルステータス取得
  const { data: tracknetStatus } = useQuery({
    queryKey: ['tracknet-status'],
    queryFn: () => apiGet<{ success: boolean; data: { available: boolean; backend: string | null; loaded: boolean } }>('/tracknet/status'),
    enabled: activeTab === 'tracknet',
    refetchInterval: activeTab === 'tracknet' ? 5000 : false,
  })

  // YOLO モデルステータス取得
  const { data: yoloStatus } = useQuery({
    queryKey: ['yolo-status'],
    queryFn: () => apiGet<{ success: boolean; data: { available: boolean; backend: string | null; loaded: boolean; status_code: string; status_message: string | null; install_hint: string | null } }>('/yolo/status'),
    enabled: activeTab === 'tracknet',
    refetchInterval: activeTab === 'tracknet' ? 10000 : false,
  })

  // GPU / コンピュートデバイス検出
  const { data: computeDevices, refetch: refetchDevices, isFetching: devicesFetching } = useQuery({
    queryKey: ['compute-devices'],
    queryFn: () => apiGet<{
      success: boolean
      cuda_devices: { index: number; name: string; vram_mb: number }[]
      openvino_devices: string[]
      onnx_providers: string[]
    }>('/settings/devices'),
    enabled: activeTab === 'tracknet',
    staleTime: 60_000,
  })

  // R-002: サーバー情報（LAN IP）
  const { data: serverInfo, refetch: refetchServerInfo } = useQuery({
    queryKey: ['server-my-info'],
    queryFn: () => apiGet<{ success: boolean; data: { lan_ips: string[]; port: number; lan_mode: boolean; accessible: boolean } }>('/sessions/my-info'),
    enabled: activeTab === 'sharing',
  })

  // Q-002/Q-008: ネットワーク診断
  const { data: netDiag, isFetching: netDiagFetching, refetch: runDiagnostics } = useQuery({
    queryKey: ['network-diagnostics'],
    queryFn: () => apiGet<{ success: boolean; data: NetworkDiagnostics }>('/network/diagnostics'),
    enabled: false,
    retry: false,
  })

  const toggleLanMode = useMutation({
    mutationFn: (enable: boolean) => apiPost('/network/lan-mode?enable=' + enable, {}),
    onSuccess: () => { refetchServerInfo() },
  })

  // リモートトンネル ステータス
  const { data: tunnelStatus, refetch: refetchTunnel } = useQuery({
    queryKey: ['tunnel-status'],
    queryFn: () => apiGet<{
      success: boolean
      data: {
        available: boolean
        running: boolean
        url: string | null
        active_provider: 'cloudflare' | 'ngrok' | null
        providers: {
          cloudflare: {
            available: boolean
            named_ready?: boolean
            hostname?: string | null
            config_path?: string | null
            reason?: string | null
          }
          ngrok: { available: boolean }
        }
        recent_log: string[]
        ngrok_authtoken_from_env: boolean
      }
    }>('/tunnel/status'),
    enabled: activeTab === 'sharing',
    refetchInterval: activeTab === 'sharing' ? 3000 : false,
  })

  const tunnelStart = useMutation({
    mutationFn: () => apiPost(`/tunnel/start?provider=${appSettings.tunnel_provider}`, {}),
    onSuccess: () => { refetchTunnel() },
  })

  const tunnelStop = useMutation({
    mutationFn: () => apiPost('/tunnel/stop', {}),
    onSuccess: () => { refetchTunnel() },
  })

  const turnTest = useMutation({
    mutationFn: () => apiPost<{ success: boolean; data?: { host: string; port: number; reachable: boolean }; error?: string }>('/webrtc/test-turn', {}),
  })

  // データ管理: バックアップ一覧
  const { data: backupsData, refetch: refetchBackups } = useQuery({
    queryKey: ['sync-backups'],
    queryFn: () => apiGet<{ success: boolean; data: Array<{ filename: string; size_bytes: number; created_at: string }> }>('/sync/backups'),
    enabled: activeTab === 'data',
  })

  // データ管理: 試合一覧（エクスポート用）
  const { data: matchesForExport } = useQuery({
    queryKey: ['matches-for-export'],
    queryFn: () => apiGet<{ data: Array<{ id: number; date: string; tournament: string; result: string }> }>('/matches'),
    enabled: activeTab === 'data',
  })
  const exportMatchList = (matchesForExport as any)?.data ?? []

  // 競合レビュー一覧
  const { data: conflictsData, refetch: refetchConflicts } = useQuery({
    queryKey: ['sync-conflicts'],
    queryFn: () => apiGet<{ success: boolean; data: Array<{ id: number; record_table: string; record_uuid: string; import_device: string; import_updated_at: string; local_updated_at: string; reason: string; created_at: string }> }>('/sync/conflicts'),
    enabled: activeTab === 'data',
  })
  const conflicts = (conflictsData as any)?.data ?? []

  async function runCvBenchmark() {
    setBenchmarkRunning(true)
    setBenchmarkResult(null)
    try {
      const res = await apiPost<{ success: boolean; data: { yolo: BenchmarkItem; tracknet: BenchmarkItem; tracking?: BenchmarkItem } }>('/cv/benchmark', {})
      if (res.success) setBenchmarkResult(res.data)
    } catch (_e) {
      // ignore
    } finally {
      setBenchmarkRunning(false)
    }
  }

  // ─── 新ベンチマーク関数 ───────────────────────────────────────────────────────

  /** デバイス一覧を取得してステートに反映する */
  async function fetchBmDevices() {
    setBmDetecting(true)
    setBmError(null)
    try {
      const devs = await getDevices()
      setBmDevices(devs)
      setBmSelectedDevices(devs.filter((d) => d.available).map((d) => d.device_id))
    } catch (_e) {
      setBmError('デバイス取得に失敗しました')
    } finally {
      setBmDetecting(false)
    }
  }

  /** ベンチマークジョブを開始する */
  async function startBenchmark() {
    if (bmSelectedDevices.length === 0 || bmTargets.length === 0) return
    setBmRunning(true)
    setBmJob(null)
    setBmJobId(null)
    bmJobIdRef.current = null
    setBmError(null)
    try {
      const jobId = await runBenchmark(bmSelectedDevices, bmTargets, bmNFrames)
      bmJobIdRef.current = jobId
      setBmJobId(jobId)
    } catch (_e) {
      setBmError('ベンチマーク開始に失敗しました')
      setBmRunning(false)
    }
  }

  /** ベンチマークジョブを停止する */
  async function stopBenchmark() {
    // ref を使って最新の jobId を確実に参照する（state の非同期更新による race condition を回避）
    const jobId = bmJobIdRef.current ?? bmJobId
    if (jobId) {
      try {
        await cancelJob(jobId)
      } catch (_e) {
        // キャンセル失敗は無視
      }
    }
    bmJobIdRef.current = null
    setBmRunning(false)
    setBmJobId(null)
  }

  /** ポーリング時にジョブ状態を取得する */
  async function pollBmJob() {
    if (!bmJobId) return
    try {
      const job = await getJob(bmJobId)
      setBmJob(job)
      if (job.status === 'done' || job.status === 'failed') {
        setBmRunning(false)
      }
    } catch (_e) {
      // ポーリングエラーは無視して次のポーリングに任せる
    }
  }

  // バッチ fps 選択時に処理時間を試算し、長い場合は確認ダイアログを出す
  // measuredFps: ベンチマーク実測値（未計測なら保守的デフォルト）
  function selectBatchFps(
    label: string,
    selectedFps: number,
    measuredFps: number | null,
    defaultMeasured: number,
    onApply: (v: number) => void,
  ) {
    const m = measuredFps ?? defaultMeasured
    const estimatedHours = selectedFps / m  // 動画1時間あたりの処理時間（時間）
    if (estimatedHours > 0.5) {
      setCvBatchConfirm({
        label,
        estimatedHours,
        onConfirm: () => { onApply(selectedFps); setCvBatchConfirm(null) },
      })
    } else {
      onApply(selectedFps)
    }
  }

  async function resolveConflict(id: number, resolution: 'keep_local' | 'use_incoming') {
    await fetch(`/api/sync/conflicts/${id}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolution }),
    })
    refetchConflicts()
    queryClient.invalidateQueries()
  }

  // DB ステータス
  const { data: dbStats, refetch: refetchDbStats } = useQuery<DbStats>({
    queryKey: ['db-stats'],
    queryFn: () => getDbStats() as Promise<DbStats>,
    enabled: activeTab === 'data',
    refetchInterval: activeTab === 'data' ? 30000 : false,
  })
  const [dbMaintRunning, setDbMaintRunning] = useState(false)
  const [dbMaintResult, setDbMaintResult] = useState<{ freed_mb: number; freed_pages: number } | null>(null)
  const [dbAvRunning, setDbAvRunning] = useState(false)
  const [dbAvMessage, setDbAvMessage] = useState<string | null>(null)

  // クラウドフォルダ内パッケージ一覧
  const { data: cloudPackagesData, refetch: refetchCloudPackages } = useQuery({
    queryKey: ['sync-cloud-packages'],
    queryFn: () => apiGet<{ success: boolean; data: Array<{ filename: string; path: string; size_bytes: number; modified_at: string }>; configured: boolean; folder: string }>('/sync/cloud/packages'),
    enabled: activeTab === 'data',
  })
  const cloudPackages = (cloudPackagesData as any)?.data ?? []
  const cloudFolderConfigured = (cloudPackagesData as any)?.configured ?? false

  async function handleSetAutoVacuum(mode: 'incremental' | 'off') {
    setDbAvRunning(true)
    setDbAvMessage(null)
    try {
      const res = await setAutoVacuum(mode) as any
      setDbAvMessage(res.message ?? (res.error ? `エラー: ${res.error}` : '完了'))
      refetchDbStats()
    } catch (e) {
      setDbAvMessage('設定に失敗しました')
    } finally {
      setDbAvRunning(false)
    }
  }

  // JSON パッケージ インポート
  const [pkgImportFile, setPkgImportFile] = useState<File | null>(null)
  const [pkgImportRunning, setPkgImportRunning] = useState(false)
  const [pkgImportResult, setPkgImportResult] = useState<{ success: boolean; message: string } | null>(null)

  async function handlePkgImport(force = false) {
    if (!pkgImportFile) return
    setPkgImportRunning(true)
    setPkgImportResult(null)
    try {
      const text = await pkgImportFile.text()
      const res = await fetch(`/api/import/package${force ? '?force=true' : ''}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: text,
      })
      const data = await res.json()
      if (data.conflict) {
        setPkgImportResult({ success: false, message: `既存試合と競合: force=true で上書きできます。` })
      } else if (data.success) {
        setPkgImportResult({ success: true, message: `インポート完了: ラリー ${data.rallies_imported} 件、ストローク ${data.strokes_imported} 件` })
        setPkgImportFile(null)
      } else {
        setPkgImportResult({ success: false, message: data.detail ?? 'インポートに失敗しました' })
      }
    } catch (e) {
      setPkgImportResult({ success: false, message: 'ネットワークエラーが発生しました' })
    } finally {
      setPkgImportRunning(false)
    }
  }

  async function handleDbMaintenance() {
    setDbMaintRunning(true)
    setDbMaintResult(null)
    try {
      const res = await runDbMaintenance()
      setDbMaintResult({ freed_mb: (res as any).freed_mb ?? 0, freed_pages: (res as any).freed_pages ?? 0 })
      refetchDbStats()
    } catch (e) {
      setDbMaintResult({ freed_mb: 0, freed_pages: 0 })
    } finally {
      setDbMaintRunning(false)
    }
  }

  async function handleExportMatch() {
    if (exportMode === 'change_set') {
      if (!exportSince.trim()) return
      const url = `/api/sync/export/change_set?since=${encodeURIComponent(exportSince)}`
      window.open(url, '_blank')
    } else {
      if (!exportMatchIds.trim()) return
      const url = `/api/sync/export/match?match_ids=${encodeURIComponent(exportMatchIds.trim())}`
      window.open(url, '_blank')
    }
  }

  async function handlePreviewImport() {
    if (!importFile) return
    setImportPreviewLoading(true)
    setImportPreview(null)
    try {
      const form = new FormData()
      form.append('file', importFile)
      const resp = await fetch('/api/sync/preview', { method: 'POST', body: form })
      const json = await resp.json()
      setImportPreview(json)
    } catch {
      setImportPreview({ success: false, error: '通信エラー' })
    } finally {
      setImportPreviewLoading(false)
    }
  }

  async function handleImport() {
    if (!importFile) return
    setImportRunning(true)
    setImportResult(null)
    try {
      const form = new FormData()
      form.append('file', importFile)
      const resp = await fetch('/api/sync/import', { method: 'POST', body: form })
      const json = await resp.json()
      setImportResult(json)
      queryClient.invalidateQueries()
    } catch {
      setImportResult({ success: false, error: '通信エラー' })
    } finally {
      setImportRunning(false)
    }
  }

  async function handleBackup() {
    setBackupRunning(true)
    setBackupResult(null)
    try {
      const resp = await fetch('/api/sync/backup', { method: 'POST' })
      const json = await resp.json()
      setBackupResult(json.success ? json.data?.filename ?? '完了' : 'エラー')
      refetchBackups()
    } catch {
      setBackupResult('通信エラー')
    } finally {
      setBackupRunning(false)
    }
  }

  // 選手作成
  const createPlayer = useMutation({
    mutationFn: (body: any) => apiPost('/players', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['players'] })
      setShowPlayerForm(false)
      setPlayerForm(defaultPlayerForm())
    },
  })

  // 選手更新
  const updatePlayer = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) => apiPut(`/players/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['players'] })
      setShowPlayerForm(false)
      setEditingPlayer(null)
      setPlayerForm(defaultPlayerForm())
    },
    onError: (err: any) => {
      let detail = ''
      try { detail = JSON.parse(err.message)?.detail ?? '' } catch { detail = err.message ?? '' }
      alert(`保存に失敗しました (HTTP ${err.status ?? '?'}):\n${detail || '不明なエラー'}`)
    },
  })

  // 選手削除
  const deletePlayer = useMutation({
    mutationFn: (id: number) =>
      apiDelete(`/players/${id}`, { 'X-Idempotency-Key': newIdempotencyKey() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['players'] }),
    onError: (err: any, playerId: number) => {
      // err.message はサーバーが返したJSONテキスト ("{"detail":"..."}") or プレーンテキスト
      let detail = ''
      try { detail = JSON.parse(err.message)?.detail ?? '' } catch { detail = err.message ?? '' }
      const isReferenced = (err as any).status === 409
      if (isReferenced) {
        const go = window.confirm(`${detail}\n\n試合一覧でこの選手の試合を確認しますか？`)
        if (go) navigate(`/matches?player_id=${playerId}`)
      } else {
        alert(`削除できません: ${detail || '不明なエラー'}`)
      }
    },
  })

  // V4-U-003: 選手を「確認済み」にする
  const markVerified = useMutation({
    mutationFn: (id: number) =>
      apiPut(`/players/${id}`, { profile_status: 'verified', needs_review: false }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['players'] })
      queryClient.invalidateQueries({ queryKey: ['players-needs-review'] })
    },
    onError: (err: any) => {
      let detail = ''
      try { detail = JSON.parse(err.message)?.detail ?? '' } catch { detail = err.message ?? '' }
      alert(`確認済み設定に失敗しました: ${detail || '不明なエラー'}`)
    },
  })

  const handlePlayerSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // 空文字フィールドは null として明示送信する（undefined にすると JSON から省略され
    // バックエンドが exclude_none で無視してしまい、意図した上書きができない）
    const strOrNull = (v: string) => v.trim() !== '' ? v.trim() : null
    const body = {
      name: playerForm.name,
      name_en: strOrNull(playerForm.name_en),
      team: strOrNull(playerForm.team),
      nationality: strOrNull(playerForm.nationality),
      dominant_hand: playerForm.dominant_hand,
      birth_year: playerForm.birth_year ? Number(playerForm.birth_year) : null,
      world_ranking: playerForm.world_ranking ? Number(playerForm.world_ranking) : null,
      is_target: playerForm.is_target,
      notes: strOrNull(playerForm.notes),
    }

    if (editingPlayer) {
      updatePlayer.mutate({ id: editingPlayer.id, body })
    } else {
      createPlayer.mutate(body)
    }
  }

  const openEdit = (player: Player) => {
    setEditingPlayer(player)
    setPlayerForm({
      name: player.name,
      name_en: player.name_en ?? '',
      team: player.team ?? '',
      nationality: player.nationality ?? '',
      dominant_hand: (player.dominant_hand === 'R' || player.dominant_hand === 'L') ? player.dominant_hand : 'R',
      birth_year: player.birth_year ? String(player.birth_year) : '',
      world_ranking: player.world_ranking ? String(player.world_ranking) : '',
      is_target: player.is_target,
      notes: player.notes ?? '',
    })
    setShowPlayerForm(true)
  }

  const players = playersData?.data ?? []

  // 選手リスト: クライアントサイドフィルタ＋ソート
  // サーバはソート前の状態を保持し、各端末が独立してソートを行う
  const filteredPlayers = useMemo(() => {
    const q = playerSearch.trim().toLowerCase()
    const filtered = players.filter((p) => {
      if (coachTeamFilter !== null && (p.team ?? '') !== coachTeamFilter) return false
      if (targetOnly && !p.is_target) return false
      if (!q) return true
      return (
        p.name.toLowerCase().includes(q) ||
        (p.name_en ?? '').toLowerCase().includes(q) ||
        (p.team ?? '').toLowerCase().includes(q) ||
        (p.nationality ?? '').toLowerCase().includes(q)
      )
    })

    return [...filtered].sort((a, b) => {
      let cmp = 0
      if (playerSortKey === 'name') {
        cmp = a.name.localeCompare(b.name, 'ja')
      } else if (playerSortKey === 'team') {
        cmp = (a.team ?? '').localeCompare(b.team ?? '', 'ja')
      } else if (playerSortKey === 'nationality') {
        cmp = (a.nationality ?? '').localeCompare(b.nationality ?? '', 'ja')
      } else if (playerSortKey === 'world_ranking') {
        // ランキングなし（null/undefined）は末尾
        const ra = a.world_ranking ?? Infinity
        const rb = b.world_ranking ?? Infinity
        cmp = ra - rb
      } else if (playerSortKey === 'is_target') {
        // 解析対象(true)を先頭
        cmp = (b.is_target ? 1 : 0) - (a.is_target ? 1 : 0)
      }
      return playerSortDir === 'asc' ? cmp : -cmp
    })
  }, [players, playerSearch, targetOnly, playerSortKey, playerSortDir, coachTeamFilter])

  // カラムヘッダークリックでソートキー切替（同じキーなら昇降反転）端末ごとに localStorage に保存
  function handlePlayerSort(key: PlayerSortKey) {
    if (playerSortKey === key) {
      const next = playerSortDir === 'asc' ? 'desc' : 'asc'
      setPlayerSortDir(next)
      localStorage.setItem('shuttlescope.playerSort.dir', next)
    } else {
      setPlayerSortKey(key)
      setPlayerSortDir('asc')
      localStorage.setItem('shuttlescope.playerSort.key', key)
      localStorage.setItem('shuttlescope.playerSort.dir', 'asc')
    }
  }

  // 選手名クリップボードコピー
  async function copyPlayerName(p: Player) {
    try {
      await navigator.clipboard.writeText(p.name)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = p.name
      ta.style.cssText = 'position:fixed;opacity:0'
      document.body.appendChild(ta); ta.select(); document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopiedPlayerId(p.id)
    setTimeout(() => setCopiedPlayerId((prev) => (prev === p.id ? null : prev)), 1500)
  }

  // `/` キーで検索バーにフォーカス（選手タブのみ）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (activeTab !== 'players') return
      if (e.key === '/' && document.activeElement === document.body) {
        e.preventDefault()
        playerSearchRef.current?.focus()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [activeTab])

  // Esc で選手フォームモーダルを閉じる
  useEffect(() => {
    if (!showPlayerForm) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setShowPlayerForm(false); setEditingPlayer(null) }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [showPlayerForm])

  const { card, textHeading, textSecondary, textMuted, textFaint, isLight } = useCardTheme()
  const { theme, setTheme } = useTheme()
  const bodyBg = isLight ? 'bg-gray-50' : 'bg-gray-900'
  const borderLine = isLight ? 'border-gray-200' : 'border-gray-700'
  const inputClass = isLight
    ? 'bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900'
    : 'bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white'

  return (
    <div className={`flex flex-col h-full ${bodyBg} ${isLight ? 'text-gray-900' : 'text-white'}`}>
      {/* CV バッチ fps 確認ダイアログ */}
      {cvBatchConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className={`rounded-xl p-6 max-w-sm w-full mx-4 space-y-4 border ${isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-600'}`}>
            <p className="text-sm font-medium">{cvBatchConfirm.label} — 処理時間の目安</p>
            <p className={`text-sm ${isLight ? 'text-gray-700' : 'text-gray-300'}`}>
              動画1時間あたり約{' '}
              <span className="text-yellow-400 font-bold">
                {cvBatchConfirm.estimatedHours >= 1
                  ? `${cvBatchConfirm.estimatedHours.toFixed(1)} 時間`
                  : `${Math.round(cvBatchConfirm.estimatedHours * 60)} 分`}
              </span>{' '}
              の処理が見込まれます。
            </p>
            <p className={`text-xs ${isLight ? 'text-gray-500' : 'text-gray-500'}`}>
              バックグラウンドで実行されるため、処理中もアノテーション作業は継続できます。
            </p>
            <div className="flex gap-3">
              <button
                onClick={cvBatchConfirm.onConfirm}
                className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium text-white"
              >
                OK（この設定で進める）
              </button>
              <button
                onClick={() => setCvBatchConfirm(null)}
                className={`flex-1 py-2 rounded text-sm ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-700' : 'bg-gray-700 hover:bg-gray-600 text-white'}`}
              >
                キャンセル
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ヘッダー */}
      <div className={`px-6 py-4 border-b ${borderLine}`}>
        <h1 className={`text-xl font-semibold ${textHeading}`}>{t('nav.settings')}</h1>
      </div>

      {/* タブ（horizontal scroll: モバイル対応） */}
      <div className={`relative border-b ${borderLine}`}>
        <div className="flex overflow-x-auto scrollbar-hide">
          {([
            ...(canManagePlayers ? [
              { key: 'players' as const, label: t('auto.SettingsPage.k31') },
              { key: 'review' as const, label: t('review.title'), badge: reviewPlayersData?.data?.length ?? 0 },
            ] : []),
            ...(role === 'admin' && !isPublicMode ? [
              { key: 'tracknet' as const, label: t('tracknet.tab_label') },
              { key: 'sharing' as const, label: t('sharing.tab_label') },
            ] : []),
            { key: 'data' as const, label: t('auto.SettingsPage.k32') },
            ...(role === 'admin' && !isPublicMode ? [
              { key: 'cluster' as const, label: t('cluster.tab') },
            ] : []),
            { key: 'account' as const, label: t('auto.SettingsPage.k33') },
          ]).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as any)}
              className={`flex-shrink-0 flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                activeTab === tab.key
                  ? 'border-blue-500 text-blue-400'
                  : `border-transparent ${textMuted} ${isLight ? 'hover:text-gray-900' : 'hover:text-white'}`
              }`}
            >
              {tab.label}
              {'badge' in tab && (tab.badge ?? 0) > 0 && (
                <span className="inline-flex items-center justify-center w-4 h-4 text-[10px] bg-orange-500 text-white rounded-full">
                  {tab.badge}
                </span>
              )}
            </button>
          ))}
        </div>
        {/* 右端フェードアウト */}
        <div className={`absolute right-0 top-0 h-full w-8 pointer-events-none ${
          isLight ? 'bg-gradient-to-l from-white to-transparent' : 'bg-gradient-to-l from-gray-900 to-transparent'
        }`} />
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {/* 選手管理タブ */}
        {activeTab === 'players' && (
          <div>
            {/* ヘッダー行: タイトル＋追加ボタン */}
            <div className="flex items-center justify-between mb-3">
              <h2 className={`text-lg font-medium ${textHeading}`}>{t('settings.ui.player_list')}</h2>
              <button
                onClick={() => { setEditingPlayer(null); setPlayerForm(defaultPlayerForm()); setShowPlayerForm(true) }}
                className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-sm"
              >
                <Plus size={14} />
                {t('settings.ui.add_player')}
              </button>
            </div>

            {/* 検索・フィルタ行 */}
            <div className="flex flex-wrap items-center gap-2 mb-3">
              {/* テキスト検索 */}
              <div className="relative flex-1 min-w-[180px]">
                <Search size={13} className={`absolute left-2.5 top-1/2 -translate-y-1/2 ${textMuted} pointer-events-none`} />
                <input
                  ref={playerSearchRef}
                  type="text"
                  value={playerSearch}
                  onChange={(e) => setPlayerSearch(e.target.value)}
                  placeholder={t('player.search_placeholder')}
                  className={`w-full pl-8 pr-7 py-1.5 text-sm rounded ${inputClass}`}
                />
                {playerSearch && (
                  <button
                    onClick={() => setPlayerSearch('')}
                    className={`absolute right-2 top-1/2 -translate-y-1/2 ${textMuted} hover:opacity-80`}
                    aria-label={t('auto.SettingsPage.k30')}
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              {/* 解析対象のみフィルタ */}
              <label className={`flex items-center gap-1.5 text-sm cursor-pointer select-none ${textSecondary}`}>
                <input
                  type="checkbox"
                  checked={targetOnly}
                  onChange={(e) => setTargetOnly(e.target.checked)}
                  className="accent-blue-500"
                />
                {t('player.target_only')}
              </label>

              {/* 件数表示 */}
              <span className={`text-xs ${textMuted} ml-auto`}>
                {filteredPlayers.length}{t('player.count_suffix')}
                {filteredPlayers.length !== players.length && ` / ${players.length}${t('player.count_suffix')}`}
              </span>
            </div>

            {/* テーブル */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className={`sticky top-0 z-10 ${bodyBg}`}>
                  <tr className={`${textSecondary} border-b ${borderLine}`}>
                    {/* ソート可能カラム共通ヘルパー */}
                    {(
                      [
                        { key: 'name', label: t('auto.SettingsPage.k34') },
                        { key: 'team', label: t('auto.SettingsPage.k35') },
                        { key: 'nationality', label: t('auto.SettingsPage.k36') },
                      ] as { key: PlayerSortKey; label: string }[]
                    ).map(({ key, label }) => (
                      <th
                        key={key}
                        className="text-left py-2 pr-3 whitespace-nowrap cursor-pointer select-none hover:opacity-80"
                        onClick={() => handlePlayerSort(key)}
                      >
                        <span className="inline-flex items-center gap-0.5">
                          {label}
                          {playerSortKey === key ? (
                            playerSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                          ) : (
                            <ChevronsUpDown size={12} className="opacity-30" />
                          )}
                        </span>
                      </th>
                    ))}
                    {/* 手（ソートなし） */}
                    <th className="text-left py-2 pr-3 whitespace-nowrap">{t('settings.ui.hand')}</th>
                    {/* Rk: ソート可能 */}
                    <th
                      className="text-left py-2 pr-3 whitespace-nowrap cursor-pointer select-none hover:opacity-80"
                      onClick={() => handlePlayerSort('world_ranking')}
                    >
                      <span className="inline-flex items-center gap-0.5">
                        Rk
                        {playerSortKey === 'world_ranking' ? (
                          playerSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                        ) : (
                          <ChevronsUpDown size={12} className="opacity-30" />
                        )}
                      </span>
                    </th>
                    {/* 対象: ソート可能 */}
                    <th
                      className="text-left py-2 pr-3 whitespace-nowrap cursor-pointer select-none hover:opacity-80"
                      onClick={() => handlePlayerSort('is_target')}
                    >
                      <span className="inline-flex items-center gap-0.5">
                        {t('settings.ui.target')}
                        {playerSortKey === 'is_target' ? (
                          playerSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                        ) : (
                          <ChevronsUpDown size={12} className="opacity-30" />
                        )}
                      </span>
                    </th>
                    <th className="text-left py-2 whitespace-nowrap">{t('settings.ui.operation')}</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPlayers.map((p) => (
                    <tr key={p.id} className={`border-b ${isLight ? 'border-gray-100 hover:bg-gray-50' : 'border-gray-800 hover:bg-gray-800/50'}`}>
                      <td className="pr-4">
                        {/* 行高さを name_en 有無に関わらず統一: min-h で2行分確保し中央寄せ */}
                        <div className="flex flex-col justify-center min-h-[3.25rem] py-1">
                          {/* 名前クリックでクリップボードコピー */}
                          <button
                            type="button"
                            onClick={() => copyPlayerName(p)}
                            className="text-left group flex items-center gap-1.5"
                            title={t('auto.SettingsPage.k22')}
                          >
                            <span>{p.name}</span>
                            {copiedPlayerId === p.id ? (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500 text-white border border-white font-medium">
                                コピー済
                              </span>
                            ) : (
                              <span className={`text-[10px] opacity-0 group-hover:opacity-60 transition-opacity ${textMuted}`}>
                                コピー
                              </span>
                            )}
                          </button>
                          {p.name_en && <div className="text-xs text-gray-500 mt-0.5 leading-snug">{p.name_en}</div>}
                        </div>
                      </td>
                      <td className={`py-2 pr-4 ${textSecondary}`}>
                        <div className="flex items-center gap-1.5">
                          <span>{p.team ?? '-'}</span>
                          {p.team_history && p.team_history.length > 0 && (
                            <span
                              title={p.team_history.map(h => `${h.team}${h.until ? ` (〜${h.until})` : ''}`).join(' → ')}
                              className="text-[10px] px-1 rounded bg-gray-600/50 text-gray-400 cursor-default"
                            >
                              履歴{p.team_history.length}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className={`py-2 pr-4 ${textSecondary}`}>{p.nationality ?? '-'}</td>
                      <td className={`py-2 pr-4 ${textSecondary}`}>
                        {p.dominant_hand === 'R' ? '右' : p.dominant_hand === 'L' ? '左' : '-'}
                      </td>
                      <td className={`py-2 pr-4 ${textSecondary}`}>{p.world_ranking ? `#${p.world_ranking}` : '-'}</td>
                      <td className="py-2 pr-4">
                        {p.is_target && <CheckCircle size={14} className="text-green-400" />}
                      </td>
                      <td className="py-2">
                        {deleteConfirmId === p.id ? (
                          // インライン削除確認
                          <div className={`flex items-center gap-1 px-2 py-1 rounded border border-white text-xs ${isLight ? 'bg-red-50 text-red-700' : 'bg-red-900/30 text-red-400'}`}>
                            <button
                              onClick={() => { deletePlayer.mutate(p.id); setDeleteConfirmId(null) }}
                              className="font-medium hover:opacity-80"
                            >
                              削除
                            </button>
                            <span className="opacity-50">|</span>
                            <button
                              onClick={() => setDeleteConfirmId(null)}
                              className="hover:opacity-80"
                            >
                              取消
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => openEdit(p)}
                              className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
                            >
                              <Edit2 size={12} />
                            </button>
                            <button
                              onClick={() => setDeleteConfirmId(p.id)}
                              className="p-1.5 rounded bg-red-900/50 hover:bg-red-700 text-red-400"
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* 空状態メッセージ */}
            {players.length === 0 && (
              <div className="text-center text-gray-500 py-8">
                {t('settings.ui.no_players')}
              </div>
            )}
            {players.length > 0 && filteredPlayers.length === 0 && (
              <div className={`text-center ${textMuted} py-8 text-sm`}>
                {t('settings.ui.no_match_players')}
              </div>
            )}
          </div>
        )}

        {/* 要レビュータブ（V4-U-003） */}
        {activeTab === 'review' && (
          <div>
            <h2 className={`text-lg font-medium ${textHeading} mb-4`}>{t('review.title')}</h2>
            <div className="mb-6">
              <h3 className={`text-sm font-medium ${textSecondary} mb-2 flex items-center gap-2`}>
                <AlertCircle size={14} className="text-orange-400" />
                {t('review.provisional_players')}
              </h3>
              {!reviewPlayersData?.data?.length ? (
                <div className={`text-sm ${textMuted} py-4`}>{t('review.no_items')}</div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className={`${textSecondary} border-b ${borderLine}`}>
                      <th className="text-left py-2 pr-4">{t('settings.ui.name')}</th>
                      <th className="text-left py-2 pr-4">{t('review.profile_status')}</th>
                      <th className="text-left py-2 pr-4">{t('settings.ui.dominant_hand')}</th>
                      <th className="text-left py-2 pr-4">{t('settings.ui.match_count')}</th>
                      <th className="text-left py-2">{t('settings.ui.operation')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reviewPlayersData.data.map((p) => (
                      <tr key={p.id} className={`border-b ${isLight ? 'border-gray-100 hover:bg-gray-50' : 'border-gray-800 hover:bg-gray-800/50'}`}>
                        <td className="py-2 pr-4">
                          <div className="flex items-center gap-2">
                            {p.name}
                            {p.profile_status === 'provisional' && (
                              <span className="text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded">{t('settings.ui.tentative')}</span>
                            )}
                          </div>
                        </td>
                        <td className={`py-2 pr-4 ${textSecondary}`}>
                          {t(`player.profile_status_${p.profile_status ?? 'provisional'}`)}
                        </td>
                        <td className={`py-2 pr-4 ${textSecondary}`}>
                          {p.dominant_hand === 'R' ? '右' : p.dominant_hand === 'L' ? '左' : t('player.unknown_hand')}
                        </td>
                        <td className={`py-2 pr-4 ${textSecondary}`}>{p.match_count ?? 0}</td>
                        <td className="py-2">
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => openEdit(p)}
                              className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
                              title={t('auto.SettingsPage.k23')}
                            >
                              <Edit2 size={12} />
                            </button>
                            <button
                              onClick={() => markVerified.mutate(p.id)}
                              disabled={markVerified.isPending}
                              className="p-1.5 rounded bg-green-800 hover:bg-green-700 text-green-300"
                              title={t('review.mark_verified')}
                            >
                              <CheckCircle size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {/* TrackNet設定タブ */}
        {activeTab === 'tracknet' && (
          <div className="space-y-6">
            <h2 className={`text-lg font-medium ${textHeading}`}>{t('tracknet.tab_label')}</h2>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="space-y-6">
            {/* モデルステータス */}
            <div className={`${card} rounded-lg p-4 border ${borderLine}`}>
              <h3 className={`text-sm font-medium ${textSecondary} mb-3 flex items-center gap-2`}>
                <Zap size={14} className="text-yellow-400" />
                {t('tracknet.model_status')}
              </h3>
              {!tracknetStatus ? (
                <p className={`text-sm ${textMuted}`}>{t('tracknet.backend_offline')}</p>
              ) : tracknetStatus.data?.available ? (
                <div className="flex items-center gap-2">
                  <CheckCircle size={14} className="text-green-400" />
                  <span className="text-sm text-green-300">
                    {t('tracknet.model_ready')} — {tracknetStatus.data.backend}
                  </span>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <AlertCircle size={14} className="text-orange-400" />
                    <span className="text-sm text-orange-300">{t('tracknet.model_not_found')}</span>
                  </div>
                <div className={`${isLight ? 'bg-gray-100' : 'bg-gray-900'} rounded p-3 text-xs font-mono space-y-1 ${textMuted}`}>
                    <p className="text-gray-300 font-sans font-medium text-xs mb-1">{t('tracknet.setup_instructions')}</p>
                    <p>python -m backend.tracknet.setup download</p>
                    <p>python -m backend.tracknet.setup export</p>
                    <p>python -m backend.tracknet.setup convert</p>
                    <p className="text-gray-500 font-sans">{t('auto.SettingsPage.k1')}</p>
                  </div>
                </div>
              )}
            </div>

            {/* 有効/無効トグル */}
            <div className={`flex items-center justify-between ${card} rounded-lg p-4 border ${borderLine}`}>
              <div>
                <p className="text-sm font-medium">{t('tracknet.enable_toggle')}</p>
                <p className="text-xs text-gray-400 mt-0.5">{t('tracknet.enable_description')}</p>
              </div>
              <button
                onClick={() => updateSettings({ tracknet_enabled: !appSettings.tracknet_enabled })}
                disabled={settingsLoading}
                className="flex-shrink-0"
              >
                {appSettings.tracknet_enabled
                  ? <ToggleRight size={32} className="text-blue-400" />
                  : <ToggleLeft size={32} className="text-gray-500" />}
              </button>
            </div>

            {/* バックエンド選択 */}
            <div className={`${card} rounded-lg p-4 border ${borderLine}`}>
              <h3 className={`text-sm font-medium ${textSecondary} mb-3 flex items-center gap-2`}>
                <Cpu size={14} />
                {t('tracknet.backend_label')}
              </h3>
              <div className="flex gap-2">
                {([
                  { value: 'auto',           label: 'Auto (CUDA → DML → OpenVINO → ONNX → TF)' },
                  { value: 'cuda',           label: 'CUDA (NVIDIA)' },
                  { value: 'directml',       label: 'DirectML (AMD/NVIDIA)' },
                  { value: 'openvino',       label: 'OpenVINO (Intel)' },
                  { value: 'onnx_cuda',      label: 'ONNX CUDA' },
                  { value: 'onnx_cpu',       label: 'ONNX CPU' },
                  { value: 'tensorflow_cpu', label: 'TensorFlow CPU' },
                ] as const).map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => updateSettings({ tracknet_backend: opt.value })}
                    className={`py-1.5 px-3 rounded text-xs border transition-colors ${
                      appSettings.tracknet_backend === opt.value
                        ? 'border-blue-500 bg-blue-600 text-white'
                        : 'border-gray-600 bg-gray-700 text-gray-300 hover:border-gray-500'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 解析モード */}
            <div className={`${card} rounded-lg p-4 border ${borderLine}`}>
              <h3 className={`text-sm font-medium ${textSecondary} mb-1`}>{t('tracknet.mode_label')}</h3>
              <p className="text-xs text-gray-500 mb-3">{t('tracknet.mode_description')}</p>
              <div className="flex gap-2">
                {([
                  { value: 'batch', label: t('tracknet.mode_batch') },
                  { value: 'assist', label: t('tracknet.mode_assist') },
                ] as const).map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => updateSettings({ tracknet_mode: opt.value })}
                    className={`flex-1 py-2 px-3 rounded text-sm border transition-colors ${
                      appSettings.tracknet_mode === opt.value
                        ? 'border-blue-500 bg-blue-900/30 text-blue-300'
                        : 'border-gray-600 bg-gray-700 text-gray-300 hover:border-gray-500'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* CPU使用率上限 */}
            <div className={`${card} rounded-lg p-4 border ${borderLine}`}>
              <div className="flex items-center justify-between mb-2">
                <h3 className={`text-sm font-medium ${textSecondary}`}>{t('tracknet.cpu_limit_label')}</h3>
                <span className="text-sm font-mono text-blue-300">{appSettings.tracknet_max_cpu_pct}%</span>
              </div>
              <input
                type="range"
                min={10}
                max={90}
                step={5}
                value={appSettings.tracknet_max_cpu_pct}
                onChange={(e) => updateSettings({ tracknet_max_cpu_pct: Number(e.target.value) })}
                className="w-full accent-blue-500"
              />
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>10%</span>
                <span>90%</span>
              </div>
            </div>

            {/* YOLO プレイヤー検出 セクション */}
            <div className={`${card} rounded-lg p-4 border ${borderLine} space-y-3`}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">{t('yolo.enabled')}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{t('yolo.enable_description')}</p>
                </div>
                <button
                  onClick={() => updateSettings({ yolo_enabled: !appSettings.yolo_enabled })}
                  disabled={settingsLoading}
                  className="flex-shrink-0"
                >
                  {appSettings.yolo_enabled
                    ? <ToggleRight size={32} className="text-blue-400" />
                    : <ToggleLeft size={32} className="text-gray-500" />}
                </button>
              </div>

              {/* YOLO モデルステータス */}
              <div className={`rounded p-2.5 text-xs space-y-1.5 ${isLight ? 'bg-gray-100' : 'bg-gray-900'}`}>
                <p className={`font-medium ${isLight ? 'text-gray-600' : 'text-gray-400'}`}>{t('settings.ui.model_state')}</p>
                {!yoloStatus ? (
                  <p className={isLight ? 'text-gray-500' : 'text-gray-500'}>{t('settings.ui.backend_connecting')}</p>
                ) : (() => {
                  const sc = yoloStatus.data?.status_code
                  const msg = yoloStatus.data?.status_message
                  if (sc === 'ready') {
                    return (
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="text-emerald-400">●</span>
                          <span className={isLight ? 'text-emerald-700' : 'text-emerald-300'}>
                            推論可能 — {yoloStatus.data?.backend ?? 'ultralytics'}
                          </span>
                        </div>
                      </div>
                    )
                  }
                  if (sc === 'weights_missing') {
                    return (
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-blue-400">●</span>
                          <span className={isLight ? 'text-blue-700' : 'text-blue-300'}>
                            パッケージ導入済み（初回実行時に自動DL）
                          </span>
                        </div>
                        {msg && <p className={`text-[10px] ${isLight ? 'text-gray-500' : 'text-gray-500'}`}>{msg}</p>}
                      </div>
                    )
                  }
                  if (sc === 'load_failed') {
                    return (
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-red-400">●</span>
                          <span className={isLight ? 'text-red-700' : 'text-red-300'}>{t('settings.ui.load_failed')}</span>
                        </div>
                        {msg && <p className={`text-[10px] font-mono break-all ${isLight ? 'text-gray-600' : 'text-gray-400'}`}>{msg}</p>}
                      </div>
                    )
                  }
                  // package_missing
                  return (
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-orange-400">●</span>
                        <span className={isLight ? 'text-orange-700' : 'text-orange-300'}>{t('settings.ui.package_missing')}</span>
                      </div>
                      <code className={`block text-[10px] px-2 py-1 rounded ${isLight ? 'bg-gray-200 text-gray-700' : 'bg-gray-800 text-gray-300'}`}>
                        pip install ultralytics
                      </code>
                    </div>
                  )
                })()}
              </div>
            </div>

            </div>{/* end left col */}
            <div className="space-y-6">{/* right col */}

            {/* ─── GPU / デバイス設定 ─── */}
            <div className={`${card} rounded-lg p-4 border ${borderLine} space-y-4`}>
              <div className="flex items-center justify-between">
                <h3 className={`text-sm font-medium ${textSecondary} flex items-center gap-2`}>
                  <Cpu size={14} className="text-purple-400" />
                  GPU / コンピュートデバイス設定
                </h3>
                <button
                  onClick={() => refetchDevices()}
                  disabled={devicesFetching}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-white rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-50 transition-colors"
                >
                  {devicesFetching ? <RotateCcw size={11} className="animate-spin" /> : <RotateCcw size={11} />}
                  {t('settings.ui.redetect')}
                </button>
              </div>

              {/* CUDA デバイス選択 */}
              {computeDevices && (computeDevices.cuda_devices?.length ?? 0) > 0 && (
                <div>
                  <p className={`text-xs font-medium mb-2 ${isLight ? 'text-gray-600' : 'text-gray-400'}`}>{t('auto.SettingsPage.k2')}</p>
                  <div className="space-y-1.5">
                    {computeDevices.cuda_devices.map((dev) => (
                      <button
                        key={dev.index}
                        onClick={() => updateSettings({ cuda_device_index: dev.index })}
                        className={`w-full text-left px-3 py-2 rounded text-xs border transition-colors ${
                          appSettings.cuda_device_index === dev.index
                            ? 'border-blue-500 bg-blue-600/20 text-blue-300'
                            : `border-gray-600 ${isLight ? 'bg-white text-gray-700' : 'bg-gray-700 text-gray-300'} hover:border-gray-500`
                        }`}
                      >
                        <span className="font-medium">GPU {dev.index}</span>
                        <span className="ml-2">{dev.name}</span>
                        <span className={`ml-auto float-right ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>{dev.vram_mb >= 1024 ? `${(dev.vram_mb / 1024).toFixed(1)} GB` : `${dev.vram_mb} MB`}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* OpenVINO デバイス選択 */}
              {computeDevices && (computeDevices.openvino_devices?.length ?? 0) > 0 && (
                <div>
                  <p className={`text-xs font-medium mb-2 ${isLight ? 'text-gray-600' : 'text-gray-400'}`}>{t('auto.SettingsPage.k3')}</p>
                  <div className="flex flex-wrap gap-2">
                    {computeDevices.openvino_devices.map((dev) => (
                      <button
                        key={dev}
                        onClick={() => updateSettings({ openvino_device: dev })}
                        className={`py-1.5 px-3 rounded text-xs border transition-colors ${
                          appSettings.openvino_device === dev
                            ? 'border-blue-500 bg-blue-600 text-white'
                            : `border-gray-600 ${isLight ? 'bg-white text-gray-700' : 'bg-gray-700 text-gray-300'} hover:border-gray-500`
                        }`}
                      >
                        {dev}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* ONNX プロバイダー状態表示 */}
              {computeDevices && (
                <div>
                  <p className={`text-xs font-medium mb-1.5 ${isLight ? 'text-gray-600' : 'text-gray-400'}`}>{t('auto.SettingsPage.k4')}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {(computeDevices.onnx_providers ?? []).map((p) => (
                      <span
                        key={p}
                        className={`text-[10px] px-2 py-0.5 rounded ${
                          p === 'CUDAExecutionProvider'
                            ? 'bg-green-900/40 text-green-300 border border-green-700'
                            : p === 'DmlExecutionProvider'
                            ? 'bg-blue-900/40 text-blue-300 border border-blue-700'
                            : `${isLight ? 'bg-gray-100 text-gray-600' : 'bg-gray-800 text-gray-400'} border border-gray-600`
                        }`}
                      >
                        {p.replace('ExecutionProvider', '')}
                      </span>
                    ))}
                    {(computeDevices.onnx_providers ?? []).length === 0 && (
                      <span className="text-xs text-gray-500">{t('auto.SettingsPage.k5')}</span>
                    )}
                  </div>
                  {(() => {
                    const providers = computeDevices.onnx_providers ?? []
                    const hasCuda = providers.includes('CUDAExecutionProvider')
                    const hasDml = providers.includes('DmlExecutionProvider')
                    if (hasCuda || hasDml) return null
                    return (
                      <p className="text-[10px] text-amber-400 mt-1.5">
                        GPU推論を有効にするには{' '}
                        <code className="bg-gray-800 px-1 rounded">onnxruntime-gpu</code>（CUDA）または{' '}
                        <code className="bg-gray-800 px-1 rounded">onnxruntime-directml</code>（DirectML）をインストールしてください
                      </p>
                    )
                  })()}
                </div>
              )}

              {!computeDevices && !devicesFetching && (
                <p className="text-xs text-gray-500">{t('auto.SettingsPage.k6')}</p>
              )}
            </div>

            {/* ─── ベンチマーク（新 UI） ─── */}
            <div className={`${card} rounded-lg p-4 border ${borderLine} space-y-4`}>
              <div className="flex items-center justify-between">
                <h3 className={`text-sm font-medium ${textSecondary} flex items-center gap-2`}>
                  <Zap size={14} className="text-yellow-400" />
                  {t('benchmark.title')}
                </h3>
                {/* デバイス検出ボタン */}
                <button
                  onClick={fetchBmDevices}
                  disabled={bmRunning || bmDetecting}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-white rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-50 transition-colors"
                >
                  {bmDetecting
                    ? <><Loader2 size={12} className="animate-spin" />{t('benchmark.detecting')}</>
                    : t('benchmark.detect_devices')
                  }
                </button>
              </div>

              {/* エラー表示 */}
              {bmError && (
                <p className="text-xs text-red-400">{bmError}</p>
              )}

              {/* デバイス選択 */}
              {bmDevices.length > 0 && (
                <DeviceSelector
                  devices={bmDevices}
                  selected={bmSelectedDevices}
                  onChange={setBmSelectedDevices}
                />
              )}

              {/* ターゲット選択 */}
              <TargetSelector
                selected={bmTargets}
                onTargetsChange={setBmTargets}
                nFrames={bmNFrames}
                onNFramesChange={setBmNFrames}
              />

              {/* 実行ボタン */}
              <button
                onClick={startBenchmark}
                disabled={bmRunning || bmSelectedDevices.length === 0 || bmTargets.length === 0}
                className="flex items-center gap-1.5 px-4 py-2 text-xs text-white rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-wait transition-colors"
              >
                {bmRunning ? (
                  <><RotateCcw size={11} className="animate-spin" /> {t('benchmark.running')}</>
                ) : (
                  <><Play size={11} /> {t('benchmark.run')}</>
                )}
              </button>

              {/* 停止ボタン（実行中のみ表示） */}
              {bmRunning && (
                <button
                  onClick={stopBenchmark}
                  className="flex items-center gap-1.5 px-4 py-2 text-xs text-white rounded bg-red-700 hover:bg-red-600 transition-colors"
                >
                  <Square size={11} /> {t('benchmark.stop')}
                </button>
              )}

              {/* プログレスバー（実行中のみ表示） */}
              <BenchmarkProgress
                running={bmRunning}
                job={bmJob}
                onPoll={pollBmJob}
              />

              {/* 結果マトリクス */}
              {bmJob && (bmJob.status === 'done' || bmJob.status === 'failed') && (
                <ResultMatrix
                  job={bmJob}
                  devices={bmDevices.filter((d) => bmSelectedDevices.includes(d.device_id))}
                  targets={bmTargets}
                />
              )}
            </div>

            </div>{/* end right col */}
            </div>{/* end grid */}
          </div>
        )}

        {/* 共有設定タブ (R-001/R-002/Q-002/Q-008) */}
        {activeTab === 'sharing' && (
          <div className="space-y-6">
            <h2 className={`text-lg font-medium ${textHeading}`}>{t('sharing.tab_label')}</h2>

            {/* トンネル起動中バナー: URLをここで優先表示 */}
            {tunnelStatus?.data?.running && tunnelStatus.data.url && (
              <div className="bg-blue-900/30 border border-blue-500/40 rounded-lg p-4 space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium text-blue-300">
                  <Globe size={14} />
                  トンネル接続中 — このURLを使用してください
                </div>
                <LanUrlCard url={tunnelStatus.data.url} hint="iOSを含む全デバイスからHTTPSでアクセス可能" />
              </div>
            )}

            {/* LAN モード設定 */}
            <div className={`${card} rounded-lg p-4 border ${borderLine}`}>
              <div className="flex items-center justify-between mb-3">
                <div>
                  <p className="text-sm font-medium">{t('sharing.lan_mode_label')}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{t('sharing.lan_mode_description')}</p>
                </div>
                <button
                  onClick={() => toggleLanMode.mutate(!serverInfo?.data?.lan_mode)}
                  className="flex-shrink-0"
                >
                  {serverInfo?.data?.lan_mode
                    ? <ToggleRight size={32} className="text-blue-400" />
                    : <ToggleLeft size={32} className="text-gray-500" />}
                </button>
              </div>
              {serverInfo?.data?.lan_mode && serverInfo.data.lan_ips.length > 0 ? (
                <div className={`${isLight ? 'bg-gray-100' : 'bg-gray-900'} rounded p-3 space-y-3`}>
                  {serverInfo.data.lan_ips.map((ip) => {
                    const appUrl = `http://${ip}:${serverInfo.data.port}/`
                    return (
                      <LanUrlCard key={ip} url={appUrl} hint={t('sharing.lan_app_url_hint')} />
                    )
                  })}
                </div>
              ) : serverInfo?.data?.lan_mode ? (
                <div className="flex items-center gap-2 text-xs text-orange-400">
                  <WifiOff size={12} />
                  {t('sharing.lan_no_ip')}
                </div>
              ) : (
                <p className="text-xs text-gray-500">{t('sharing.lan_disabled_hint')}</p>
              )}
            </div>

            {/* リモート公開 */}
            <div className={`${card} rounded-lg p-4 border ${borderLine}`}>
              <h3 className={`text-sm font-medium ${textSecondary} mb-1 flex items-center gap-2`}>
                <Globe size={14} className="text-blue-400" />
                {t('sharing.remote_exposure_title')}
              </h3>
              <p className={`text-xs mb-3 ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>{t('sharing.remote_exposure_description')}</p>

              {/* プロバイダー選択（停止中のみ変更可） */}
              {!tunnelStatus?.data?.running && (
                <div className="mb-3">
                  <p className={`text-xs font-medium mb-1.5 ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>{t('sharing.remote_provider_label')}</p>
                  <div className="flex gap-2 flex-wrap">
                    {(['auto', 'ngrok', 'cloudflare'] as const).map(p => {
                      const unavailable =
                        (p === 'ngrok' && tunnelStatus?.data?.providers?.ngrok?.available === false) ||
                        (p === 'cloudflare' && tunnelStatus?.data?.providers?.cloudflare?.available === false)
                      return (
                        <button
                          key={p}
                          onClick={() => updateSettings({ tunnel_provider: p })}
                          className={`flex items-center gap-1 px-3 py-1 rounded text-xs transition-colors ${
                            appSettings.tunnel_provider === p
                              ? 'bg-blue-600 text-white'
                              : isLight ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                          }`}
                        >
                          {p === 'auto' ? '自動' : p}
                          {unavailable && <span className="text-orange-400 ml-0.5">✕</span>}
                        </button>
                      )
                    })}
                  </div>
                  {appSettings.tunnel_provider === 'auto' && (
                    <p className={`text-xs mt-1.5 ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>{t('sharing.auto_order_hint')}</p>
                  )}
                </div>
              )}

              {/* ngrok 認証トークン */}
              {(appSettings.tunnel_provider === 'ngrok' || appSettings.tunnel_provider === 'auto') && (
                <div className="space-y-1.5">
                  <label className={`text-xs font-medium ${isLight ? 'text-gray-600' : 'text-gray-400'}`}>
                    {t('sharing.ngrok_authtoken_label')}
                  </label>
                  {tunnelStatus?.data?.ngrok_authtoken_from_env ? (
                    /* env から自動適用済み */
                    <div className={`flex items-center gap-2 px-2 py-1.5 rounded text-xs ${
                      isLight ? 'bg-green-50 border border-green-200 text-green-700' : 'bg-green-900/20 border border-green-700/40 text-green-400'
                    }`}>
                      <CheckCircle2 size={12} />
                      {t('sharing.ngrok_authtoken_from_env')}
                    </div>
                  ) : (
                    /* 未設定 → 入力を求める */
                    <>
                      <div className="flex items-center gap-2">
                        <input
                          type="password"
                          value={appSettings.ngrok_authtoken ?? ''}
                          onChange={(e) => updateSettings({ ngrok_authtoken: e.target.value })}
                          placeholder={t('sharing.ngrok_authtoken_placeholder')}
                          className={`flex-1 rounded px-2 py-1 text-xs font-mono ${
                            isLight
                              ? 'bg-gray-100 text-gray-700 placeholder-gray-400 border border-gray-200'
                              : 'bg-gray-900/60 text-gray-300 placeholder-gray-600 border border-gray-700'
                          } focus:outline-none focus:ring-1 focus:ring-blue-500`}
                        />
                      </div>
                      <p className={`text-[10px] ${isLight ? 'text-gray-400' : 'text-gray-600'}`}>
                        {t('sharing.ngrok_authtoken_hint')}
                      </p>
                    </>
                  )}
                </div>
              )}

              {/* 利用可否なし */}
              {tunnelStatus?.data?.available === false ? (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2 text-xs text-orange-400">
                    <AlertCircle size={13} />
                    {t('sharing.tunnel_not_available')}
                  </div>
                  <p className={`text-xs ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>{t('sharing.tunnel_install_hint')}</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {tunnelStatus?.data?.providers?.cloudflare?.available && (
                    <div className={`rounded border px-3 py-2 text-xs ${
                      isLight ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-blue-800 bg-blue-950/30 text-blue-300'
                    }`}>
                      <div className="font-medium">Cloudflare named tunnel</div>
                      <div className="mt-1 font-mono break-all">
                        {tunnelStatus.data.providers.cloudflare.hostname
                          ? `https://${tunnelStatus.data.providers.cloudflare.hostname}`
                          : 'https://app.shuttle-scope.com'}
                      </div>
                      <div className={`mt-1 ${isLight ? 'text-blue-600' : 'text-blue-400'}`}>
                        {tunnelStatus.data.providers.cloudflare.named_ready
                          ? 'named tunnel 設定を検出しました。Cloudflare 選択時は固定ドメインを優先します。'
                          : 'named tunnel 設定は未完了です。repo外の Desktop\\cloudflare-shuttle-scope または ~/.cloudflared を使う想定です。'}
                      </div>
                      {tunnelStatus.data.providers.cloudflare.config_path && (
                        <div className={`mt-1 break-all ${isLight ? 'text-blue-500' : 'text-blue-500'}`}>
                          {tunnelStatus.data.providers.cloudflare.config_path}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2">
                      {tunnelStatus?.data?.running
                        ? <span className="inline-block w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                        : <span className="inline-block w-2 h-2 rounded-full bg-gray-500" />}
                      <span className="text-sm">
                        {tunnelStatus?.data?.running ? t('sharing.tunnel_running') : t('sharing.tunnel_not_running')}
                      </span>
                      {tunnelStatus?.data?.active_provider && (
                        <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${isLight ? 'bg-gray-100 text-gray-500' : 'bg-gray-700 text-gray-400'}`}>
                          {tunnelStatus.data.active_provider}
                        </span>
                      )}
                    </div>
                    <div className="ml-auto flex gap-2">
                      {!tunnelStatus?.data?.running ? (
                        <button
                          onClick={() => tunnelStart.mutate()}
                          disabled={tunnelStart.isPending}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded text-xs text-white"
                        >
                          <Power size={12} />
                          {tunnelStart.isPending ? t('sharing.tunnel_starting') : t('sharing.tunnel_start')}
                        </button>
                      ) : (
                        <button
                          onClick={() => tunnelStop.mutate()}
                          disabled={tunnelStop.isPending}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-red-800 hover:bg-red-700 disabled:opacity-50 rounded text-xs text-white"
                        >
                          <PowerOff size={12} />
                          {t('sharing.tunnel_stop')}
                        </button>
                      )}
                    </div>
                  </div>

                  {tunnelStatus?.data?.running && tunnelStatus.data.url && (
                    <div className={`${isLight ? 'bg-gray-100' : 'bg-gray-900'} rounded p-3`}>
                      <LanUrlCard url={tunnelStatus.data.url} hint={t('sharing.tunnel_url_hint')} />
                    </div>
                  )}

                  {tunnelStatus?.data?.running && !tunnelStatus.data.url && (
                    <p className={`text-xs animate-pulse ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>{t('auto.SettingsPage.k7')}</p>
                  )}
                </div>
              )}
            </div>

            {/* リモート映像（WebRTC） */}
            <div className={`${card} rounded-lg p-4 border ${borderLine}`}>
              <h3 className={`text-sm font-medium ${textSecondary} mb-1 flex items-center gap-2`}>
                <Wifi size={14} className="text-purple-400" />
                {t('sharing.remote_video_title')}
              </h3>
              <p className={`text-xs mb-3 ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>{t('sharing.remote_video_description')}</p>

              {/* Off / WebRTC 選択 */}
              <div className="flex gap-2 mb-3">
                {(['off', 'webrtc'] as const).map(v => (
                  <button
                    key={v}
                    onClick={() => updateSettings({ video_transport: v })}
                    className={`px-3 py-1 rounded text-xs transition-colors ${
                      appSettings.video_transport === v
                        ? 'bg-blue-600 text-white'
                        : isLight ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                    }`}
                  >
                    {v === 'off' ? t('sharing.video_transport_off') : t('sharing.video_transport_webrtc')}
                  </button>
                ))}
              </div>

              {appSettings.video_transport === 'webrtc' && (
                <div className="space-y-3">
                  {/* TURN トグル */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className={`text-xs font-medium ${textSecondary}`}>{t('sharing.turn_enable_label')}</p>
                      <p className={`text-xs mt-0.5 ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>{t('sharing.turn_description')}</p>
                    </div>
                    <button onClick={() => updateSettings({ turn_enabled: !appSettings.turn_enabled })}>
                      {appSettings.turn_enabled
                        ? <ToggleRight size={28} className="text-blue-400" />
                        : <ToggleLeft size={28} className="text-gray-500" />}
                    </button>
                  </div>

                  {/* TURN なし警告 */}
                  {!appSettings.turn_enabled && (
                    <div className={`flex items-start gap-2 text-xs rounded p-2 ${isLight ? 'bg-amber-50 text-amber-700' : 'bg-amber-900/20 text-amber-400'}`}>
                      <AlertCircle size={12} className="flex-shrink-0 mt-0.5" />
                      {t('sharing.webrtc_best_effort_warning')}
                    </div>
                  )}

                  {/* TURN 必要場面説明 */}
                  {appSettings.turn_enabled && (
                    <p className={`text-xs ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>
                      {t('sharing.turn_when_required')}
                    </p>
                  )}

                  {/* TURN 設定フィールド */}
                  {appSettings.turn_enabled && (
                    <div className="space-y-2">
                      <input
                        type="text"
                        placeholder={t('sharing.turn_url_placeholder')}
                        value={appSettings.turn_url}
                        onChange={e => updateSettings({ turn_url: e.target.value })}
                        className={`w-full px-2 py-1.5 rounded text-xs border font-mono ${
                          isLight ? 'bg-white border-gray-300 text-gray-800' : 'bg-gray-800 border-gray-600 text-gray-200'
                        } ${appSettings.turn_url && !/^turns?:/i.test(appSettings.turn_url) ? 'border-red-500' : ''}`}
                      />
                      {appSettings.turn_url && !/^turns?:/i.test(appSettings.turn_url) && (
                        <p className="text-[10px] text-red-400 flex items-center gap-1">
                          <AlertCircle size={10} />
                          {t('sharing.turn_url_invalid')}
                        </p>
                      )}
                      <div className="flex gap-2">
                        <input
                          type="text"
                          placeholder={t('sharing.turn_username_placeholder')}
                          value={appSettings.turn_username}
                          onChange={e => updateSettings({ turn_username: e.target.value })}
                          className={`flex-1 px-2 py-1.5 rounded text-xs border ${
                            isLight ? 'bg-white border-gray-300 text-gray-800' : 'bg-gray-800 border-gray-600 text-gray-200'
                          }`}
                        />
                        <input
                          type="password"
                          placeholder={t('sharing.turn_credential_placeholder')}
                          value={appSettings.turn_credential}
                          onChange={e => updateSettings({ turn_credential: e.target.value })}
                          className={`flex-1 px-2 py-1.5 rounded text-xs border ${
                            isLight ? 'bg-white border-gray-300 text-gray-800' : 'bg-gray-800 border-gray-600 text-gray-200'
                          }`}
                        />
                      </div>

                      {/* 疎通テストボタン + 結果 */}
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => turnTest.mutate()}
                          disabled={turnTest.isPending || !appSettings.turn_url}
                          className={`px-3 py-1.5 text-xs rounded disabled:opacity-40 ${isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-700' : 'bg-gray-700 hover:bg-gray-600 text-gray-200'}`}
                        >
                          {turnTest.isPending ? t('sharing.turn_test_running') : t('sharing.turn_test_button')}
                        </button>
                        {turnTest.data && (
                          <span className={`text-xs flex items-center gap-1 ${turnTest.data.success ? 'text-green-400' : 'text-red-400'}`}>
                            {turnTest.data.success
                              ? <><CheckCircle size={11} />{t('sharing.turn_test_ok')} ({turnTest.data.data?.host}:{turnTest.data.data?.port})</>
                              : <><AlertCircle size={11} />{t('sharing.turn_test_fail')}: {turnTest.data.error}</>
                            }
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* セッション作成ヘルプ */}
            <div className={`${card} rounded-lg p-4 border ${borderLine}`}>
              <h3 className={`text-sm font-medium ${textSecondary} mb-2 flex items-center gap-2`}>
                <Share2 size={14} />
                {t('sharing.session_guide_title')}
              </h3>
              <ol className="space-y-2 text-xs text-gray-400">
                <li>1. {t('sharing.guide_step1')}</li>
                <li>2. {t('sharing.guide_step2')}</li>
                <li>3. {t('sharing.guide_step3')}</li>
                <li>4. {t('sharing.guide_step4')}</li>
              </ol>
            </div>

            {/* Q-002/Q-008: ネットワーク診断 */}
            <div className={`${card} rounded-lg p-4 border ${borderLine}`}>
              <div className="flex items-center justify-between mb-3">
                <h3 className={`text-sm font-medium ${textSecondary} flex items-center gap-2`}>
                  <Wifi size={14} />
                  {t('sharing.network_diag_title')}
                </h3>
                <button
                  onClick={() => runDiagnostics()}
                  disabled={netDiagFetching}
                  className={`px-3 py-1 text-xs rounded disabled:opacity-50 ${isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-700' : 'bg-gray-700 hover:bg-gray-600 text-gray-200'}`}
                >
                  {netDiagFetching ? '診断中...' : t('sharing.run_diagnostics')}
                </button>
              </div>

              {netDiag?.data && (
                <div className="space-y-3">
                  {/* 環境分類 */}
                  <div className="flex items-center gap-2">
                    {netDiag.data.environment === 'open'
                      ? <CheckCircle size={14} className="text-green-400" />
                      : <AlertCircle size={14} className="text-orange-400" />}
                    <span className="text-sm font-medium">
                      {{
                        open: 'オープン環境',
                        corporate_proxy: '企業プロキシ検出',
                        vpn: 'VPN 環境',
                        filtered: '制限環境',
                        captive_portal: 'キャプティブポータル',
                        unknown: '不明',
                      }[netDiag.data.environment] ?? netDiag.data.environment}
                    </span>
                    <span className="text-xs text-gray-500 ml-auto">{netDiag.data.probe_duration_ms}ms</span>
                  </div>

                  {/* capabilities */}
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    {([
                      ['TCP 443', netDiag.data.capabilities.tcp_443.ok],
                      ['TCP 80', netDiag.data.capabilities.tcp_80.ok],
                      ['Localhost', netDiag.data.capabilities.localhost_bridge.ok],
                    ] as [string, boolean][]).map(([label, ok]) => (
                      <div key={label} className={`rounded px-2 py-1 text-center ${ok ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'}`}>
                        {ok ? '✓' : '✗'} {label}
                      </div>
                    ))}
                  </div>

                  {/* LAN 情報 */}
                  {netDiag.data.lan.lan_ips.length > 0 && (
                    <div className="text-xs text-gray-400">
                      LAN IP: {netDiag.data.lan.lan_ips.join(', ')}
                    </div>
                  )}

                  {/* transport ladder 推奨 */}
                  <div className={`${isLight ? 'bg-gray-100' : 'bg-gray-900'} rounded p-3 space-y-1`}>
                    <p className={`text-xs font-medium ${textSecondary} mb-1`}>{t('sharing.transport_ladder')}</p>
                    {netDiag.data.transport_ladder.map((rec, i) => (
                      <p key={i} className="text-xs text-gray-400">{rec}</p>
                    ))}
                  </div>
                </div>
              )}

              {!netDiag && !netDiagFetching && (
                <p className="text-xs text-gray-500">{t('sharing.diag_not_run')}</p>
              )}
            </div>
          </div>
        )}

        {/* データ管理タブ */}
        {activeTab === 'data' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">

            {/* ── デバイス・同期設定 (admin only) ────────────────────────── */}
            {role === 'admin' && <section className={`${card} rounded-lg p-5 space-y-4`}>
              <div className="flex items-center gap-2">
                <HardDrive size={16} className="text-gray-400" />
                <h2 className="text-base font-semibold">{t('settings.ui.sync_settings')}</h2>
              </div>
              <div className="space-y-3">
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('auto.SettingsPage.k8')}</label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={appSettings.sync_device_id}
                      onChange={(e) => updateSettings({ sync_device_id: e.target.value })}
                      placeholder={t('auto.SettingsPage.k26')}
                      className="flex-1 bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white font-mono"
                    />
                  </div>
                  <p className="text-[11px] text-gray-500 mt-0.5">{t('auto.SettingsPage.k9')}</p>
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('auto.SettingsPage.k10')}</label>
                  <input
                    type="text"
                    value={appSettings.sync_folder_path}
                    onChange={(e) => updateSettings({ sync_folder_path: e.target.value })}
                    placeholder={t('auto.SettingsPage.k27')}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white font-mono"
                  />
                  <p className="text-[11px] text-gray-500 mt-0.5">{t('auto.SettingsPage.k11')}</p>
                </div>
              </div>
            </section>}

            {/* ── 監査ログ (admin only) ────────────────────────── */}
            {role === 'admin' && (
              <section className={`${card} rounded-lg p-5 space-y-3`}>
                <div className="flex items-center gap-2">
                  <ScrollText size={16} className="text-amber-400" />
                  <h2 className="text-base font-semibold">{t('settings.ui.audit_logs_title')}</h2>
                </div>
                <p className="text-xs text-gray-400">{t('settings.ui.audit_logs_desc')}</p>
                <button
                  onClick={() => navigate('/audit-logs')}
                  className="inline-flex items-center gap-2 bg-amber-600 hover:bg-amber-700 text-white text-sm font-medium px-3 py-2 rounded-lg"
                >
                  <ScrollText size={14} />
                  {t('settings.ui.audit_logs_open')}
                </button>
              </section>
            )}

            {/* ── エクスポート ──────────────────────────────── */}
            <section className={`${card} rounded-lg p-5 space-y-4`}>
              <div className="flex items-center gap-2">
                <Download size={16} className="text-blue-400" />
                <h2 className="text-base font-semibold">{t('settings.ui.export')}</h2>
              </div>
              <p className="text-xs text-gray-400">
                試合データを <code className="bg-gray-700 px-1 rounded">.sspkg</code> 形式でダウンロード。別 PC へのデータ持ち運びや引き継ぎに使用します。
              </p>

              {/* エクスポートモード切替 */}
              <div className="flex gap-1.5">
                {([{ key: 'match', label: t('auto.SettingsPage.k37') }, { key: 'change_set', label: t('auto.SettingsPage.k38') }] as const).map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => setExportMode(key)}
                    className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                      exportMode === key ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {exportMode === 'match' ? (
                /* 試合選択 */
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-sm text-gray-400">{t('auto.SettingsPage.k12')}</label>
                    {exportMatchList.length > 0 && (
                      <button
                        type="button"
                        onClick={() => {
                          const allIds = exportMatchList.map((m: any) => String(m.id))
                          const currentIds = exportMatchIds ? exportMatchIds.split(',').map((s: string) => s.trim()).filter(Boolean) : []
                          const allSelected = allIds.every((id: string) => currentIds.includes(id))
                          setExportMatchIds(allSelected ? '' : allIds.join(', '))
                        }}
                        className="text-xs text-blue-400 hover:text-blue-300"
                      >
                        {exportMatchList.every((m: any) => exportMatchIds.split(',').map((s: string) => s.trim()).includes(String(m.id)))
                          ? '選択解除' : 'すべて選択'}
                      </button>
                    )}
                  </div>
                  <div className="flex gap-2 items-start">
                    <div className="flex-1">
                      <input
                        type="text"
                        value={exportMatchIds}
                        onChange={(e) => setExportMatchIds(e.target.value)}
                        placeholder={t('auto.SettingsPage.k28')}
                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white mb-1"
                      />
                      {exportMatchList.length > 0 && (
                        <div className="max-h-40 overflow-y-auto rounded border border-gray-700 divide-y divide-gray-700">
                          {exportMatchList.map((m: any) => (
                            <button
                              key={m.id}
                              type="button"
                              onClick={() => {
                                const ids = exportMatchIds ? exportMatchIds.split(',').map((s: string) => s.trim()).filter(Boolean) : []
                                const sid = String(m.id)
                                setExportMatchIds(ids.includes(sid) ? ids.filter((x: string) => x !== sid).join(', ') : [...ids, sid].join(', '))
                              }}
                              className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between transition-colors ${
                                exportMatchIds.split(',').map((s: string) => s.trim()).includes(String(m.id))
                                  ? 'bg-blue-900/40 text-blue-300' : 'text-gray-300 hover:bg-gray-700'
                              }`}
                            >
                              <span>[{m.id}] {m.date} {m.tournament}</span>
                              <span className={`text-[10px] ${m.result === 'win' ? 'text-green-400' : 'text-red-400'}`}>
                                {m.result === 'win' ? '勝' : m.result === 'loss' ? '敗' : m.result}
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={handleExportMatch}
                      disabled={!exportMatchIds.trim()}
                      className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-sm font-medium transition-colors whitespace-nowrap"
                    >
                      <Download size={14} />
                      ダウンロード
                    </button>
                  </div>
                </div>
              ) : (
                /* Change Set */
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('auto.SettingsPage.k13')}</label>
                  <div className="flex gap-2">
                    <input
                      type="datetime-local"
                      value={exportSince}
                      onChange={(e) => setExportSince(e.target.value)}
                      className="flex-1 bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white"
                    />
                    <button
                      onClick={handleExportMatch}
                      disabled={!exportSince.trim()}
                      className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-sm font-medium transition-colors whitespace-nowrap"
                    >
                      <Download size={14} />
                      差分DL
                    </button>
                  </div>
                </div>
              )}
            </section>

            {/* ── インポート ────────────────────────────────── */}
            <section className={`${card} rounded-lg p-5 space-y-4`}>
              <div className="flex items-center gap-2">
                <Upload size={16} className="text-emerald-400" />
                <h2 className="text-base font-semibold">{t('settings.ui.import')}</h2>
              </div>
              <p className="text-xs text-gray-400">
                別 PC からエクスポートされた <code className="bg-gray-700 px-1 rounded">.sspkg</code> ファイルを取り込みます。既存データはレコード単位でマージされます。
              </p>

              <div>
                <label className={`block text-sm ${textSecondary} mb-1`}>{t('auto.SettingsPage.k14')}</label>
                <input
                  type="file"
                  accept=".sspkg,.zip"
                  onChange={(e) => {
                    setImportFile(e.target.files?.[0] ?? null)
                    setImportPreview(null)
                    setImportResult(null)
                  }}
                  className={`w-full text-sm file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-xs ${isLight ? 'text-gray-700 file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200' : 'text-gray-300 file:bg-gray-700 file:text-gray-300 hover:file:bg-gray-600'}`}
                />
              </div>

              {importFile && !importPreview && (
                <button
                  onClick={handlePreviewImport}
                  disabled={importPreviewLoading}
                  className={`flex items-center gap-1.5 px-4 py-2 disabled:opacity-40 rounded text-sm transition-colors ${isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-700' : 'bg-gray-700 hover:bg-gray-600 text-gray-200'}`}
                >
                  <Eye size={14} />
                  {importPreviewLoading ? '確認中...' : '内容を確認'}
                </button>
              )}

              {/* プレビュー結果 */}
              {importPreview && (
                <div className="rounded-lg border border-gray-700 p-4 space-y-3">
                  {!importPreview.success ? (
                    <p className="text-sm text-red-400">{importPreview.data?.error ?? 'エラー'}</p>
                  ) : (
                    <>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        {[
                          { label: t('auto.SettingsPage.k39'), value: importPreview.data?.merge_preview?.added ?? 0, color: 'text-blue-400' },
                          { label: t('auto.SettingsPage.k16'), value: importPreview.data?.merge_preview?.updated ?? 0, color: 'text-yellow-400' },
                          { label: t('auto.SettingsPage.k40'), value: importPreview.data?.merge_preview?.kept ?? 0, color: 'text-gray-400' },
                          { label: t('auto.SettingsPage.k41'), value: importPreview.data?.merge_preview?.conflicts ?? 0, color: 'text-orange-400' },
                        ].map(({ label, value, color }) => (
                          <div key={label} className="bg-gray-700/50 rounded p-2 text-center">
                            <p className={`text-xl font-bold ${color}`}>{value}</p>
                            <p className="text-gray-500">{label}</p>
                          </div>
                        ))}
                      </div>
                      {(importPreview.data?.merge_preview?.conflicts ?? 0) > 0 && (
                        <p className="text-xs text-orange-400">
                          ⚠ 競合 {importPreview.data.merge_preview.conflicts} 件はローカルを優先して保持します（Phase 2 で個別解決予定）
                        </p>
                      )}
                      {!importResult && (
                        <button
                          onClick={handleImport}
                          disabled={importRunning}
                          className="w-full flex items-center justify-center gap-2 py-2.5 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded text-sm font-medium transition-colors"
                        >
                          <Upload size={14} />
                          {importRunning ? 'インポート中...' : 'インポート実行'}
                        </button>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* インポート結果 */}
              {importResult && (
                <div className={`rounded-lg p-3 text-sm ${importResult.success ? 'bg-emerald-900/30 border border-emerald-700' : 'bg-red-900/30 border border-red-700'}`}>
                  {importResult.success ? (
                    <>
                      <p className="font-medium text-emerald-300 mb-1">{t('auto.SettingsPage.k15')}</p>
                      <p className="text-xs text-gray-300">
                        追加 {importResult.data?.added} / 更新 {importResult.data?.updated} / 保持 {importResult.data?.kept} / 競合 {importResult.data?.conflicts}
                      </p>
                    </>
                  ) : (
                    <p className="text-red-400">{importResult.error ?? 'インポートエラー'}</p>
                  )}
                </div>
              )}
            </section>

            {/* ── バックアップ (admin only) ──────────────────────────────── */}
            {role === 'admin' && <section className={`${card} rounded-lg p-5 space-y-4`}>
              <div className="flex items-center gap-2">
                <HardDrive size={16} className="text-purple-400" />
                <h2 className="text-base font-semibold">{t('settings.ui.backup')}</h2>
              </div>
              <p className="text-xs text-gray-400">
                現行データベースをローカルにバックアップします。最大 10 世代を自動ローテーション保持します。
              </p>

              <div className="flex items-center gap-3">
                <button
                  onClick={handleBackup}
                  disabled={backupRunning}
                  className="flex items-center gap-1.5 px-4 py-2 bg-purple-700 hover:bg-purple-600 disabled:opacity-40 rounded text-sm font-medium transition-colors text-white"
                >
                  <FileArchive size={14} />
                  {backupRunning ? t('settings.ui.backup_running') : t('settings.ui.backup_now')}
                </button>
                {backupResult && (
                  <p className="text-xs text-gray-300 truncate max-w-xs">{backupResult}</p>
                )}
              </div>

              {/* バックアップ一覧 */}
              {(backupsData as any)?.data?.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs text-gray-500">{t('settings.ui.saved_backups')}</p>
                  <div className="rounded border border-gray-700 divide-y divide-gray-700 max-h-48 overflow-y-auto">
                    {((backupsData as any).data as Array<{ filename: string; size_bytes: number; created_at: string }>).map((b) => (
                      <div key={b.filename} className="flex items-center justify-between px-3 py-2 text-xs text-gray-300">
                        <span className="truncate font-mono">{b.filename}</span>
                        <span className="text-gray-500 shrink-0 ml-2">{(b.size_bytes / 1024).toFixed(0)} KB</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>}

            {/* ── クラウドフォルダ候補 ─────────────────────── */}
            {cloudFolderConfigured && (
              <section className={`${card} rounded-lg p-5 space-y-4`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Share2 size={16} className="text-cyan-400" />
                    <h2 className="text-base font-semibold">{t('settings.ui.cloud_packages')}</h2>
                  </div>
                  <button onClick={() => refetchCloudPackages()} className={`text-xs px-2 py-1 rounded ${isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-400 hover:text-white'}`}>{t('auto.SettingsPage.k16')}</button>
                </div>
                <p className="text-xs text-gray-400 font-mono truncate">{(cloudPackagesData as any)?.folder}</p>

                {cloudPackages.length === 0 ? (
                  <p className="text-sm text-gray-500">{t('settings.ui.no_packages')}</p>
                ) : (
                  <div className="rounded border border-gray-700 divide-y divide-gray-700 max-h-60 overflow-y-auto">
                    {cloudPackages.map((pkg: any) => (
                      <div key={pkg.filename} className="flex items-center justify-between px-3 py-2 text-xs gap-3">
                        <div className="min-w-0">
                          <p className="text-gray-200 font-mono truncate">{pkg.filename}</p>
                          <p className="text-gray-500">{(pkg.size_bytes / 1024).toFixed(0)} KB · {pkg.modified_at?.slice(0, 10)}</p>
                        </div>
                        <button
                          onClick={async () => {
                            const resp = await fetch(`/api/sync/cloud/import_from_path?path=${encodeURIComponent(pkg.path)}&dry_run=false`, { method: 'POST' })
                            const json = await resp.json()
                            alert(json.success
                              ? `完了: 追加${json.data.added} / 更新${json.data.updated} / 競合${json.data.conflicts}`
                              : `エラー: ${json.detail}`)
                            if (json.success) queryClient.invalidateQueries()
                          }}
                          className="flex items-center gap-1 px-2.5 py-1.5 bg-emerald-700 hover:bg-emerald-600 rounded text-white whitespace-nowrap shrink-0"
                        >
                          <Upload size={11} />
                          {t('settings.ui.fetch_in')}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            {/* ── 競合レビュー ─────────────────────────────── */}
            {conflicts.length > 0 && (
              <section className={`${card} rounded-lg p-5 space-y-4`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <AlertCircle size={16} className="text-orange-400" />
                    <h2 className="text-base font-semibold">{t('settings.ui.conflict_review')}</h2>
                    <span className="text-xs bg-orange-500 text-white px-1.5 py-0.5 rounded-full">{conflicts.length}</span>
                  </div>
                  <button onClick={() => refetchConflicts()} className={`text-xs px-2 py-1 rounded ${isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-400 hover:text-white'}`}>{t('auto.SettingsPage.k16')}</button>
                </div>
                <p className="text-xs text-gray-400">
                  インポート時に検出された競合レコードです。ローカルを維持するか、取込データで上書きするかを選択してください。
                </p>
                <div className="space-y-2 max-h-80 overflow-y-auto">
                  {conflicts.map((c: any) => (
                    <div key={c.id} className="rounded border border-orange-900/60 bg-orange-900/10 p-3 space-y-2">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-orange-300">{c.record_table} / <span className="font-mono">{c.record_uuid?.slice(0, 8)}…</span></p>
                          <p className="text-[11px] text-gray-400 mt-0.5">{c.reason}</p>
                          <p className="text-[11px] text-gray-500">
                            ローカル: {c.local_updated_at?.slice(0, 16)} ／ 取込: {c.import_updated_at?.slice(0, 16)}
                            {c.import_device ? ` (${c.import_device})` : ''}
                          </p>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => resolveConflict(c.id, 'keep_local')}
                          className="flex-1 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 rounded transition-colors"
                        >
                          {t('settings.ui.keep_local')}
                        </button>
                        <button
                          onClick={() => resolveConflict(c.id, 'use_incoming')}
                          className="flex-1 py-1.5 text-xs bg-orange-700 hover:bg-orange-600 text-white rounded transition-colors"
                        >
                          {t('settings.ui.overwrite_with_import')}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* ── JSON パッケージ インポート ──────────────────────── */}
            <section>
              <h2 className="text-base font-semibold">{t('settings.ui.json_package_import')}</h2>
              <p className={`text-xs ${textMuted} mt-1 mb-3`}>
                試合一覧ページからエクスポートした JSON ファイルをインポートします。
              </p>
              <div className={`space-y-3 p-3 rounded border ${isLight ? 'bg-gray-50 border-gray-200' : 'bg-gray-900/40 border-gray-700'}`}>
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={(e) => {
                    setPkgImportFile(e.target.files?.[0] ?? null)
                    setPkgImportResult(null)
                  }}
                  className={`block w-full text-xs ${textMuted} file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-medium ${
                    isLight ? 'file:bg-gray-200 file:text-gray-700' : 'file:bg-gray-700 file:text-gray-300'
                  }`}
                />
                {pkgImportFile && (
                  <p className={`text-xs ${textSecondary}`}>選択: {pkgImportFile.name}</p>
                )}
                <div className="flex gap-2">
                  <button
                    onClick={() => handlePkgImport(false)}
                    disabled={!pkgImportFile || pkgImportRunning}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed`}
                  >
                    <Upload size={12} />
                    {pkgImportRunning ? t('settings.ui.importing') : t('settings.ui.import')}
                  </button>
                  {pkgImportResult && !pkgImportResult.success && pkgImportResult.message.includes('競合') && (
                    <button
                      onClick={() => handlePkgImport(true)}
                      disabled={pkgImportRunning}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium text-white bg-orange-600 hover:bg-orange-500 disabled:opacity-40"
                    >
                      {t('settings.ui.reimport_overwrite')}
                    </button>
                  )}
                </div>
                {pkgImportResult && (
                  <p className={`text-xs font-medium ${pkgImportResult.success ? 'text-green-400' : 'text-red-400'}`}>
                    {pkgImportResult.message}
                  </p>
                )}
              </div>
            </section>

            {/* ── DB メンテナンス (admin only) ──────────────────────────────────── */}
            {role === 'admin' && <section className={`${card} rounded-lg p-5 space-y-4`}>
              <div className="flex items-center gap-2">
                <HardDrive size={16} className="text-purple-400" />
                <h2 className="text-base font-semibold">{t('settings.ui.db_maintenance')}</h2>
              </div>

              {/* DB 状態 */}
              {dbStats?.supported && (
                <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
                  <div className="flex justify-between">
                    <span className={textSecondary}>{t('settings.ui.db_size')}</span>
                    <span className="font-mono">{dbStats.file_size_mb} MB</span>
                  </div>
                  <div className="flex justify-between">
                    <span className={textSecondary}>{t('settings.ui.wal_size')}</span>
                    <span className="font-mono">{dbStats.wal_size_mb} MB</span>
                  </div>
                  <div className="flex justify-between">
                    <span className={textSecondary}>{t('settings.ui.free_pages')}</span>
                    <span className={`font-mono ${dbStats.freelist_ratio > 0.1 ? 'text-orange-400' : ''}`}>
                      {dbStats.freelist_count} ({(dbStats.freelist_ratio * 100).toFixed(1)}%)
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className={textSecondary}>auto_vacuum</span>
                    <div className="flex items-center gap-2">
                      <span className={`font-mono text-xs ${dbStats.auto_vacuum === 2 ? 'text-green-400' : 'text-yellow-400'}`}>
                        {dbStats.auto_vacuum === 0 ? 'OFF' : dbStats.auto_vacuum === 1 ? 'FULL' : 'INCREMENTAL'}
                      </span>
                      {/* トグルボタン */}
                      {dbStats.auto_vacuum !== 2 ? (
                        <button
                          onClick={() => handleSetAutoVacuum('incremental')}
                          disabled={dbAvRunning}
                          title={t('auto.SettingsPage.k24')}
                          className="text-[10px] px-2 py-0.5 rounded bg-yellow-600 hover:bg-yellow-500 text-white disabled:opacity-40 transition-colors"
                        >
                          {dbAvRunning ? <RotateCcw size={10} className="animate-spin inline" /> : 'INCREMENTAL に変更'}
                        </button>
                      ) : (
                        <button
                          onClick={() => handleSetAutoVacuum('off')}
                          disabled={dbAvRunning}
                          title={t('auto.SettingsPage.k25')}
                          className="text-[10px] px-2 py-0.5 rounded bg-gray-600 hover:bg-gray-500 text-white disabled:opacity-40 transition-colors"
                        >
                          {dbAvRunning ? <RotateCcw size={10} className="animate-spin inline" /> : 'OFF に戻す'}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {dbAvMessage && (
                <div className="text-xs rounded px-3 py-2 bg-blue-900/40 text-blue-300">
                  {dbAvMessage}
                </div>
              )}

              <p className="text-xs text-gray-400 leading-relaxed">
                <span className="font-medium text-gray-300">{t('auto.SettingsPage.k17')}</span>
                WAL チェックポイントと incremental vacuum を実行します（auto_vacuum=INCREMENTAL 時に空きページを回収）。
                大量削除後や定期メンテとして実行してください。
              </p>

              {dbMaintResult && (
                <div className={`text-xs rounded px-3 py-2 ${
                  dbMaintResult.freed_mb > 0
                    ? 'bg-green-900/40 text-green-300'
                    : 'bg-gray-700 text-gray-300'
                }`}>
                  {dbMaintResult.freed_mb > 0
                    ? `${dbMaintResult.freed_pages} ページ（${dbMaintResult.freed_mb} MB）を回収しました`
                    : '回収可能な空きページはありませんでした'}
                </div>
              )}

              <button
                onClick={handleDbMaintenance}
                disabled={dbMaintRunning || dbAvRunning}
                className={`flex items-center gap-2 px-4 py-2 rounded text-sm font-medium transition-colors ${
                  dbMaintRunning || dbAvRunning
                    ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                    : 'bg-purple-700 hover:bg-purple-600 text-white'
                }`}
              >
                {dbMaintRunning
                  ? <><RotateCcw size={13} className="animate-spin" /> {t('auto.SettingsPage.k18')}</>
                  : <><Zap size={13} /> {t('auto.SettingsPage.k19')}</>
                }
              </button>
            </section>}

          </div>
        )}

        {/* クラスタタブ */}
        {activeTab === 'cluster' && (
          <div className="space-y-6">
            <ClusterSettingsPanel />
          </div>
        )}

        {/* アカウント設定タブ */}
        {activeTab === 'account' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">

            {/* テーマ */}
            <section>
              <h2 className={`text-lg font-medium ${textHeading} mb-1`}>{t('settings.ui.theme')}</h2>
              <p className={`text-xs ${textMuted} mb-3`}>{t('settings.ui.theme_hint')}</p>
              <div className="flex gap-3">
                {([
                  { mode: 'dark' as const, label: t('settings.ui.dark'), Icon: Moon },
                  { mode: 'light' as const, label: t('settings.ui.light'), Icon: Sun },
                ]).map(({ mode, label, Icon }) => (
                  <button
                    key={mode}
                    onClick={() => setTheme(mode)}
                    className={`flex items-center gap-2 flex-1 justify-center px-4 py-3 rounded-lg border transition-colors ${
                      theme === mode
                        ? 'border-blue-500 bg-blue-500/10 text-blue-400'
                        : isLight
                          ? 'border-gray-300 bg-white text-gray-600 hover:border-gray-400'
                          : 'border-gray-600 bg-gray-800 text-gray-300 hover:border-gray-500'
                    }`}
                  >
                    <Icon size={16} />
                    <span className="font-medium text-sm">{label}</span>
                    {theme === mode && <CheckCircle size={14} className="text-blue-400 ml-auto" />}
                  </button>
                ))}
              </div>
            </section>

            {/* 言語 */}
            <section>
              <h2 className={`text-lg font-medium ${textHeading} mb-1`}>{t('settings.ui.language')}</h2>
              <p className={`text-xs ${textMuted} mb-3`}>{t('settings.ui.language_hint')}</p>
              <div className="flex gap-3">
                {SUPPORTED_LANGS.map((lng) => {
                  const active = (i18n.language as SupportedLang) === lng
                  const label = lng === 'ja' ? t('settings.ui.language_ja') : t('settings.ui.language_en')
                  return (
                    <button
                      key={lng}
                      onClick={() => setLanguage(lng as SupportedLang)}
                      className={`flex items-center gap-2 flex-1 justify-center px-4 py-3 rounded-lg border transition-colors ${
                        active
                          ? 'border-blue-500 bg-blue-500/10 text-blue-400'
                          : isLight
                            ? 'border-gray-300 bg-white text-gray-600 hover:border-gray-400'
                            : 'border-gray-600 bg-gray-800 text-gray-300 hover:border-gray-500'
                      }`}
                    >
                      <Globe size={16} />
                      <span className="font-medium text-sm">{label}</span>
                      {active && <CheckCircle size={14} className="text-blue-400 ml-auto" />}
                    </button>
                  )
                })}
              </div>
            </section>

            {/* ロール設定 */}
            <section>
              <h2 className={`text-lg font-medium ${textHeading} mb-1`}>Account</h2>
              <p className={`text-xs ${textMuted} mb-3`}>
                The active role is fixed by login. To switch users or roles, log out and sign in again.
              </p>
              <div className={`rounded-lg border p-4 space-y-2 ${isLight ? 'border-gray-300 bg-white' : 'border-gray-600 bg-gray-800'}`}>
                <div className={`text-sm ${textSecondary}`}>Display name: <span className={textHeading}>{displayName ?? 'Unset'}</span></div>
                <div className={`text-sm ${textSecondary}`}>Role: <span className={textHeading}>{role ? t(`auth.role.${role}`) : 'Not logged in'}</span></div>
                <div className={`text-sm ${textSecondary}`}>User ID: <span className={textHeading}>{displayName ?? '-'}</span></div>
                <div className={`text-sm ${textSecondary}`}>Team: <span className={textHeading}>{teamName ?? '-'}</span></div>
              </div>
              <div className="mt-4 flex flex-col gap-3">
                <button
                  onClick={handleLogout}
                  className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                    isLight ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-red-700 hover:bg-red-600 text-white'
                  }`}
                >
                  <LogOut size={16} />
                  {t('auth.logout')}
                </button>
                <p className={`text-xs ${textMuted}`}>
                  Auth state is stored per session. After closing the app or browser, the next launch starts from the login screen.
                </p>
              </div>
            </section>

            {/* パスワード変更 (ログイン済みユーザ全員) */}
            <PasswordChangeCard isLight={isLight} />

            {/* アプリ再起動 (admin only) */}
            {role === 'admin' && (
              <section>
                <h2 className={`text-lg font-medium ${textHeading} mb-1`}>{t('settings.ui.restart_app')}</h2>
                <p className={`text-xs ${textMuted} mb-3`}>
                  設定変更や不具合が発生した際にアプリを再起動します。未保存のアノテーションデータは失われます。
                </p>
                <button
                  onClick={() => {
                    if (window.shuttlescope?.restartApp) {
                      window.shuttlescope.restartApp()
                    } else {
                      window.location.reload()
                    }
                  }}
                  className={`flex items-center gap-2 px-4 py-2.5 rounded border transition-colors text-sm font-medium
                    ${isLight
                      ? 'border-gray-300 bg-white text-gray-700 hover:border-gray-400 hover:bg-gray-50'
                      : 'border-gray-600 bg-gray-800 text-gray-300 hover:border-gray-500 hover:bg-gray-700'
                    }`}
                >
                  <RotateCcw size={15} />
                  {t('settings.ui.restart_app_btn')}
                </button>
              </section>
            )}

            {/* バックエンドコンソール (admin only) */}
            {role === 'admin' && (
              <BackendConsole isLight={isLight} textHeading={textHeading} textMuted={textMuted} />
            )}

          </div>
        )}
      </div>

      {/* 選手フォームモーダル */}
      {showPlayerForm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className={`${card} rounded-lg w-full max-w-lg`}>
            <div className={`flex items-center justify-between px-6 py-4 border-b ${borderLine}`}>
              <h2 className={`text-lg font-semibold ${textHeading}`}>{editingPlayer ? '選手編集' : '選手追加'}</h2>
              <button onClick={() => { setShowPlayerForm(false); setEditingPlayer(null) }} className={`${textMuted} ${isLight ? 'hover:text-gray-900' : 'hover:text-white'}`}>✕</button>
            </div>
            <form onSubmit={handlePlayerSubmit} className="p-6 flex flex-col gap-3">
              <div>
                <label className={`block text-sm ${textSecondary} mb-1`}>{t('player.name')} *</label>
                <input
                  value={playerForm.name}
                  onChange={(e) => setPlayerForm({ ...playerForm, name: e.target.value })}
                  required
                  className={`w-full ${inputClass}`}
                  placeholder={t('auto.SettingsPage.k29')}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('player.name_en')}</label>
                  <input
                    value={playerForm.name_en}
                    onChange={(e) => setPlayerForm({ ...playerForm, name_en: e.target.value })}
                    className={`w-full ${inputClass}`}
                    placeholder="Yamada Taro"
                  />
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('player.team')}</label>
                  <input
                    value={playerForm.team}
                    onChange={(e) => setPlayerForm({ ...playerForm, team: e.target.value })}
                    className={`w-full ${inputClass}`}
                  />
                  {editingPlayer?.team_history && editingPlayer.team_history.length > 0 && (
                    <div className={`mt-1.5 text-xs ${textMuted} space-y-0.5`}>
                      <div className="font-medium">{t('auto.SettingsPage.k20')}</div>
                      {editingPlayer.team_history.map((h: TeamHistoryEntry, i: number) => (
                        <div key={i} className="flex items-center gap-1">
                          <span className={`px-1.5 py-0.5 rounded ${isLight ? 'bg-gray-100 text-gray-600' : 'bg-gray-700 text-gray-400'}`}>
                            {h.team}
                          </span>
                          {h.until && <span className="text-gray-500">〜{h.until}</span>}
                          {h.note && <span className="text-gray-500 italic">{h.note}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('player.nationality')}</label>
                  <input
                    value={playerForm.nationality}
                    onChange={(e) => setPlayerForm({ ...playerForm, nationality: e.target.value })}
                    className={`w-full ${inputClass}`}
                    placeholder="JPN"
                  />
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('player.dominant_hand')}</label>
                  <select
                    value={playerForm.dominant_hand}
                    onChange={(e) => setPlayerForm({ ...playerForm, dominant_hand: e.target.value as 'R' | 'L' })}
                    className={`w-full ${inputClass}`}
                  >
                    <option value="R">{t('settings.ui.right_handed')}</option>
                    <option value="L">{t('settings.ui.left_handed')}</option>
                  </select>
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('player.birth_year')}</label>
                  <input
                    type="number"
                    value={playerForm.birth_year}
                    onChange={(e) => setPlayerForm({ ...playerForm, birth_year: e.target.value })}
                    className={`w-full ${inputClass}`}
                    placeholder="2000"
                  />
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('player.world_ranking')}</label>
                  <input
                    type="number"
                    value={playerForm.world_ranking}
                    onChange={(e) => setPlayerForm({ ...playerForm, world_ranking: e.target.value })}
                    className={`w-full ${inputClass}`}
                    placeholder="100"
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={playerForm.is_target}
                  onChange={(e) => setPlayerForm({ ...playerForm, is_target: e.target.checked })}
                  className="w-4 h-4"
                />
                <span className={`text-sm ${textSecondary}`}>{t('player.is_target')}（解析メイン対象）</span>
              </label>
              <div>
                <label className={`block text-sm ${textSecondary} mb-1`}>{t('player.notes')}</label>
                <textarea
                  value={playerForm.notes}
                  onChange={(e) => setPlayerForm({ ...playerForm, notes: e.target.value })}
                  rows={2}
                  className={`w-full ${inputClass}`}
                />
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={createPlayer.isPending || updatePlayer.isPending}
                  className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium disabled:opacity-50"
                >
                  {(createPlayer.isPending || updatePlayer.isPending) ? '保存中...' : '保存'}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowPlayerForm(false); setEditingPlayer(null) }}
                  className={`flex-1 py-2 ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-700' : 'bg-gray-700 hover:bg-gray-600'} rounded text-sm`}
                >
                  {t('app.cancel')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── バックエンドコンソールコンポーネント ─────────────────────────────────────

function BackendConsole({
  isLight,
  textHeading,
  textMuted,
}: {
  isLight: boolean
  textHeading: string
  textMuted: string
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [lines, setLines] = useState<string[]>([])
  const endRef = useRef<HTMLTextAreaElement | null>(null)

  // 初回開いたときにバッファを取得
  useEffect(() => {
    if (!open) return
    if (window.shuttlescope?.getBackendLog) {
      window.shuttlescope.getBackendLog().then(setLines).catch(() => {})
    }
  }, [open])

  // リアルタイム受信
  useEffect(() => {
    if (!open) return
    const unsub = window.shuttlescope?.onBackendLog?.((line) => {
      setLines(prev => {
        const next = [...prev, line]
        return next.length > 500 ? next.slice(-500) : next
      })
    })
    return () => { unsub?.() }
  }, [open])

  // 末尾オートスクロール（textarea）
  useEffect(() => {
    if (open && endRef.current) {
      endRef.current.scrollTop = endRef.current.scrollHeight
    }
  }, [lines, open])

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <h2 className={`text-lg font-medium ${textHeading}`}>{t('settings.ui.backend_console')}</h2>
        <button
          onClick={() => setOpen(v => !v)}
          className={`text-xs px-2 py-1 rounded border transition-colors ${
            isLight
              ? 'border-gray-300 text-gray-600 hover:bg-gray-100'
              : 'border-gray-600 text-gray-400 hover:bg-gray-700'
          }`}
        >
          {open ? t('settings.ui.hide') : t('settings.ui.show')}
        </button>
      </div>
      <p className={`text-xs ${textMuted} mb-2`}>
        Pythonバックエンドのログ（YOLO検出エラーや推論スコアを確認できます）
      </p>
      {open && (
        <textarea
          readOnly
          value={lines.length === 0 ? '(ログなし)' : lines.join('\n')}
          ref={endRef}
          className={`w-full rounded font-mono text-[10px] p-2 h-72 resize-none outline-none ${
            isLight ? 'bg-gray-100 text-gray-800' : 'bg-gray-900 text-gray-300'
          }`}
          style={{ whiteSpace: 'pre', overflowX: 'auto' }}
          spellCheck={false}
        />
      )}
      {open && (
        <div className="flex items-center gap-3 mt-1">
          <button
            onClick={() => setLines([])}
            className={`text-[10px] ${textMuted} hover:underline`}
          >
            {t('settings.ui.clear')}
          </button>
          <span className={`text-[10px] ${textMuted}`}>{lines.length} 行 — Ctrl+A → Ctrl+C でコピー可</span>
        </div>
      )}
    </section>
  )
}
