import { useState, useRef, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Play, Trash2, Download, Filter, AlertCircle, Search, UserPlus, User, FolderOpen, TrendingUp, Pencil, ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'
import { clsx } from 'clsx'
import { apiGet, apiPost, apiPut, apiDelete, newIdempotencyKey } from '@/api/client'
import { Match, Player, TournamentLevel, MatchFormat, MatchResult, MATCH_ROUNDS } from '@/types'
import { QuickStartModal } from '@/components/annotation/QuickStartModal'
import { SearchableSelect, SearchableOption } from '@/components/common/SearchableSelect'
import { DateRangeFilter } from '@/components/common/DateRangeFilter'
import { DateRangeSlider } from '@/components/common/DateRangeSlider'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useAuth } from '@/hooks/useAuth'
import { PipelineJobBadge } from '@/components/analysis/PipelineJobBadge'

// 試合登録フォーム
interface MatchFormData {
  tournament: string
  tournament_level: TournamentLevel
  round: string
  date: string
  format: MatchFormat
  player_a_id: number | ''
  player_b_id: number | ''
  partner_a_id: number | ''
  partner_b_id: number | ''
  initial_server: 'player_a' | 'player_b' | ''
  result: MatchResult
  final_score: string
  video_url: string
  video_local_path: string
  notes: string
  // Phase B-13: admin のみ操作可能。「全チームから閲覧可能な公開プール試合」として登録するか
  is_public_pool: boolean
}

const defaultForm = (): MatchFormData => ({
  tournament: '',
  tournament_level: '国内',
  round: MATCH_ROUNDS[3],
  date: new Date().toISOString().split('T')[0],
  format: 'singles',
  player_a_id: '',
  player_b_id: '',
  partner_a_id: '',
  partner_b_id: '',
  initial_server: '',
  result: 'win',
  final_score: '',
  video_url: '',
  video_local_path: '',
  notes: '',
  is_public_pool: false,
})

// ─── 選手コンボボックス（名前検索 + 暫定登録対応）────────────────────────────

interface PlayerComboboxProps {
  label: string
  required?: boolean
  value: number | ''
  query: string
  setQuery: (q: string) => void
  setValue: (id: number | '') => void
  candidates: Player[]
  isLight: boolean
  textSecondary: string
  placeholder?: string
}

function PlayerCombobox({
  label, required = false, value, query, setQuery, setValue,
  candidates, isLight, textSecondary, placeholder = '名前を入力して検索...',
}: PlayerComboboxProps) {
  const { t } = useTranslation()

  const [showDropdown, setShowDropdown] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={containerRef}>
      <label className={`block text-sm ${textSecondary} mb-1`}>
        {label}{required && ' *'}
      </label>
      <div className="relative">
        <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setValue('')
            setShowDropdown(true)
          }}
          onFocus={() => { if (query.trim().length >= 1) setShowDropdown(true) }}
          placeholder={placeholder}
          autoComplete="off"
          className={`w-full ${isLight ? 'bg-white border-gray-300 text-gray-900' : 'bg-gray-700 border-gray-600 text-white'} border rounded pl-8 pr-3 py-2 text-sm`}
        />
        {value !== '' && (
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
            <User size={12} className="text-green-400" />
            <span className="text-[10px] text-green-400">{t('auto.MatchListPage.k1')}</span>
          </div>
        )}
      </div>
      {showDropdown && query.trim().length >= 1 && (
        <div className={`absolute z-20 top-full mt-1 w-full ${isLight ? 'bg-white border-gray-300' : 'bg-gray-700 border-gray-600'} border rounded shadow-lg max-h-40 overflow-y-auto`}>
          {candidates.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setValue(p.id)
                setQuery(p.name)
                setShowDropdown(false)
              }}
              className={`w-full text-left px-3 py-2 ${isLight ? 'hover:bg-gray-100' : 'hover:bg-gray-600'} text-sm flex items-center gap-2 min-w-0`}
            >
              <User size={12} className="text-gray-400 shrink-0" />
              <span className="truncate">{p.name}</span>
              {p.team && (
                <span className="text-xs text-blue-300 bg-blue-900/30 px-1.5 rounded shrink-0">{p.team}</span>
              )}
              {p.needs_review && <span className="text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded shrink-0">{t('match.list.tentative')}</span>}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              setValue('')
              setShowDropdown(false)
            }}
            className={`w-full text-left px-3 py-2 hover:bg-blue-500/10 text-sm flex items-center gap-2 text-blue-400 border-t ${isLight ? 'border-gray-200' : 'border-gray-600'}`}
          >
            <UserPlus size={12} className="shrink-0" />
            <span>「{query.trim()}」を暫定登録して作成</span>
          </button>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

export function MatchListPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { card, textHeading, textSecondary, textMuted, textFaint, isLight } = useCardTheme()
  const { role, playerId, teamName } = useAuth()

  const bodyBg = isLight ? 'bg-gray-50' : 'bg-gray-900'
  const borderLine = isLight ? 'border-gray-200' : 'border-gray-700'
  const inputClass = isLight
    ? 'bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900'
    : 'bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white'

  const [showForm, setShowForm] = useState(false)
  const [showQuickStart, setShowQuickStart] = useState(false)
  const [editingMatchId, setEditingMatchId] = useState<number | null>(null)
  const [form, setForm] = useState<MatchFormData>(defaultForm())
  // Phase 1: 編集モードで既存動画のファイル名のみ表示する（パスは露出しない）
  const [editingVideoFilename, setEditingVideoFilename] = useState<string>('')
  const [analystSide, setAnalystSide] = useState<'top' | 'bottom'>('bottom')
  const [filterPlayer, setFilterPlayer] = useState<string>(() => searchParams.get('player_id') ?? '')
  const [filterLevel, setFilterLevel] = useState<string>('')
  const [filterIncompleteOnly, setFilterIncompleteOnly] = useState(false)
  const [filterDateFrom, setFilterDateFrom] = useState<string | null>(null)
  const [filterDateTo, setFilterDateTo] = useState<string | null>(null)
  const [filterText, setFilterText] = useState<string>('')
  // 試合一覧ソート（クライアントサイド）
  type MatchSortKey = 'date' | 'tournament' | 'result' | 'status'
  const [matchSortKey, setMatchSortKey] = useState<MatchSortKey>('date')
  const [matchSortDir, setMatchSortDir] = useState<'asc' | 'desc'>('desc')
  // 進捗列：優先表示するステータス（null = デフォルト順）
  const [statusSortTarget, setStatusSortTarget] = useState<string | null>(null)
  const [showStatusDropdown, setShowStatusDropdown] = useState(false)
  const statusDropdownRef = useRef<HTMLDivElement>(null)

  // 進捗ドロップダウン外クリック閉じ
  useEffect(() => {
    if (!showStatusDropdown) return
    const handler = (e: MouseEvent) => {
      if (statusDropdownRef.current && !statusDropdownRef.current.contains(e.target as Node)) {
        setShowStatusDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showStatusDropdown])
  // インライン削除確認
  const [deleteConfirmMatchId, setDeleteConfirmMatchId] = useState<number | null>(null)
  // 一括選択
  const [selectedMatchIds, setSelectedMatchIds] = useState<Set<number>>(new Set())
  const [downloadJobIds, setDownloadJobIds] = useState<Record<number, string>>({})
  const [downloadQuality, setDownloadQuality] = useState<string>('720')
  const [downloadCookieBrowser, setDownloadCookieBrowser] = useState<string>('')

  // 選手コンボボックス用クエリ
  const [playerAQuery, setPlayerAQuery] = useState('')
  const [playerBQuery, setPlayerBQuery] = useState('')
  const [playerATeam, setPlayerATeam] = useState('')
  const [playerBTeam, setPlayerBTeam] = useState('')
  const [partnerAQuery, setPartnerAQuery] = useState('')
  const [partnerBQuery, setPartnerBQuery] = useState('')

  const resetPlayerFields = () => {
    setPlayerAQuery('')
    setPlayerBQuery('')
    setPlayerATeam('')
    setPlayerBTeam('')
    setPartnerAQuery('')
    setPartnerBQuery('')
  }

  // 試合一覧取得
  const { data: matchesData, isLoading } = useQuery({
    queryKey: ['matches', filterPlayer, filterLevel, filterIncompleteOnly, role, playerId, teamName],
    queryFn: () => {
      const params: Record<string, string | boolean> = {}
      if (filterPlayer) params.player_id = filterPlayer
      if (filterLevel) params.tournament_level = filterLevel
      if (filterIncompleteOnly) params.incomplete_only = true
      return apiGet<{ success: boolean; data: Match[] }>('/matches', params)
    },
  })

  // 選手一覧取得
  const { data: playersData } = useQuery({
    queryKey: ['players'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players'),
  })

  // 動画 DL ジョブ一覧 (5 秒間隔 polling) — 試合一覧で「DL 中」バッジを表示するため
  type DownloadInfo = {
    job_id: string
    status: string  // queued | pending | downloading | processing | starting | error
    percent?: string
    speed?: string
    eta?: string
    error?: string
  }
  const { data: activeDownloads } = useQuery({
    queryKey: ['matches', 'downloads', 'active'],
    queryFn: () => apiGet<{ success: boolean; data: Record<string, DownloadInfo> }>('/matches/downloads/active'),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  })
  const dlByMatch = activeDownloads?.data ?? {}

  // 選手検索（各フィールド）
  const { data: playerASearchData } = useQuery({
    queryKey: ['players-search-a', playerAQuery],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players/search', { q: playerAQuery }),
    enabled: playerAQuery.trim().length >= 1 && form.player_a_id === '',
  })
  const playerACandidates = playerASearchData?.data ?? []

  const { data: playerBSearchData } = useQuery({
    queryKey: ['players-search-b', playerBQuery],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players/search', { q: playerBQuery }),
    enabled: playerBQuery.trim().length >= 1 && form.player_b_id === '',
  })
  const playerBCandidates = playerBSearchData?.data ?? []

  const { data: partnerASearchData } = useQuery({
    queryKey: ['players-search-partner-a', partnerAQuery],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players/search', { q: partnerAQuery }),
    enabled: partnerAQuery.trim().length >= 1 && form.partner_a_id === '',
  })
  const partnerACandidates = partnerASearchData?.data ?? []

  const { data: partnerBSearchData } = useQuery({
    queryKey: ['players-search-partner-b', partnerBQuery],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players/search', { q: partnerBQuery }),
    enabled: partnerBQuery.trim().length >= 1 && form.partner_b_id === '',
  })
  const partnerBCandidates = partnerBSearchData?.data ?? []

  // チーム候補（各側の検索結果からチーム名を抽出）
  const playerATeamSuggestions = [
    ...new Set(
      [...playerACandidates, ...partnerACandidates].map((p) => p.team).filter(Boolean) as string[]
    ),
  ]
  const playerBTeamSuggestions = [
    ...new Set(
      [...playerBCandidates, ...partnerBCandidates].map((p) => p.team).filter(Boolean) as string[]
    ),
  ]

  // 試合作成
  const createMatch = useMutation({
    mutationFn: (body: any) => apiPost('/matches', body),
    onSuccess: (data: any) => {
      const newMatchId = data?.data?.id ?? data?.data?.match?.id
      if (newMatchId) {
        localStorage.setItem(`shuttlescope.viewpoint.${newMatchId}`, analystSide)
      }
      queryClient.invalidateQueries({ queryKey: ['matches'] })
      setShowForm(false)
      setEditingMatchId(null)
      setForm(defaultForm())
      setAnalystSide('bottom')
      resetPlayerFields()
    },
  })

  // 試合更新
  const updateMatch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) => apiPut(`/matches/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['matches'] })
      setShowForm(false)
      setEditingMatchId(null)
      setForm(defaultForm())
      setAnalystSide('bottom')
      resetPlayerFields()
    },
    onError: (err: any) => {
      let detail = ''
      try {
        const parsed = JSON.parse(err.message)
        if (Array.isArray(parsed?.detail)) {
          detail = parsed.detail.map((d: any) => `${d.loc?.join('.')}: ${d.msg}`).join('\n')
        } else {
          detail = parsed?.detail ?? err.message ?? ''
        }
      } catch { detail = err.message ?? '' }
      alert(`保存に失敗しました (HTTP ${err.status ?? '?'}):\n${detail || '不明なエラー'}`)
    },
  })

  // 試合削除
  const deleteMatch = useMutation({
    mutationFn: (id: number) =>
      apiDelete(`/matches/${id}`, { 'X-Idempotency-Key': newIdempotencyKey() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['matches'] }),
    onError: (err: any) => {
      let detail = ''
      try { detail = JSON.parse(err.message)?.detail ?? '' } catch { detail = err.message ?? '' }
      alert(`削除に失敗しました (HTTP ${err.status ?? '?'}):\n${detail || '不明なエラー'}`)
    },
  })

  // 動画ダウンロード開始
  const startDownload = useMutation({
    mutationFn: ({ matchId, quality, cookieBrowser }: { matchId: number; quality: string; cookieBrowser: string }) =>
      apiPost(`/matches/${matchId}/download`, { quality, cookie_browser: cookieBrowser }),
    onSuccess: (data: any, { matchId }) => {
      if (data?.data?.job_id) {
        setDownloadJobIds((prev) => ({ ...prev, [matchId]: data.data.job_id }))
      }
    },
  })

  // 選手の暫定作成ヘルパー
  const createProvisionalPlayer = async (
    name: string,
    opts: { isTarget?: boolean; team?: string } = {}
  ): Promise<number> => {
    const resp: any = await apiPost('/players', {
      name,
      team: opts.team || undefined,
      is_target: opts.isTarget ?? false,
      profile_status: 'provisional',
      needs_review: true,
    })
    const id = resp?.data?.id
    if (!id) throw new Error('IDが取得できませんでした')
    return id
  }

  // 編集開始: フォームを既存試合データで初期化
  const handleStartEdit = (m: Match) => {
    setForm({
      tournament: m.tournament,
      tournament_level: m.tournament_level,
      round: m.round,
      date: m.date,
      format: m.format,
      player_a_id: m.player_a_id,
      player_b_id: m.player_b_id,
      partner_a_id: m.partner_a_id ?? '',
      partner_b_id: m.partner_b_id ?? '',
      initial_server: (m.initial_server as 'player_a' | 'player_b' | '') ?? '',
      result: m.result,
      final_score: m.final_score ?? '',
      video_url: m.video_url ?? '',
      // Phase 1: API レスポンスから video_local_path は除去された。
      // 空のまま編集を開始 → 動画変更なしなら PUT に含まれず DB の値は保持される。
      // 既存ファイル名は m.video_filename / m.has_video_local で表示する。
      video_local_path: '',
      notes: m.notes ?? '',
    })
    // 編集中の試合の既存動画ファイル名（パスは含まない、表示専用）
    setEditingVideoFilename(m.video_filename ?? (m.has_video_local ? '(動画登録済み)' : ''))
    setPlayerAQuery(m.player_a?.name ?? '')
    setPlayerBQuery(m.player_b?.name ?? '')
    setPlayerATeam(m.player_a?.team ?? '')
    setPlayerBTeam(m.player_b?.team ?? '')
    setPartnerAQuery(m.partner_a?.name ?? '')
    setPartnerBQuery(m.partner_b?.name ?? '')
    setEditingMatchId(m.id)
    setShowForm(true)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    const aTeam = playerATeam.trim()
    const bTeam = playerBTeam.trim()

    // ── player_a（必須）──
    let finalPlayerAId = form.player_a_id
    if (!finalPlayerAId) {
      const name = playerAQuery.trim()
      if (!name) { alert('対象選手（A）を入力または選択してください'); return }
      try {
        finalPlayerAId = await createProvisionalPlayer(name, { isTarget: true, team: aTeam || undefined })
      } catch (err: any) {
        alert(`対象選手登録エラー: ${err?.message ?? '不明なエラー'}`); return
      }
    }

    // ── player_b（必須）──
    let finalPlayerBId = form.player_b_id
    if (!finalPlayerBId) {
      const name = playerBQuery.trim()
      if (!name) { alert('対戦相手（B）を入力または選択してください'); return }
      try {
        finalPlayerBId = await createProvisionalPlayer(name, { team: bTeam || undefined })
      } catch (err: any) {
        alert(`対戦相手登録エラー: ${err?.message ?? '不明なエラー'}`); return
      }
    }

    // ── partner_a（任意）──
    let finalPartnerAId: number | undefined = form.partner_a_id ? Number(form.partner_a_id) : undefined
    if (!finalPartnerAId && partnerAQuery.trim()) {
      try {
        finalPartnerAId = await createProvisionalPlayer(partnerAQuery.trim(), { team: aTeam || undefined })
      } catch (err: any) {
        alert(`自チーム相方登録エラー: ${err?.message ?? '不明なエラー'}`); return
      }
    }

    // ── partner_b（任意）──
    let finalPartnerBId: number | undefined = form.partner_b_id ? Number(form.partner_b_id) : undefined
    if (!finalPartnerBId && partnerBQuery.trim()) {
      try {
        finalPartnerBId = await createProvisionalPlayer(partnerBQuery.trim(), { team: bTeam || undefined })
      } catch (err: any) {
        alert(`相手チーム相方登録エラー: ${err?.message ?? '不明なエラー'}`); return
      }
    }

    // undefinedキーはJSON.stringifyで除去される。空文字も数値フィールドには送らない
    const body: Record<string, any> = {
      tournament: form.tournament,
      tournament_level: form.tournament_level,
      round: form.round,
      date: form.date,
      format: form.format,
      result: form.result,
      player_a_id: Number(finalPlayerAId),
      player_b_id: Number(finalPlayerBId),
    }
    if (finalPartnerAId) body.partner_a_id = finalPartnerAId
    if (finalPartnerBId) body.partner_b_id = finalPartnerBId
    if (form.initial_server) body.initial_server = form.initial_server
    if (form.final_score) body.final_score = form.final_score
    if (form.video_url) body.video_url = form.video_url
    if (form.video_local_path) body.video_local_path = form.video_local_path
    if (form.notes) body.notes = form.notes
    // Phase B-13: 公開プール（admin 限定）。サーバ側でも admin 以外の指定は無視される
    if (form.is_public_pool) body.is_public_pool = true

    if (editingMatchId !== null) {
      console.log('[updateMatch] body:', JSON.stringify(body, null, 2))
      updateMatch.mutate({ id: editingMatchId, body })
    } else {
      createMatch.mutate(body)
    }
  }

  // ローカルファイル選択（Electron IPC）
  const handlePickVideoFile = async () => {
    if (!window.shuttlescope?.openVideoFile) return
    const fileUrl = await window.shuttlescope.openVideoFile()
    if (!fileUrl) return
    setForm((f) => ({ ...f, video_local_path: fileUrl, video_url: '' }))
  }

  const allMatches = matchesData?.data ?? []
  const players = playersData?.data ?? []

  // 期間フィルター + テキスト部分検索 + クライアントサイドソート
  const matches = useMemo(() => {
    const q = filterText.trim().toLowerCase()
    const filtered = allMatches.filter((m) => {
      if (filterDateFrom && m.date < filterDateFrom) return false
      if (filterDateTo && m.date > filterDateTo) return false
      if (q) {
        const haystack = [
          m.tournament,
          m.round,
          m.venue ?? '',
          m.notes ?? '',
          m.player_a?.name ?? '',
          m.player_b?.name ?? '',
          m.partner_a?.name ?? '',
          m.partner_b?.name ?? '',
          m.player_a?.team ?? '',
          m.player_b?.team ?? '',
        ].join(' ').toLowerCase()
        if (!haystack.includes(q)) return false
      }
      return true
    })
    return [...filtered].sort((a, b) => {
      let cmp = 0
      if (matchSortKey === 'date') {
        cmp = a.date.localeCompare(b.date)
      } else if (matchSortKey === 'tournament') {
        cmp = a.tournament.localeCompare(b.tournament, 'ja')
      } else if (matchSortKey === 'result') {
        // win > draw > loss の順
        const order: Record<string, number> = { win: 0, draw: 1, loss: 2 }
        cmp = (order[a.result as string] ?? 3) - (order[b.result as string] ?? 3)
      } else if (matchSortKey === 'status') {
        if (statusSortTarget) {
          // 選択ステータスを先頭に、それ以外はデフォルト順
          const statusOrder: Record<string, number> = { pending: 0, in_progress: 1, complete: 2, reviewed: 3 }
          const aScore = a.annotation_status === statusSortTarget ? -1 : (statusOrder[a.annotation_status] ?? 0)
          const bScore = b.annotation_status === statusSortTarget ? -1 : (statusOrder[b.annotation_status] ?? 0)
          cmp = aScore - bScore
        } else {
          const statusOrder: Record<string, number> = { pending: 0, in_progress: 1, complete: 2, reviewed: 3 }
          cmp = (statusOrder[a.annotation_status] ?? 0) - (statusOrder[b.annotation_status] ?? 0)
        }
      }
      return matchSortDir === 'asc' ? cmp : -cmp
    })
  }, [allMatches, filterDateFrom, filterDateTo, filterText, matchSortKey, matchSortDir, statusSortTarget])

  function handleMatchSort(key: MatchSortKey) {
    if (matchSortKey === key) {
      setMatchSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setMatchSortKey(key)
      setMatchSortDir(key === 'date' ? 'desc' : 'asc')
    }
  }

  // 日付プリセット
  function applyDatePreset(preset: 'week' | 'month' | 'month3') {
    const today = new Date()
    const to = today.toISOString().split('T')[0]
    const d = new Date(today)
    if (preset === 'week') d.setDate(d.getDate() - 7)
    else if (preset === 'month') d.setMonth(d.getMonth() - 1)
    else d.setMonth(d.getMonth() - 3)
    setFilterDateFrom(d.toISOString().split('T')[0])
    setFilterDateTo(to)
  }

  // 一括選択トグル
  function toggleSelectMatch(id: number) {
    setSelectedMatchIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }
  function toggleSelectAll() {
    if (selectedMatchIds.size === matches.length) {
      setSelectedMatchIds(new Set())
    } else {
      setSelectedMatchIds(new Set(matches.map((m) => m.id)))
    }
  }

  // 選手セレクター用オプション
  const playerOptions: SearchableOption[] = players.map((p) => ({
    value: String(p.id),
    label: p.name,
    searchText: p.team ?? '',
    prefix: p.is_target ? '★' : undefined,
    suffix: p.team ? `（${p.team}）` : undefined,
  }))

  const statusColor = (status: string) => {
    switch (status) {
      case 'complete': return 'text-green-400'
      case 'in_progress': return 'text-yellow-400'
      case 'reviewed': return 'text-blue-400'
      default: return 'text-gray-400'
    }
  }

  // Esc で試合フォームを閉じる
  useEffect(() => {
    if (!showForm) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setShowForm(false); setEditingMatchId(null) }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [showForm])

  const isDoubles = form.format !== 'singles'
  const showATeamField = playerAQuery.trim().length >= 1 || partnerAQuery.trim().length >= 1
  const showBTeamField = playerBQuery.trim().length >= 1 || partnerBQuery.trim().length >= 1

  return (
    <div className={`flex flex-col h-full ${bodyBg} ${isLight ? 'text-gray-900' : 'text-white'}`}>
      {/* ヘッダー */}
      <div className={`flex items-center justify-between px-6 py-4 border-b ${borderLine}`}>
        <h1 className={`text-xl font-semibold ${textHeading}`}>{t('nav.matches')}</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowQuickStart(true)}
            className="flex items-center gap-2 px-4 py-2 bg-yellow-600 hover:bg-yellow-500 text-white font-semibold rounded text-sm"
          >
            {t('quick_start.button')}
          </button>
          <button
            onClick={() => { setEditingMatchId(null); setForm(defaultForm()); resetPlayerFields(); setShowForm(true) }}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm"
          >
            <Plus size={16} />
            試合登録
          </button>
        </div>
      </div>

      {/* フィルター（モバイルではスクロール内へ移動するため hidden md:flex） */}
      <div className={`hidden md:flex flex-col gap-2 px-6 py-3 border-b ${borderLine} text-sm ${isLight ? 'bg-gray-100' : 'bg-gray-800'}`}>
        {/* テキスト部分検索 */}
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <input
            type="text"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder={t('auto.MatchListPage.k13')}
            className={`w-full pl-8 pr-8 py-1.5 rounded border text-sm ${
              isLight
                ? 'bg-white border-gray-300 text-gray-800 placeholder-gray-400'
                : 'bg-gray-700 border-gray-600 text-gray-100 placeholder-gray-500'
            }`}
          />
          {filterText && (
            <button
              onClick={() => setFilterText('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-300"
            >
              ✕
            </button>
          )}
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <Filter size={14} className="text-gray-400 shrink-0" />
          <SearchableSelect
            options={playerOptions}
            value={filterPlayer || null}
            onChange={(v) => setFilterPlayer(v != null ? String(v) : '')}
            emptyLabel="全選手"
            placeholder={t('auto.MatchListPage.k14')}
            className="min-w-[200px]"
          />
          <select
            value={filterLevel}
            onChange={(e) => setFilterLevel(e.target.value)}
            className={`${isLight ? 'bg-white border-gray-300' : 'bg-gray-800 border-gray-700'} border rounded px-2 py-1.5 text-sm`}
          >
            <option value="">{t('match.list.level_all')}</option>
            {['IC', 'IS', 'SJL', '全日本', '国内', 'その他'].map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
          <label className="flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={filterIncompleteOnly}
              onChange={(e) => setFilterIncompleteOnly(e.target.checked)}
            />
            <span className={textSecondary}>{t('match.list.only_unfinished')}</span>
          </label>
          <div className={`ml-auto flex items-center gap-2 text-sm ${textMuted}`}>
            <Download size={13} />
            <span>{t('match.list.quality')}</span>
            <select
              value={downloadQuality}
              onChange={(e) => setDownloadQuality(e.target.value)}
              className={`${isLight ? 'bg-white border-gray-300' : 'bg-gray-700 border-gray-600'} border rounded px-2 py-1 text-sm`}
            >
              <option value="360">360p</option>
              <option value="480">480p</option>
              <option value="720">{t('match.list.quality_720')}</option>
              <option value="1080">1080p</option>
              <option value="best">{t('match.list.quality_best')}</option>
            </select>
            <select
              value={downloadCookieBrowser}
              onChange={(e) => setDownloadCookieBrowser(e.target.value)}
              className={`${isLight ? 'bg-white border-gray-300' : 'bg-gray-700 border-gray-600'} border rounded px-2 py-1 text-sm`}
              title={t('auto.MatchListPage.k4')}
            >
              <option value="">{t('match.list.cookie_none')}</option>
              <option value="chrome">Chrome</option>
              <option value="edge">Edge</option>
              <option value="firefox">Firefox</option>
              <option value="brave">Brave</option>
              <option value="opera">Opera</option>
              <option value="vivaldi">Vivaldi</option>
              <option value="chromium">Chromium</option>
            </select>
          </div>
        </div>
        {/* 期間フィルター */}
        <div className="flex items-center gap-3 flex-wrap">
          <DateRangeFilter
            from={filterDateFrom ?? ''}
            to={filterDateTo ?? ''}
            onChange={(from, to) => { setFilterDateFrom(from || null); setFilterDateTo(to || null) }}
          />
          <DateRangeSlider
            from={filterDateFrom}
            to={filterDateTo}
            densityDates={allMatches.map((m) => m.date).filter(Boolean) as string[]}
            onChange={(from, to) => { setFilterDateFrom(from); setFilterDateTo(to) }}
            isLight={isLight}
          />
          {/* 日付プリセット */}
          {(['week', 'month', 'month3'] as const).map((p) => (
            <button
              key={p}
              onClick={() => applyDatePreset(p)}
              className={`text-xs px-2 py-0.5 rounded border ${
                isLight
                  ? 'border-gray-300 text-gray-600 hover:bg-gray-200'
                  : 'border-gray-600 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {p === 'week' ? '直近1週' : p === 'month' ? '直近1ヶ月' : '直近3ヶ月'}
            </button>
          ))}
          {(filterDateFrom || filterDateTo) && (
            <button
              className="text-xs text-blue-400 hover:text-blue-300"
              onClick={() => { setFilterDateFrom(null); setFilterDateTo(null) }}
            >
              リセット
            </button>
          )}
        </div>
      </div>

      {/* 一括選択バー（選択時のみ表示） */}
      {selectedMatchIds.size > 0 && (
        <div className="flex items-center gap-3 px-6 py-2 bg-blue-600 text-white text-sm shrink-0">
          <span className="font-medium">{selectedMatchIds.size}件選択中</span>
          <button
            onClick={() => {
              const ids = [...selectedMatchIds].join(',')
              window.open(`/api/sync/export/match?match_ids=${encodeURIComponent(ids)}`, '_blank')
            }}
            className="flex items-center gap-1.5 px-3 py-1 bg-white/20 hover:bg-white/30 rounded text-sm"
          >
            <Download size={13} />
            エクスポート
          </button>
          <button
            onClick={() => setSelectedMatchIds(new Set())}
            className="ml-auto text-white/70 hover:text-white text-xs"
          >
            選択解除
          </button>
        </div>
      )}

      {/* 試合一覧 */}
      <div className="flex-1 overflow-y-auto px-3 md:px-6 py-4">
        {/* モバイル用フィルター（スクロールで上に消える） */}
        <div className={`md:hidden flex flex-col gap-2 -mx-3 px-3 py-3 mb-3 border-b ${borderLine} text-sm ${isLight ? 'bg-gray-100' : 'bg-gray-800'}`}>
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            <input
              type="text"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              placeholder={t('auto.MatchListPage.k13')}
              className={`w-full pl-8 pr-8 py-1.5 rounded border text-sm ${
                isLight
                  ? 'bg-white border-gray-300 text-gray-800 placeholder-gray-400'
                  : 'bg-gray-700 border-gray-600 text-gray-100 placeholder-gray-500'
              }`}
            />
            {filterText && (
              <button
                onClick={() => setFilterText('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-300"
              >
                ✕
              </button>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Filter size={14} className="text-gray-400 shrink-0" />
            <SearchableSelect
              options={playerOptions}
              value={filterPlayer || null}
              onChange={(v) => setFilterPlayer(v != null ? String(v) : '')}
              emptyLabel="全選手"
              placeholder={t('auto.MatchListPage.k14')}
              className="min-w-[160px]"
            />
            <select
              value={filterLevel}
              onChange={(e) => setFilterLevel(e.target.value)}
              className={`${isLight ? 'bg-white border-gray-300' : 'bg-gray-800 border-gray-700'} border rounded px-2 py-1.5 text-sm`}
            >
              <option value="">{t('match.list.level_all')}</option>
              {['IC', 'IS', 'SJL', '全日本', '国内', 'その他'].map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
            <label className="flex items-center gap-1 cursor-pointer">
              <input
                type="checkbox"
                checked={filterIncompleteOnly}
                onChange={(e) => setFilterIncompleteOnly(e.target.checked)}
              />
              <span className={textSecondary}>{t('match.list.only_unfinished')}</span>
            </label>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <DateRangeFilter
              from={filterDateFrom ?? ''}
              to={filterDateTo ?? ''}
              onChange={(from, to) => { setFilterDateFrom(from || null); setFilterDateTo(to || null) }}
            />
            {(['week', 'month', 'month3'] as const).map((p) => (
              <button
                key={p}
                onClick={() => applyDatePreset(p)}
                className={`text-xs px-2 py-0.5 rounded border ${
                  isLight
                    ? 'border-gray-300 text-gray-600 hover:bg-gray-200'
                    : 'border-gray-600 text-gray-400 hover:bg-gray-700'
                }`}
              >
                {p === 'week' ? '直近1週' : p === 'month' ? '直近1ヶ月' : '直近3ヶ月'}
              </button>
            ))}
            {(filterDateFrom || filterDateTo) && (
              <button
                className="text-xs text-blue-400 hover:text-blue-300"
                onClick={() => { setFilterDateFrom(null); setFilterDateTo(null) }}
              >
                リセット
              </button>
            )}
          </div>
        </div>
        {isLoading ? (
          <div className={`text-center ${textMuted} py-8`}>{t('app.loading')}</div>
        ) : matches.length === 0 ? (
          <div className={`text-center ${textMuted} py-8`}>
            試合が登録されていません。「試合登録」ボタンで追加してください。
          </div>
        ) : (
          <>
            {/* ── モバイル: カードリスト ────────────────────────────── */}
            <div className="md:hidden space-y-2">
              {matches.map((m) => (
                <div
                  key={m.id}
                  className={`rounded-lg border px-3 py-2 ${
                    isLight ? 'bg-white border-gray-100 shadow-sm' : 'bg-gray-800 border-gray-700'
                  }`}
                >
                  {/* 1行目: 日付 + レベル + 大会名 + 結果 */}
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={`text-xs ${textMuted} shrink-0`}>{m.date}</span>
                    <span className={`text-[10px] px-1.5 py-0 rounded-full shrink-0 ${isLight ? 'bg-gray-100 text-gray-600' : 'bg-gray-700 text-gray-300'}`}>
                      {m.tournament_level}
                    </span>
                    <span className="font-medium text-sm truncate flex-1">{m.tournament}</span>
                    <span className={clsx(
                      'text-xs font-bold shrink-0',
                      m.result === 'win' ? 'text-green-400' : m.result === 'loss' ? 'text-red-400' : 'text-gray-400'
                    )}>
                      {t(`match.results.${m.result}`)}
                    </span>
                  </div>

                  {/* 2行目: 対戦情報 */}
                  <div className="flex items-center gap-1 mb-1 text-sm">
                    <span className={`text-[10px] ${textMuted} shrink-0`}>{t(`match.formats.${m.format}`)}</span>
                    <span className={`${textSecondary} truncate`}>
                      vs {m.player_b?.name ?? `#${m.player_b_id}`}
                      {m.partner_b?.name && ` / ${m.partner_b.name}`}
                    </span>
                    {m.player_b?.needs_review && (
                      <span className="text-[10px] text-yellow-400 bg-yellow-400/10 px-1 rounded shrink-0">{t('match.list.tentative')}</span>
                    )}
                    {m.final_score && (
                      <span className={`text-xs ${textMuted} ml-auto shrink-0`}>{m.final_score}</span>
                    )}
                  </div>

                  {/* 3行目: 進捗 + 操作ボタン */}
                  <div className="flex items-center gap-2">
                    {m.annotation_status !== 'complete' ? (
                      <div className="flex items-center gap-1.5 flex-1 min-w-0">
                        <div className={`h-1 flex-1 ${isLight ? 'bg-gray-100' : 'bg-gray-700'} rounded-full overflow-hidden`}>
                          <div
                            className="h-full bg-blue-500 rounded-full transition-all"
                            style={{ width: `${m.annotation_progress * 100}%` }}
                          />
                        </div>
                        <span className={clsx('text-[10px] shrink-0', statusColor(m.annotation_status))}>
                          {t(`match.statuses.${m.annotation_status}`)}
                        </span>
                        {/* INFRA Phase B: 解析ジョブ状態バッジ */}
                        <PipelineJobBadge matchId={m.id} className="shrink-0" />
                      </div>
                    ) : (
                      <span className={clsx('text-[10px] flex-1', statusColor(m.annotation_status))}>
                        {t(`match.statuses.${m.annotation_status}`)}
                      </span>
                    )}
                    <button
                      onClick={() => navigate(`/annotator/${m.id}`)}
                      className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-medium shrink-0"
                    >
                      <Play size={12} />
                      開く
                    </button>
                    {m.player_a_id && (
                      <button
                        onClick={() => navigate(`/prediction?playerId=${m.player_a_id}`)}
                        className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-blue-600 hover:bg-blue-50' : 'text-gray-400 hover:text-blue-400 hover:bg-gray-700'}`}
                        title={t('auto.MatchListPage.k5')}
                      >
                        <TrendingUp size={16} />
                      </button>
                    )}
                    {/* 動画 DL バッジ: 進行中なら percent + eta、error なら赤バッジ + 再試行 */}
                    {dlByMatch[String(m.id)] && dlByMatch[String(m.id)].status === 'error' && (
                      <button
                        type="button"
                        onClick={() => startDownload.mutate({ matchId: m.id, quality: downloadQuality, cookieBrowser: downloadCookieBrowser })}
                        className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded ${
                          isLight ? 'bg-red-100 text-red-700 hover:bg-red-200' : 'bg-red-900/40 text-red-300 hover:bg-red-900/60'
                        }`}
                        title={`DL 失敗: ${dlByMatch[String(m.id)].error ?? ''}\nクリックで再試行`}
                        disabled={startDownload.isPending}
                      >
                        <AlertCircle size={12} />
                        失敗・再試行
                      </button>
                    )}
                    {dlByMatch[String(m.id)] && dlByMatch[String(m.id)].status !== 'error' && (
                      <span
                        className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded ${
                          isLight ? 'bg-blue-100 text-blue-700' : 'bg-blue-900/40 text-blue-300'
                        }`}
                        title={`DL中 ${dlByMatch[String(m.id)].percent ?? ''} (残り ${dlByMatch[String(m.id)].eta ?? '?'})`}
                      >
                        <Download size={12} className="animate-pulse" />
                        {dlByMatch[String(m.id)].percent ?? 'DL中'}
                      </span>
                    )}
                    {m.video_url && !m.has_video_local && !dlByMatch[String(m.id)] && (
                      <button
                        onClick={() => startDownload.mutate({ matchId: m.id, quality: downloadQuality, cookieBrowser: downloadCookieBrowser })}
                        className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'}`}
                        title={t('auto.MatchListPage.k6')}
                        disabled={startDownload.isPending}
                      >
                        <Download size={16} />
                      </button>
                    )}
                    <a
                      href={`/api/export/package?match_id=${m.id}`}
                      download
                      title={t('auto.MatchListPage.k7')}
                      className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-green-600 hover:bg-green-50' : 'text-gray-400 hover:text-green-400 hover:bg-gray-700'}`}
                    >
                      <Download size={16} />
                    </a>
                    <button
                      onClick={() => handleStartEdit(m)}
                      className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'}`}
                      title={t('auto.MatchListPage.k8')}
                    >
                      <Pencil size={16} />
                    </button>
                    {deleteConfirmMatchId === m.id ? (
                      <div className={`flex items-center gap-1 px-1.5 py-0.5 rounded border border-white text-[10px] ${isLight ? 'bg-red-50 text-red-700' : 'bg-red-900/30 text-red-400'}`}>
                        <button
                          onClick={() => { deleteMatch.mutate(m.id); setDeleteConfirmMatchId(null) }}
                          className="font-medium hover:opacity-80"
                        >
                          削除
                        </button>
                        <span className="opacity-50">|</span>
                        <button onClick={() => setDeleteConfirmMatchId(null)} className="hover:opacity-80">
                          取消
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeleteConfirmMatchId(m.id)}
                        className="p-1 rounded text-red-400 hover:text-red-300 hover:bg-red-900/20"
                        title={t('auto.MatchListPage.k9')}
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* ── デスクトップ: テーブル ─────────────────────────────── */}
            <table className="hidden md:table w-full text-sm">
              <thead>
                <tr className={`${textSecondary} border-b ${borderLine}`}>
                  {/* 一括選択チェックボックス */}
                  <th className="py-2 pr-2 w-6">
                    <input
                      type="checkbox"
                      checked={matches.length > 0 && selectedMatchIds.size === matches.length}
                      onChange={toggleSelectAll}
                      className="accent-blue-500"
                      title={t('auto.MatchListPage.k10')}
                    />
                  </th>
                  {/* ソート可能: 日付 */}
                  <th
                    className="text-left py-2 pr-4 cursor-pointer select-none hover:opacity-80 whitespace-nowrap"
                    onClick={() => handleMatchSort('date')}
                  >
                    <span className="inline-flex items-center gap-0.5">
                      日付
                      {matchSortKey === 'date'
                        ? matchSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                        : <ChevronsUpDown size={12} className="opacity-30" />}
                    </span>
                  </th>
                  {/* ソート可能: 大会名 */}
                  <th
                    className="text-left py-2 pr-4 cursor-pointer select-none hover:opacity-80 whitespace-nowrap"
                    onClick={() => handleMatchSort('tournament')}
                  >
                    <span className="inline-flex items-center gap-0.5">
                      大会名
                      {matchSortKey === 'tournament'
                        ? matchSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                        : <ChevronsUpDown size={12} className="opacity-30" />}
                    </span>
                  </th>
                  <th className="text-left py-2 pr-4">{t('match.list.col_level')}</th>
                  <th className="text-left py-2 pr-4">{t('match.list.col_format')}</th>
                  <th className="text-left py-2 pr-4">{t('match.list.col_opponent')}</th>
                  {/* ソート可能: 結果 */}
                  <th
                    className="text-left py-2 pr-4 cursor-pointer select-none hover:opacity-80 whitespace-nowrap"
                    onClick={() => handleMatchSort('result')}
                  >
                    <span className="inline-flex items-center gap-0.5">
                      結果
                      {matchSortKey === 'result'
                        ? matchSortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                        : <ChevronsUpDown size={12} className="opacity-30" />}
                    </span>
                  </th>
                  <th className="text-left py-2 pr-4 whitespace-nowrap">
                    <div className="relative inline-block" ref={statusDropdownRef}>
                      <button
                        className="inline-flex items-center gap-0.5 cursor-pointer select-none hover:opacity-80"
                        onClick={() => {
                          setMatchSortKey('status')
                          setShowStatusDropdown((v) => !v)
                        }}
                      >
                        進捗
                        {statusSortTarget ? (
                          <span className="text-blue-400 text-[9px] ml-0.5 font-bold">●</span>
                        ) : (
                          <ChevronDown size={12} className="opacity-30" />
                        )}
                      </button>
                      {showStatusDropdown && (
                        <div className={`absolute top-full left-0 mt-1 z-50 rounded shadow-lg border min-w-[90px] text-xs py-0.5 ${
                          isLight ? 'bg-white border-gray-200 text-gray-800' : 'bg-gray-900 border-gray-700 text-gray-100'
                        }`}>
                          {([
                            { key: 'pending',    label: t('auto.MatchListPage.k20') },
                            { key: 'in_progress', label: t('auto.MatchListPage.k21') },
                            { key: 'complete',   label: t('auto.MatchListPage.k22') },
                          ] as const).map(({ key, label }) => (
                            <button
                              key={key}
                              className={`w-full text-left px-3 py-1.5 flex items-center gap-1.5 ${
                                statusSortTarget === key
                                  ? isLight ? 'bg-blue-50 font-semibold text-blue-700' : 'bg-blue-900/30 font-semibold text-blue-300'
                                  : isLight ? 'hover:bg-gray-100' : 'hover:bg-gray-800'
                              }`}
                              onClick={() => {
                                setStatusSortTarget(statusSortTarget === key ? null : key)
                                setShowStatusDropdown(false)
                              }}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </th>
                  <th className="text-left py-2">{t('match.list.col_actions')}</th>
                </tr>
              </thead>
              <tbody>
                {matches.map((m) => (
                  <tr key={m.id} className={`border-b ${isLight ? 'border-gray-100 hover:bg-gray-50' : 'border-gray-800 hover:bg-gray-800/50'}`}>
                    <td className="py-2 pr-2">
                      <input
                        type="checkbox"
                        checked={selectedMatchIds.has(m.id)}
                        onChange={() => toggleSelectMatch(m.id)}
                        className="accent-blue-500"
                      />
                    </td>
                    <td className={`py-2 pr-4 ${textSecondary}`}>{m.date}</td>
                    <td className="py-2 pr-4">{m.tournament}</td>
                    <td className="py-2 pr-4">
                      <span className={`px-1.5 py-0.5 rounded text-xs ${isLight ? 'bg-gray-200 text-gray-700' : 'bg-gray-700'}`}>{m.tournament_level}</span>
                      {m.is_public_pool && (
                        <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-400" title="全チームから閲覧可能な公開プール試合">
                          共有
                        </span>
                      )}
                      {m.owner_team_display_id && (
                        <span className={`ml-1 text-[10px] ${textSecondary}`} title={`登録チーム: ${m.owner_team_display_name ?? ''}`}>
                          [{m.owner_team_display_id}]
                        </span>
                      )}
                    </td>
                    <td className={`py-2 pr-4 ${textSecondary}`}>{t(`match.formats.${m.format}`)}</td>
                    <td className="py-2 pr-4">
                      <span className="text-sm">
                        {m.player_b?.name ?? `#${m.player_b_id}`}
                        {m.partner_b?.name && ` / ${m.partner_b.name}`}
                      </span>
                      {m.player_b?.needs_review && (
                        <span className="ml-1 text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded" title={t('player.profile_status_provisional')}>
                          暫定
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      <span className={clsx(
                        'font-medium',
                        m.result === 'win' ? 'text-green-400' : m.result === 'loss' ? 'text-red-400' : 'text-gray-400'
                      )}>
                        {t(`match.results.${m.result}`)}
                      </span>
                      {m.final_score && <span className={`${textMuted} ml-1 text-xs`}>{m.final_score}</span>}
                    </td>
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <div className={`w-20 h-1.5 ${isLight ? 'bg-gray-200' : 'bg-gray-700'} rounded-full overflow-hidden`}>
                          <div
                            className="h-full bg-blue-500"
                            style={{ width: `${m.annotation_progress * 100}%` }}
                          />
                        </div>
                        <span className={clsx('text-xs', statusColor(m.annotation_status))}>
                          {t(`match.statuses.${m.annotation_status}`)}
                        </span>
                        {/* INFRA Phase B: 解析ジョブ状態バッジ */}
                        <PipelineJobBadge matchId={m.id} />
                      </div>
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => navigate(`/annotator/${m.id}`)}
                          className="p-1.5 rounded bg-blue-700 hover:bg-blue-600 text-white"
                          title={t('match.start_annotation')}
                        >
                          <Play size={14} />
                        </button>
                        {m.player_a_id && (
                          <button
                            onClick={() => navigate(`/prediction?playerId=${m.player_a_id}`)}
                            className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
                            title={t('auto.MatchListPage.k5')}
                          >
                            <TrendingUp size={14} />
                          </button>
                        )}
                        {/* 動画 DL バッジ: 進行中なら percent を表示 */}
                        {dlByMatch[String(m.id)] && (
                          <span
                            className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded ${
                              isLight ? 'bg-blue-100 text-blue-700' : 'bg-blue-900/40 text-blue-300'
                            }`}
                            title={`DL中 ${dlByMatch[String(m.id)].percent ?? ''} (残り ${dlByMatch[String(m.id)].eta ?? '?'})`}
                          >
                            <Download size={12} className="animate-pulse" />
                            {dlByMatch[String(m.id)].percent ?? 'DL中'}
                          </span>
                        )}
                        {m.video_url && !m.has_video_local && !dlByMatch[String(m.id)] && (
                          <button
                            onClick={() => startDownload.mutate({
                              matchId: m.id,
                              quality: downloadQuality,
                              cookieBrowser: downloadCookieBrowser,
                            })}
                            className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
                            title={`動画ダウンロード (${downloadQuality}p${downloadCookieBrowser ? ` / Cookie: ${downloadCookieBrowser}` : ''})`}
                            disabled={startDownload.isPending}
                          >
                            <Download size={14} />
                          </button>
                        )}
                        <button
                          onClick={() => handleStartEdit(m)}
                          className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
                          title={t('auto.MatchListPage.k11')}
                        >
                          <Pencil size={14} />
                        </button>
                        {deleteConfirmMatchId === m.id ? (
                          <div className={`flex items-center gap-1 px-2 py-1 rounded border border-white text-xs ${isLight ? 'bg-red-50 text-red-700' : 'bg-red-900/30 text-red-400'}`}>
                            <button
                              onClick={() => { deleteMatch.mutate(m.id); setDeleteConfirmMatchId(null) }}
                              className="font-medium hover:opacity-80"
                            >
                              削除
                            </button>
                            <span className="opacity-50">|</span>
                            <button onClick={() => setDeleteConfirmMatchId(null)} className="hover:opacity-80">
                              取消
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setDeleteConfirmMatchId(m.id)}
                            className="p-1.5 rounded bg-red-900/50 hover:bg-red-700 text-red-400"
                            title={t('auto.MatchListPage.k9')}
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      {/* クイックスタートモーダル */}
      {showQuickStart && (
        <QuickStartModal
          onClose={() => setShowQuickStart(false)}
          onStarted={(matchId) => {
            setShowQuickStart(false)
            queryClient.invalidateQueries({ queryKey: ['matches'] })
            navigate(`/annotator/${matchId}?matchDayMode=true&quickStart=true`)
          }}
        />
      )}

      {/* 試合登録モーダル */}
      {showForm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className={`${card} rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto`}>
            <div className={`flex items-center justify-between px-6 py-4 border-b ${borderLine}`}>
              <h2 className={`text-lg font-semibold ${textHeading}`}>{editingMatchId !== null ? '試合編集' : '試合登録'}</h2>
              <button onClick={() => { setShowForm(false); setEditingMatchId(null); setForm(defaultForm()); resetPlayerFields() }} className={`${textMuted} ${isLight ? 'hover:text-gray-900' : 'hover:text-white'}`}>✕</button>
            </div>
            <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-4">
                {/* 大会名 */}
                <div className="col-span-2">
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.tournament')} *</label>
                  <input
                    value={form.tournament}
                    onChange={(e) => setForm({ ...form, tournament: e.target.value })}
                    required
                    className={`w-full ${inputClass}`}
                    placeholder={t('auto.MatchListPage.k15')}
                  />
                </div>

                {/* レベル / ラウンド */}
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.tournament_level')}</label>
                  <select
                    value={form.tournament_level}
                    onChange={(e) => setForm({ ...form, tournament_level: e.target.value as TournamentLevel })}
                    className={`w-full ${inputClass}`}
                  >
                    {['IC', 'IS', 'SJL', '全日本', '国内', 'その他'].map((l) => (
                      <option key={l} value={l}>{l}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.round')}</label>
                  <select
                    value={form.round}
                    onChange={(e) => setForm({ ...form, round: e.target.value })}
                    className={`w-full ${inputClass}`}
                  >
                    {MATCH_ROUNDS.map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </div>

                {/* 日付 / 形式 */}
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.date')} *</label>
                  <input
                    type="date"
                    value={form.date}
                    onChange={(e) => setForm({ ...form, date: e.target.value })}
                    required
                    className={`w-full ${inputClass}`}
                  />
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.format')}</label>
                  <select
                    value={form.format}
                    onChange={(e) => setForm({ ...form, format: e.target.value as MatchFormat })}
                    className={`w-full ${inputClass}`}
                  >
                    <option value="singles">{t('match.list.format_singles')}</option>
                    <option value="mens_doubles">{t('match.list.format_mens_doubles')}</option>
                    <option value="womens_doubles">{t('match.list.format_womens_doubles')}</option>
                    <option value="mixed_doubles">{t('match.list.format_mixed_doubles')}</option>
                  </select>
                </div>

                {/* 選手欄: 自チーム（左） / 相手チーム（右） */}
                <PlayerCombobox
                  label="対象選手（A）"
                  required
                  value={form.player_a_id}
                  query={playerAQuery}
                  setQuery={setPlayerAQuery}
                  setValue={(v) => setForm((f) => ({ ...f, player_a_id: v }))}
                  candidates={playerACandidates}
                  isLight={isLight}
                  textSecondary={textSecondary}
                  placeholder={t('auto.MatchListPage.k16')}
                />
                <PlayerCombobox
                  label="対戦相手（B）"
                  required
                  value={form.player_b_id}
                  query={playerBQuery}
                  setQuery={setPlayerBQuery}
                  setValue={(v) => setForm((f) => ({ ...f, player_b_id: v }))}
                  candidates={playerBCandidates}
                  isLight={isLight}
                  textSecondary={textSecondary}
                  placeholder={t('auto.MatchListPage.k16')}
                />

                {/* ダブルス: 相方欄（自チーム左・相手チーム右） */}
                {isDoubles && (
                  <>
                    <PlayerCombobox
                      label="自チーム相方"
                      value={form.partner_a_id}
                      query={partnerAQuery}
                      setQuery={setPartnerAQuery}
                      setValue={(v) => setForm((f) => ({ ...f, partner_a_id: v }))}
                      candidates={partnerACandidates}
                      isLight={isLight}
                      textSecondary={textSecondary}
                      placeholder={t('auto.MatchListPage.k16')}
                    />
                    <PlayerCombobox
                      label="相手チーム相方"
                      value={form.partner_b_id}
                      query={partnerBQuery}
                      setQuery={setPartnerBQuery}
                      setValue={(v) => setForm((f) => ({ ...f, partner_b_id: v }))}
                      candidates={partnerBCandidates}
                      isLight={isLight}
                      textSecondary={textSecondary}
                      placeholder={t('auto.MatchListPage.k16')}
                    />
                  </>
                )}

                {/* 自チーム名（A側の名前が入力されたら表示） */}
                {showATeamField && (
                  <div>
                    <label className={`block text-sm ${textSecondary} mb-1`}>
                      自チーム名
                      <span className={`ml-1 ${textFaint} text-xs`}>{t('auto.MatchListPage.k2')}</span>
                    </label>
                    <input
                      list="player-a-teams-list"
                      value={playerATeam}
                      onChange={(e) => setPlayerATeam(e.target.value)}
                      placeholder={t('auto.MatchListPage.k17')}
                      className={`w-full ${inputClass}`}
                      autoComplete="off"
                    />
                    <datalist id="player-a-teams-list">
                      {playerATeamSuggestions.map((team) => (
                        <option key={team} value={team} />
                      ))}
                    </datalist>
                    {(form.player_a_id !== '' || form.partner_a_id !== '') && playerATeam && (
                      <p className="text-[11px] text-blue-400 mt-0.5">{t('auto.MatchListPage.k3')}</p>
                    )}
                  </div>
                )}

                {/* 相手チーム名（B側の名前が入力されたら表示） */}
                {showBTeamField && (
                  <div>
                    <label className={`block text-sm ${textSecondary} mb-1`}>
                      相手チーム名
                      <span className={`ml-1 ${textFaint} text-xs`}>{t('auto.MatchListPage.k2')}</span>
                    </label>
                    <input
                      list="player-b-teams-list"
                      value={playerBTeam}
                      onChange={(e) => setPlayerBTeam(e.target.value)}
                      placeholder={t('auto.MatchListPage.k17')}
                      className={`w-full ${inputClass}`}
                      autoComplete="off"
                    />
                    <datalist id="player-b-teams-list">
                      {playerBTeamSuggestions.map((team) => (
                        <option key={team} value={team} />
                      ))}
                    </datalist>
                    {(form.player_b_id !== '' || form.partner_b_id !== '') && playerBTeam && (
                      <p className="text-[11px] text-blue-400 mt-0.5">{t('auto.MatchListPage.k3')}</p>
                    )}
                  </div>
                )}

                {/* 結果 / スコア */}
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.result')}</label>
                  <select
                    value={form.result}
                    onChange={(e) => setForm({ ...form, result: e.target.value as MatchResult })}
                    className={`w-full ${inputClass}`}
                  >
                    <option value="win">{t('match.list.result_win')}</option>
                    <option value="loss">{t('match.list.result_loss')}</option>
                    <option value="walkover">{t('match.list.result_walkover')}</option>
                    <option value="unfinished">{t('match.list.result_unfinished')}</option>
                  </select>
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.score')}</label>
                  <input
                    value={form.final_score}
                    onChange={(e) => setForm({ ...form, final_score: e.target.value })}
                    className={`w-full ${inputClass}`}
                    placeholder={t('auto.MatchListPage.k18')}
                  />
                </div>

                {/* 動画 */}
                <div className="col-span-2">
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.list.video_optional')}</label>
                  <div className="flex gap-2 items-center">
                    {typeof window.shuttlescope?.openVideoFile === 'function' && (
                      <button
                        type="button"
                        onClick={handlePickVideoFile}
                        className={`flex items-center gap-1 px-2 py-2 ${isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-700 border-gray-300' : 'bg-gray-700 hover:bg-gray-600 text-gray-200 border-gray-600'} rounded text-xs whitespace-nowrap border`}
                      >
                        <FolderOpen size={13} />
                        ファイルを選択
                      </button>
                    )}
                    <input
                      value={form.video_local_path ? form.video_local_path.split(/[/\\]/).pop() ?? '' : form.video_url}
                      onChange={(e) => setForm((f) => ({ ...f, video_url: e.target.value, video_local_path: '' }))}
                      readOnly={!!form.video_local_path}
                      className={`flex-1 ${inputClass} min-w-0`}
                      placeholder={t('auto.MatchListPage.k19')}
                    />
                    {form.video_local_path && (
                      <button
                        type="button"
                        onClick={() => setForm((f) => ({ ...f, video_local_path: '' }))}
                        className={`${textMuted} ${isLight ? 'hover:text-gray-900' : 'hover:text-white'} text-xs px-1`}
                        title={t('auto.MatchListPage.k12')}
                      >✕</button>
                    )}
                  </div>
                  {/* 編集中: 新規選択ファイル名 or 既存ファイル名（パスは露出しない） */}
                  {(form.video_local_path || editingVideoFilename) && (
                    <div className={`text-[10px] ${textMuted} mt-0.5 truncate`}>
                      📁 {form.video_local_path
                        ? form.video_local_path.split(/[/\\]/).pop()
                        : editingVideoFilename}
                    </div>
                  )}
                  {/* DL 進捗表示 (編集中の試合に進行中 / error ジョブがあれば) */}
                  {editingMatchId != null && dlByMatch[String(editingMatchId)] && (() => {
                    const dl = dlByMatch[String(editingMatchId)]
                    const isErr = dl.status === 'error'
                    const pctNum = Math.max(0, Math.min(100, parseFloat(dl.percent ?? '0') || 0))
                    if (isErr) {
                      return (
                        <div
                          className={`mt-2 p-2.5 rounded border ${
                            isLight ? 'border-red-200 bg-red-50' : 'border-red-800 bg-red-900/20'
                          }`}
                        >
                          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
                            <div className={`flex items-start gap-1.5 text-xs flex-1 min-w-0 ${isLight ? 'text-red-700' : 'text-red-300'}`}>
                              <AlertCircle size={14} className="shrink-0 mt-0.5" />
                              <div className="min-w-0">
                                <div className="font-medium">ダウンロード失敗</div>
                                {dl.error && (
                                  <div className={`text-[11px] mt-0.5 break-words ${textMuted}`}>{dl.error}</div>
                                )}
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => editingMatchId != null && startDownload.mutate({ matchId: editingMatchId, quality: downloadQuality, cookieBrowser: downloadCookieBrowser })}
                              disabled={startDownload.isPending}
                              className={`shrink-0 inline-flex items-center justify-center gap-1 px-3 py-1.5 rounded text-xs font-medium ${
                                isLight
                                  ? 'bg-red-600 hover:bg-red-700 text-white disabled:bg-red-400'
                                  : 'bg-red-700 hover:bg-red-600 text-white disabled:bg-red-900'
                              }`}
                            >
                              <Download size={12} />
                              再試行
                            </button>
                          </div>
                        </div>
                      )
                    }
                    return (
                      <div
                        className={`mt-2 p-2.5 rounded border ${
                          isLight ? 'border-blue-200 bg-blue-50' : 'border-blue-800 bg-blue-900/20'
                        }`}
                      >
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 text-xs mb-1.5">
                          <span className={`flex items-center gap-1.5 font-medium ${isLight ? 'text-blue-700' : 'text-blue-300'}`}>
                            <Download size={13} className="animate-pulse shrink-0" />
                            <span className="truncate">
                              {dl.status === 'queued' && '待機中…'}
                              {dl.status === 'pending' && '準備中…'}
                              {dl.status === 'downloading' && `ダウンロード中 ${dl.percent ?? ''}`}
                              {dl.status === 'processing' && '変換中…'}
                              {dl.status === 'starting' && '開始中…'}
                            </span>
                          </span>
                          <span className={`flex items-center gap-2 ${textMuted} text-[11px] flex-wrap`}>
                            {dl.speed && <span className="whitespace-nowrap">{dl.speed}</span>}
                            {dl.eta && dl.status === 'downloading' && (
                              <span className="whitespace-nowrap">残り {dl.eta}</span>
                            )}
                          </span>
                        </div>
                        <div className={`h-2 rounded-full overflow-hidden ${isLight ? 'bg-blue-200/60' : 'bg-blue-950'}`}>
                          <div
                            className={`h-full transition-all duration-300 ${
                              dl.status === 'downloading'
                                ? (isLight ? 'bg-blue-500' : 'bg-blue-400')
                                : (isLight ? 'bg-blue-300 animate-pulse' : 'bg-blue-700 animate-pulse')
                            }`}
                            style={dl.status === 'downloading'
                              ? { width: `${pctNum}%` }
                              : { width: dl.status === 'processing' ? '100%' : '15%' }}
                          />
                        </div>
                      </div>
                    )
                  })()}
                  {/* 動画リンク再発行（漏洩時の即時無効化用） */}
                  {editingMatchId != null && editingVideoFilename && (
                    <div className="mt-2 flex flex-col sm:flex-row sm:items-center gap-2">
                      <button
                        type="button"
                        onClick={async () => {
                          if (!window.confirm(t('match.list.reissue_video_token_confirm'))) return
                          try {
                            // Phase B2: 二度押し / 通信再送による二重発行を防ぐ
                            const idemKey = newIdempotencyKey()
                            await apiPost<{ success: boolean; data: { video_token: string } }>(
                              `/matches/${editingMatchId}/reissue_video_token`, {},
                              { 'X-Idempotency-Key': idemKey },
                            )
                            queryClient.invalidateQueries({ queryKey: ['matches'] })
                            alert(t('match.list.reissue_video_token_done'))
                          } catch (err: any) {
                            alert(t('match.list.reissue_video_token_failed') + ': ' + (err?.message ?? String(err)))
                          }
                        }}
                        className={`text-xs px-3 py-1.5 rounded border ${
                          isLight
                            ? 'border-amber-300 text-amber-700 hover:bg-amber-50'
                            : 'border-amber-700 text-amber-300 hover:bg-amber-900/20'
                        }`}
                        title={t('match.list.reissue_video_token_hint')}
                      >
                        🔄 {t('match.list.reissue_video_token')}
                      </button>
                      <span className={`text-[10px] ${textMuted}`}>
                        {t('match.list.reissue_video_token_hint_short')}
                      </span>
                    </div>
                  )}
                </div>

                {/* 先サーブ / アナリスト視点 */}
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.list.first_serve')}</label>
                  <div className="flex gap-2">
                    {([
                      { value: 'player_a', label: t('auto.MatchListPage.k23') },
                      { value: 'player_b', label: t('auto.MatchListPage.k24') },
                    ] as const).map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setForm((f) => ({ ...f, initial_server: f.initial_server === opt.value ? '' : opt.value }))}
                        className={`flex-1 py-1.5 rounded text-sm border ${
                          form.initial_server === opt.value
                            ? 'bg-blue-600 border-blue-500 text-white'
                            : isLight
                              ? 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                              : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.list.analyst_view')}</label>
                  <div className="flex gap-2">
                    {([
                      { value: 'bottom' as const, label: t('auto.MatchListPage.k25') },
                      { value: 'top'    as const, label: t('auto.MatchListPage.k26') },
                    ]).map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setAnalystSide(opt.value)}
                        className={`flex-1 py-1.5 rounded text-sm border ${
                          analystSide === opt.value
                            ? 'bg-blue-600 border-blue-500 text-white'
                            : isLight
                              ? 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                              : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* メモ */}
                <div className="col-span-2">
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.notes')}</label>
                  <textarea
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                    rows={2}
                    className={`w-full ${inputClass}`}
                  />
                </div>

                {/* Phase B-13: 公開プール（admin 限定）— 全チーム閲覧可能 */}
                {role === 'admin' && (
                  <div className="col-span-2">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={form.is_public_pool}
                        onChange={(e) => setForm({ ...form, is_public_pool: e.target.checked })}
                      />
                      <span>全チーム共有（公開プール: BWF などの公開試合用。チェックすると全チームから閲覧可）</span>
                    </label>
                  </div>
                )}
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={createMatch.isPending || updateMatch.isPending}
                  className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium disabled:opacity-50"
                >
                  {editingMatchId !== null
                    ? (updateMatch.isPending ? '保存中...' : '保存')
                    : (createMatch.isPending ? '登録中...' : '登録')}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowForm(false); setEditingMatchId(null); setForm(defaultForm()); resetPlayerFields() }}
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
