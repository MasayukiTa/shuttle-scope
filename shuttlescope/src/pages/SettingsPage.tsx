import { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Edit2, Trash2, CheckCircle, CheckCircle2, AlertCircle, Play, Cpu, Zap, ToggleLeft, ToggleRight, Wifi, WifiOff, Share2, Bookmark, Copy, Globe, Power, PowerOff, Download, Upload, HardDrive, FileArchive, Eye, Sun, Moon, ChevronUp, ChevronDown, ChevronsUpDown, Search, X } from 'lucide-react'
import QRCode from 'qrcode'
import { apiGet, apiPost, apiPut, apiDelete } from '@/api/client'
import { Player, TeamHistoryEntry, UserRole, SharedSession, NetworkDiagnostics } from '@/types'
import { useAuth } from '@/hooks/useAuth'
import { useSettings } from '@/hooks/useSettings'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTheme } from '@/hooks/useTheme'

type PlayerSortKey = 'name' | 'team' | 'nationality' | 'world_ranking' | 'is_target'

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
            title="コピー"
          >
            {copied ? <CheckCircle size={12} className="text-green-500" /> : <Copy size={12} />}
          </button>
        </div>
      </div>
    </div>
  )
}

export function SettingsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { role, setRole } = useAuth()

  const [showPlayerForm, setShowPlayerForm] = useState(false)
  const [editingPlayer, setEditingPlayer] = useState<Player | null>(null)
  const [playerForm, setPlayerForm] = useState<PlayerFormData>(defaultPlayerForm())
  const [activeTab, setActiveTab] = useState<'players' | 'review' | 'tracknet' | 'sharing' | 'data' | 'account'>('players')

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
          cloudflare: { available: boolean }
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

  async function resolveConflict(id: number, resolution: 'keep_local' | 'use_incoming') {
    await fetch(`/api/sync/conflicts/${id}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolution }),
    })
    refetchConflicts()
    queryClient.invalidateQueries()
  }

  // クラウドフォルダ内パッケージ一覧
  const { data: cloudPackagesData, refetch: refetchCloudPackages } = useQuery({
    queryKey: ['sync-cloud-packages'],
    queryFn: () => apiGet<{ success: boolean; data: Array<{ filename: string; path: string; size_bytes: number; modified_at: string }>; configured: boolean; folder: string }>('/sync/cloud/packages'),
    enabled: activeTab === 'data',
  })
  const cloudPackages = (cloudPackagesData as any)?.data ?? []
  const cloudFolderConfigured = (cloudPackagesData as any)?.configured ?? false

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
    mutationFn: (id: number) => apiDelete(`/players/${id}`),
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
  }, [players, playerSearch, targetOnly, playerSortKey, playerSortDir])

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
      {/* ヘッダー */}
      <div className={`px-6 py-4 border-b ${borderLine}`}>
        <h1 className={`text-xl font-semibold ${textHeading}`}>{t('nav.settings')}</h1>
      </div>

      {/* タブ（horizontal scroll: モバイル対応） */}
      <div className={`relative border-b ${borderLine}`}>
        <div className="flex overflow-x-auto scrollbar-hide">
          {([
            { key: 'players', label: '選手管理' },
            { key: 'review', label: t('review.title'), badge: reviewPlayersData?.data?.length ?? 0 },
            { key: 'tracknet', label: t('tracknet.tab_label') },
            { key: 'sharing', label: t('sharing.tab_label') },
            { key: 'data', label: 'データ管理' },
            { key: 'account', label: 'アカウント設定' },
          ] as const).map((tab) => (
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
              {'badge' in tab && tab.badge > 0 && (
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
              <h2 className={`text-lg font-medium ${textHeading}`}>選手一覧</h2>
              <button
                onClick={() => { setEditingPlayer(null); setPlayerForm(defaultPlayerForm()); setShowPlayerForm(true) }}
                className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-sm"
              >
                <Plus size={14} />
                選手追加
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
                    aria-label="クリア"
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
                        { key: 'name', label: '名前' },
                        { key: 'team', label: 'チーム' },
                        { key: 'nationality', label: '国' },
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
                    <th className="text-left py-2 pr-3 whitespace-nowrap">手</th>
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
                        対象
                        {playerSortKey === 'is_target' ? (
                          playerSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                        ) : (
                          <ChevronsUpDown size={12} className="opacity-30" />
                        )}
                      </span>
                    </th>
                    <th className="text-left py-2 whitespace-nowrap">操作</th>
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
                            title="クリックでコピー"
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
                選手が登録されていません。「選手追加」ボタンで追加してください。
              </div>
            )}
            {players.length > 0 && filteredPlayers.length === 0 && (
              <div className={`text-center ${textMuted} py-8 text-sm`}>
                絞り込み条件に一致する選手がいません。
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
                      <th className="text-left py-2 pr-4">名前</th>
                      <th className="text-left py-2 pr-4">{t('review.profile_status')}</th>
                      <th className="text-left py-2 pr-4">利き手</th>
                      <th className="text-left py-2 pr-4">試合数</th>
                      <th className="text-left py-2">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reviewPlayersData.data.map((p) => (
                      <tr key={p.id} className={`border-b ${isLight ? 'border-gray-100 hover:bg-gray-50' : 'border-gray-800 hover:bg-gray-800/50'}`}>
                        <td className="py-2 pr-4">
                          <div className="flex items-center gap-2">
                            {p.name}
                            {p.profile_status === 'provisional' && (
                              <span className="text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded">暫定</span>
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
                              title="編集"
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
          <div className="max-w-xl space-y-6">
            <h2 className={`text-lg font-medium ${textHeading}`}>{t('tracknet.tab_label')}</h2>

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
                    <p className="text-gray-500 font-sans"># または一括: python -m backend.tracknet.setup all</p>
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
                  { value: 'auto', label: 'Auto (OpenVINO → ONNX → TensorFlow)' },
                  { value: 'tensorflow_cpu', label: 'TensorFlow CPU / Intel' },
                  { value: 'openvino', label: 'OpenVINO (Intel GPU / CPU)' },
                  { value: 'onnx_cpu', label: 'ONNX CPU' },
                ] as const).map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => updateSettings({ tracknet_backend: opt.value })}
                    className={`flex-1 py-2 px-3 rounded text-sm border transition-colors ${
                      appSettings.tracknet_backend === opt.value
                        ? 'border-blue-500 bg-blue-900/30 text-blue-300'
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
                <p className={`font-medium ${isLight ? 'text-gray-600' : 'text-gray-400'}`}>モデル状態</p>
                {!yoloStatus ? (
                  <p className={isLight ? 'text-gray-500' : 'text-gray-500'}>バックエンド接続中...</p>
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
                          <span className={isLight ? 'text-red-700' : 'text-red-300'}>ロード失敗</span>
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
                        <span className={isLight ? 'text-orange-700' : 'text-orange-300'}>パッケージ未導入</span>
                      </div>
                      <code className={`block text-[10px] px-2 py-1 rounded ${isLight ? 'bg-gray-200 text-gray-700' : 'bg-gray-800 text-gray-300'}`}>
                        pip install ultralytics
                      </code>
                    </div>
                  )
                })()}
              </div>
            </div>
          </div>
        )}

        {/* 共有設定タブ (R-001/R-002/Q-002/Q-008) */}
        {activeTab === 'sharing' && (
          <div className="max-w-xl space-y-6">
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
                    <p className={`text-xs animate-pulse ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>URL取得中…（数秒かかります）</p>
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
          <div className="max-w-2xl space-y-6">

            {/* ── デバイス・同期設定 ────────────────────────── */}
            <section className={`${card} rounded-lg p-5 space-y-4`}>
              <div className="flex items-center gap-2">
                <HardDrive size={16} className="text-gray-400" />
                <h2 className="text-base font-semibold">同期設定</h2>
              </div>
              <div className="space-y-3">
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>デバイス名（エクスポートパッケージに記録）</label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={appSettings.sync_device_id}
                      onChange={(e) => updateSettings({ sync_device_id: e.target.value })}
                      placeholder="自動生成されます"
                      className="flex-1 bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white font-mono"
                    />
                  </div>
                  <p className="text-[11px] text-gray-500 mt-0.5">PC ごとに一意な識別子。パッケージのどの端末由来かを記録します。</p>
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>同期フォルダパス（OneDrive / SharePoint / Google Drive 等）</label>
                  <input
                    type="text"
                    value={appSettings.sync_folder_path}
                    onChange={(e) => updateSettings({ sync_folder_path: e.target.value })}
                    placeholder="例: C:\Users\YourName\OneDrive\ShuttleScope"
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white font-mono"
                  />
                  <p className="text-[11px] text-gray-500 mt-0.5">設定するとフォルダ内の .sspkg ファイルを直接インポートできます。</p>
                </div>
              </div>
            </section>

            {/* ── エクスポート ──────────────────────────────── */}
            <section className={`${card} rounded-lg p-5 space-y-4`}>
              <div className="flex items-center gap-2">
                <Download size={16} className="text-blue-400" />
                <h2 className="text-base font-semibold">エクスポート</h2>
              </div>
              <p className="text-xs text-gray-400">
                試合データを <code className="bg-gray-700 px-1 rounded">.sspkg</code> 形式でダウンロード。別 PC へのデータ持ち運びや引き継ぎに使用します。
              </p>

              {/* エクスポートモード切替 */}
              <div className="flex gap-1.5">
                {([{ key: 'match', label: '試合選択' }, { key: 'change_set', label: '差分（更新日以降）' }] as const).map(({ key, label }) => (
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
                    <label className="text-sm text-gray-400">エクスポートする試合（クリックで選択）</label>
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
                        placeholder="例: 1, 3, 7"
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
                  <label className={`block text-sm ${textSecondary} mb-1`}>この日時以降に更新されたデータを全てエクスポート</label>
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
                <h2 className="text-base font-semibold">インポート</h2>
              </div>
              <p className="text-xs text-gray-400">
                別 PC からエクスポートされた <code className="bg-gray-700 px-1 rounded">.sspkg</code> ファイルを取り込みます。既存データはレコード単位でマージされます。
              </p>

              <div>
                <label className={`block text-sm ${textSecondary} mb-1`}>パッケージファイル（.sspkg）</label>
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
                          { label: '追加', value: importPreview.data?.merge_preview?.added ?? 0, color: 'text-blue-400' },
                          { label: '更新', value: importPreview.data?.merge_preview?.updated ?? 0, color: 'text-yellow-400' },
                          { label: '保持', value: importPreview.data?.merge_preview?.kept ?? 0, color: 'text-gray-400' },
                          { label: '競合', value: importPreview.data?.merge_preview?.conflicts ?? 0, color: 'text-orange-400' },
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
                      <p className="font-medium text-emerald-300 mb-1">インポート完了</p>
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

            {/* ── バックアップ ──────────────────────────────── */}
            <section className={`${card} rounded-lg p-5 space-y-4`}>
              <div className="flex items-center gap-2">
                <HardDrive size={16} className="text-purple-400" />
                <h2 className="text-base font-semibold">バックアップ</h2>
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
                  {backupRunning ? 'バックアップ中...' : '今すぐバックアップ'}
                </button>
                {backupResult && (
                  <p className="text-xs text-gray-300 truncate max-w-xs">{backupResult}</p>
                )}
              </div>

              {/* バックアップ一覧 */}
              {(backupsData as any)?.data?.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs text-gray-500">保存済みバックアップ</p>
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
            </section>

            {/* ── クラウドフォルダ候補 ─────────────────────── */}
            {cloudFolderConfigured && (
              <section className={`${card} rounded-lg p-5 space-y-4`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Share2 size={16} className="text-cyan-400" />
                    <h2 className="text-base font-semibold">同期フォルダ内パッケージ</h2>
                  </div>
                  <button onClick={() => refetchCloudPackages()} className={`text-xs px-2 py-1 rounded ${isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-400 hover:text-white'}`}>更新</button>
                </div>
                <p className="text-xs text-gray-400 font-mono truncate">{(cloudPackagesData as any)?.folder}</p>

                {cloudPackages.length === 0 ? (
                  <p className="text-sm text-gray-500">パッケージファイルがありません</p>
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
                          取込
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
                    <h2 className="text-base font-semibold">競合レビュー</h2>
                    <span className="text-xs bg-orange-500 text-white px-1.5 py-0.5 rounded-full">{conflicts.length}</span>
                  </div>
                  <button onClick={() => refetchConflicts()} className={`text-xs px-2 py-1 rounded ${isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-400 hover:text-white'}`}>更新</button>
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
                          ローカルを維持
                        </button>
                        <button
                          onClick={() => resolveConflict(c.id, 'use_incoming')}
                          className="flex-1 py-1.5 text-xs bg-orange-700 hover:bg-orange-600 text-white rounded transition-colors"
                        >
                          取込データで上書き
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

          </div>
        )}

        {/* アカウント設定タブ */}
        {activeTab === 'account' && (
          <div className="max-w-md space-y-8">

            {/* テーマ */}
            <section>
              <h2 className={`text-lg font-medium ${textHeading} mb-1`}>テーマ</h2>
              <p className={`text-xs ${textMuted} mb-3`}>ライト / ダークモードを切り替えます</p>
              <div className="flex gap-3">
                {([
                  { mode: 'dark' as const, label: 'ダーク', Icon: Moon },
                  { mode: 'light' as const, label: 'ライト', Icon: Sun },
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

            {/* ロール設定 */}
            <section>
              <h2 className={`text-lg font-medium ${textHeading} mb-1`}>ロール設定（POCフェーズ）</h2>
              <p className={`text-xs ${textMuted} mb-3`}>操作権限の種別を選択します</p>
              <div className="flex flex-col gap-2">
                {(['analyst', 'coach', 'player'] as UserRole[]).map((r) => (
                  <button
                    key={r}
                    onClick={() => setRole(r)}
                    className={`flex items-center justify-between px-4 py-3 rounded border ${
                      role === r
                        ? 'border-blue-500 bg-blue-900/30 text-blue-300'
                        : isLight
                          ? 'border-gray-300 bg-white text-gray-600 hover:border-gray-400'
                          : 'border-gray-600 bg-gray-800 text-gray-300 hover:border-gray-500'
                    }`}
                  >
                    <span className="font-medium">{t(`roles.${r}`)}</span>
                    {role === r && <CheckCircle size={16} className="text-blue-400" />}
                  </button>
                ))}
              </div>
              <p className="text-xs text-gray-500 mt-3">
                ※ POCフェーズでは簡易ロール管理（ローカルストレージ保存）。
                本番展開時にJWT認証へ移行予定。
              </p>
            </section>

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
                  placeholder="例: 山田 太郎"
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
                      <div className="font-medium">所属履歴:</div>
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
                    <option value="R">右利き</option>
                    <option value="L">左利き</option>
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
