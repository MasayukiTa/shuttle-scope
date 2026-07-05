import { useState, useRef, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiPut, apiDelete, newIdempotencyKey } from '@/api/client'
import { Match, Player, TournamentLevel, MatchFormat, MatchResult, MATCH_ROUNDS } from '@/types'
import { QuickStartModal } from '@/components/annotation/QuickStartModal'
import { SearchableSelect, SearchableOption } from '@/components/common/SearchableSelect'
import { DateRangeFilter } from '@/components/common/DateRangeFilter'
import { errorMessage, errorStatus } from '@/utils/errors'
import { DateRangeSlider } from '@/components/common/DateRangeSlider'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useAuth } from '@/hooks/useAuth'
import { DownloadOptionsModal } from '@/components/video/DownloadOptionsModal'
import { PlayerCombobox } from '@/components/matchList/PlayerCombobox'
import { MatchCard } from '@/components/matchList/MatchCard'
import { MatchRow } from '@/components/matchList/MatchRow'
import { MIcon } from '@/components/common/MIcon'

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

// ─────────────────────────────────────────────────────────────────────────────

export function MatchListPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { card, textHeading, textSecondary, textMuted, textFaint, isLight } = useCardTheme()
  const { role, playerId, teamName } = useAuth()

  const bodyBg = 'bg-[var(--ss-bg-app)]'
  const borderLine = 'border-[var(--ss-border)]'
  const inputClass = 'bg-[var(--ss-surface-1)] border border-[var(--ss-border-strong)] rounded-[var(--r-md)] px-3 py-2 text-sm text-[var(--ss-t1)]'

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
  const [_downloadJobIds, setDownloadJobIds] = useState<Record<number, string>>({})
  const [downloadQuality, setDownloadQuality] = useState<string>('720')
  const [downloadCookieBrowser, setDownloadCookieBrowser] = useState<string>('')
  // DL オプションモーダル (2026-05-08): 全部DL / 範囲指定 / 手入力 を選べる。
  // null なら閉じている。Match を渡すと開く。
  const [downloadModalMatch, setDownloadModalMatch] = useState<Match | null>(null)

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
    mutationFn: (body: Record<string, unknown>) => apiPost('/matches', body),
    onSuccess: (data: unknown) => {
      const d = data as { data?: { id?: number; match?: { id?: number } } } | null
      const newMatchId = d?.data?.id ?? d?.data?.match?.id
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
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => apiPut(`/matches/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['matches'] })
      setShowForm(false)
      setEditingMatchId(null)
      setForm(defaultForm())
      setAnalystSide('bottom')
      resetPlayerFields()
    },
    onError: (err: unknown) => {
      const msg = errorMessage(err)
      let detail: string
      try {
        const parsed = JSON.parse(msg) as { detail?: unknown }
        if (Array.isArray(parsed?.detail)) {
          detail = (parsed.detail as Array<{ loc?: string[]; msg?: string }>)
            .map((d) => `${d.loc?.join('.')}: ${d.msg}`).join('\n')
        } else {
          detail = (typeof parsed?.detail === 'string' ? parsed.detail : msg) || ''
        }
      } catch { detail = msg }
      alert(`保存に失敗しました (HTTP ${errorStatus(err) ?? '?'}):\n${detail || '不明なエラー'}`)
    },
  })

  // 試合削除
  const deleteMatch = useMutation({
    mutationFn: (id: number) =>
      apiDelete(`/matches/${id}`, { 'X-Idempotency-Key': newIdempotencyKey() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['matches'] }),
    onError: (err: unknown) => {
      const msg = errorMessage(err)
      let detail: string
      try {
        const parsed = JSON.parse(msg) as { detail?: unknown }
        detail = typeof parsed?.detail === 'string' ? parsed.detail : ''
      } catch { detail = msg }
      alert(`削除に失敗しました (HTTP ${errorStatus(err) ?? '?'}):\n${detail || '不明なエラー'}`)
    },
  })

  // 動画ダウンロード開始
  const _startDownload = useMutation({
    mutationFn: ({ matchId, quality, cookieBrowser }: { matchId: number; quality: string; cookieBrowser: string }) =>
      apiPost(`/matches/${matchId}/download`, { quality, cookie_browser: cookieBrowser }),
    onSuccess: (data: unknown, { matchId }) => {
      const d = data as { data?: { job_id?: string } } | null
      if (d?.data?.job_id) {
        setDownloadJobIds((prev) => ({ ...prev, [matchId]: d.data!.job_id! }))
      }
    },
  })

  // 選手の暫定作成ヘルパー
  const createProvisionalPlayer = async (
    name: string,
    opts: { isTarget?: boolean; team?: string } = {}
  ): Promise<number> => {
    const resp = await apiPost<{ data?: { id?: number } }>('/players', {
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
      } catch (err: unknown) {
        alert(`対象選手登録エラー: ${errorMessage(err, '不明なエラー')}`); return
      }
    }

    // ── player_b（必須）──
    let finalPlayerBId = form.player_b_id
    if (!finalPlayerBId) {
      const name = playerBQuery.trim()
      if (!name) { alert('対戦相手（B）を入力または選択してください'); return }
      try {
        finalPlayerBId = await createProvisionalPlayer(name, { team: bTeam || undefined })
      } catch (err: unknown) {
        alert(`対戦相手登録エラー: ${errorMessage(err, '不明なエラー')}`); return
      }
    }

    // ── partner_a（任意）──
    let finalPartnerAId: number | undefined = form.partner_a_id ? Number(form.partner_a_id) : undefined
    if (!finalPartnerAId && partnerAQuery.trim()) {
      try {
        finalPartnerAId = await createProvisionalPlayer(partnerAQuery.trim(), { team: aTeam || undefined })
      } catch (err: unknown) {
        alert(`自チーム相方登録エラー: ${errorMessage(err, '不明なエラー')}`); return
      }
    }

    // ── partner_b（任意）──
    let finalPartnerBId: number | undefined = form.partner_b_id ? Number(form.partner_b_id) : undefined
    if (!finalPartnerBId && partnerBQuery.trim()) {
      try {
        finalPartnerBId = await createProvisionalPlayer(partnerBQuery.trim(), { team: bTeam || undefined })
      } catch (err: unknown) {
        alert(`相手チーム相方登録エラー: ${errorMessage(err, '不明なエラー')}`); return
      }
    }

    // undefinedキーはJSON.stringifyで除去される。空文字も数値フィールドには送らない
    const body: Record<string, unknown> = {
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

  // 配信 URL からタイトルを自動取得して大会名に反映（多言語対応）
  const [fetchingTitle, setFetchingTitle] = useState(false)
  const handleFetchTitle = async () => {
    const url = form.video_url.trim()
    if (!/^https?:\/\//i.test(url)) return
    setFetchingTitle(true)
    try {
      const r = await apiPost<{ success: boolean; data: { title?: string | null } }>(
        '/matches/probe-url',
        { url },
      )
      const title = (r.data?.title ?? '').trim()
      if (title) {
        // 明示クリックなので大会名へ反映（既存入力があっても上書き）
        setForm((f) => ({ ...f, tournament: title }))
      } else {
        alert(t('match.list.fetch_title_empty'))
      }
    } catch (err) {
      alert(t('match.list.fetch_title_failed') + ': ' + errorMessage(err, ''))
    } finally {
      setFetchingTitle(false)
    }
  }

  const allMatches = useMemo(() => matchesData?.data ?? [], [matchesData?.data])
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
      if (next.has(id)) next.delete(id); else next.add(id)
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
    prefix: p.is_target ? 'star' : undefined,
                prefixIsIcon: !!p.is_target,
    suffix: p.team ? `（${p.team}）` : undefined,
  }))

  // statusColor は @/components/matchList/matchListUtils に共通化済み (import)

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
    // h-full + overflow-y-auto: 親 (MainLayout) は overflow-hidden で高さ固定なので、
    // 狭い viewport (横向きスマホ ~390px tall) では header + filter で枠を使い切り、
    // 内部の list が高さ 0 になって "試合一覧が出ない" 事象が起きる。
    // 内側の flex-1 overflow-y-auto に頼らず、ページ全体を 1 つの scroll container
    // にすることで、filter を含めて自然にスクロール出来るようにする。
    // ※ 並んで sticky にすべき要素 (header) があれば後で position:sticky で対処。
    <div className={`h-full overflow-y-auto flex flex-col ${bodyBg} text-[var(--ss-t1)]`}>
      {/* ヘッダー */}
      <div className={`flex items-center justify-between gap-2 flex-wrap px-6 py-4 border-b ${borderLine}`}>
        <h1 className={`text-xl font-semibold ${textHeading}`}>{t('nav.matches')}</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setShowQuickStart(true)}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--ss-warn)] hover:opacity-90 text-white font-semibold rounded-[var(--r-md)] text-sm"
          >
            {t('quick_start.button')}
          </button>
          <button
            onClick={() => { setEditingMatchId(null); setForm(defaultForm()); resetPlayerFields(); setShowForm(true) }}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white rounded-[var(--r-md)] text-sm"
          >
            <MIcon name="add" size={16} />
            {t('auto.MatchListPage.k29')}
          </button>
        </div>
      </div>

      {/* フィルター（モバイルではスクロール内へ移動するため hidden md:flex） */}
      <div className={`hidden md:flex flex-col gap-2 px-6 py-3 border-b ${borderLine} text-sm bg-[var(--ss-surface-2)]`}>
        {/* テキスト部分検索 */}
        <div className="relative">
          <MIcon name="search" size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--ss-t3)] pointer-events-none" />
          <input
            type="text"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder={t('auto.MatchListPage.k13')}
            className="w-full pl-8 pr-8 py-1.5 rounded-[var(--r-md)] border border-[var(--ss-border-strong)] text-sm bg-[var(--ss-surface-1)] text-[var(--ss-t1)] placeholder-[var(--ss-t3)]"
          />
          {filterText && (
            <button
              onClick={() => setFilterText('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--ss-t3)] hover:text-[var(--ss-t1)]"
            >
              <MIcon name="close" size={12} />
            </button>
          )}
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <MIcon name="filter_alt" size={14} className="text-[var(--ss-t3)] shrink-0" />
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
            className="border rounded-[var(--r-md)] px-2 py-1.5 text-sm bg-[var(--ss-surface-1)] border-[var(--ss-border-strong)] text-[var(--ss-t1)]"
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
            <MIcon name="download" size={13} />
            <span>{t('match.list.quality')}</span>
            <select
              value={downloadQuality}
              onChange={(e) => setDownloadQuality(e.target.value)}
              className="border rounded-[var(--r-md)] px-2 py-1 text-sm bg-[var(--ss-surface-1)] border-[var(--ss-border-strong)] text-[var(--ss-t1)]"
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
              className="border rounded-[var(--r-md)] px-2 py-1 text-sm bg-[var(--ss-surface-1)] border-[var(--ss-border-strong)] text-[var(--ss-t1)]"
              title={t('auto.MatchListPage.k4')}
            >
              <option value="">{t('match.list.cookie_none')}</option>
              <option value="chrome">Chrome</option>
              <option value="edge">Edge</option>
              <option value="firefox">Firefox</option>
              <option value="brave">Brave</option>
              <option value="opera">Opera</option>
              <option value="vivaldi">{t('auto.MatchListPage.k61')}</option>
              <option value="chromium">{t('auto.MatchListPage.k62')}</option>
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
              className="text-xs px-2 py-0.5 rounded-[var(--r-md)] border border-[var(--ss-border)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]"
            >
              {p === 'week' ? t('auto.MatchListPage.k30') : p === 'month' ? t('auto.MatchListPage.k31') : t('auto.MatchListPage.k32')}
            </button>
          ))}
          {(filterDateFrom || filterDateTo) && (
            <button
              className="text-xs text-[var(--ss-brand)] hover:text-[var(--ss-brand-hover)]"
              onClick={() => { setFilterDateFrom(null); setFilterDateTo(null) }}
            >
              {t('auto.MatchListPage.k33')}
            </button>
          )}
        </div>
      </div>

      {/* 一括選択バー（選択時のみ表示） */}
      {selectedMatchIds.size > 0 && (
        <div className="flex items-center gap-3 flex-wrap gap-y-2 px-6 py-2 bg-[var(--ss-brand)] text-white text-sm shrink-0">
          <span className="font-medium">{t('auto.MatchListPage.k34', { n: selectedMatchIds.size })}</span>
          <button
            onClick={() => {
              const ids = [...selectedMatchIds].join(',')
              // R258 R6 P2 fix: noopener,noreferrer 統一
              window.open(`/api/sync/export/match?match_ids=${encodeURIComponent(ids)}`, '_blank', 'noopener,noreferrer')
            }}
            className="flex items-center gap-1.5 px-3 py-1 bg-white/20 hover:bg-white/30 rounded-[var(--r-md)] text-sm"
          >
            <MIcon name="download" size={13} />
            {t('auto.MatchListPage.k35')}
          </button>
          <button
            onClick={() => setSelectedMatchIds(new Set())}
            className="ml-auto text-white/70 hover:text-white text-xs"
          >
            {t('auto.MatchListPage.k36')}
          </button>
        </div>
      )}

      {/* 試合一覧
         NOTE: flex-1 overflow-y-auto はやめ、外側の scroll に委ねる (height < 500px
         の landscape phone で内側 scroll が高さ 0 になり list 行が見えない問題対策)。 */}
      <div className="px-3 md:px-6 py-4">
        {/* モバイル用フィルター（スクロールで上に消える） */}
        <div className={`md:hidden flex flex-col gap-2 -mx-3 px-3 py-3 mb-3 border-b ${borderLine} text-sm bg-[var(--ss-surface-2)]`}>
          <div className="relative">
            <MIcon name="search" size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--ss-t3)] pointer-events-none" />
            <input
              type="text"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              placeholder={t('auto.MatchListPage.k13')}
              className="w-full pl-8 pr-8 py-1.5 rounded-[var(--r-md)] border border-[var(--ss-border-strong)] text-sm bg-[var(--ss-surface-1)] text-[var(--ss-t1)] placeholder-[var(--ss-t3)]"
            />
            {filterText && (
              <button
                onClick={() => setFilterText('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--ss-t3)] hover:text-[var(--ss-t1)]"
              >
                <MIcon name="close" size={12} />
              </button>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <MIcon name="filter_alt" size={14} className="text-[var(--ss-t3)] shrink-0" />
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
              className="border rounded-[var(--r-md)] px-2 py-1.5 text-sm bg-[var(--ss-surface-1)] border-[var(--ss-border-strong)] text-[var(--ss-t1)]"
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
                className="text-xs px-2 py-0.5 rounded-[var(--r-md)] border border-[var(--ss-border)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]"
              >
                {p === 'week' ? t('auto.MatchListPage.k30') : p === 'month' ? t('auto.MatchListPage.k31') : t('auto.MatchListPage.k32')}
              </button>
            ))}
            {(filterDateFrom || filterDateTo) && (
              <button
                className="text-xs text-[var(--ss-brand)] hover:text-[var(--ss-brand-hover)]"
                onClick={() => { setFilterDateFrom(null); setFilterDateTo(null) }}
              >
                {t('auto.MatchListPage.k33')}
              </button>
            )}
          </div>
        </div>
        {isLoading ? (
          <div className={`text-center ${textMuted} py-8`}>{t('app.loading')}</div>
        ) : matches.length === 0 ? (
          <div className={`text-center ${textMuted} py-10`}>
            <p className="mb-4">{t('auto.MatchListPage.k37')}</p>
            <button
              onClick={() => navigate('/getting-started')}
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white rounded-[var(--r-md)] text-sm"
            >
              <MIcon name="menu_book" size={16} />
              {t('getting_started.title')}
            </button>
          </div>
        ) : (
          <>
            {/* ── モバイル: カードリスト ────────────────────────────── */}
            <div className="md:hidden space-y-2">
              {matches.map((m) => (
                <MatchCard
                  key={m.id}
                  match={m}
                  dl={dlByMatch[String(m.id)]}
                  onDownload={setDownloadModalMatch}
                  onEdit={handleStartEdit}
                  deleteConfirmId={deleteConfirmMatchId}
                  onDeleteConfirm={setDeleteConfirmMatchId}
                  onDeleteExecute={(id) => deleteMatch.mutate(id)}
                />
              ))}
            </div>

            {/* ── デスクトップ: テーブル ─────────────────────────────── */}
            <table className="hidden md:table w-full text-sm">
              <thead>
                <tr className={`${textSecondary} border-b ${borderLine} bg-[var(--ss-surface-2)]`}>
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
                      {t('auto.MatchListPage.k38')}
                      {matchSortKey === 'date'
                        ? matchSortDir === 'asc' ? <MIcon name="expand_less" size={12} /> : <MIcon name="expand_more" size={12} />
                        : <MIcon name="unfold_more" size={12} className="opacity-30" />}
                    </span>
                  </th>
                  {/* ソート可能: 大会名 */}
                  <th
                    className="text-left py-2 pr-4 cursor-pointer select-none hover:opacity-80 whitespace-nowrap"
                    onClick={() => handleMatchSort('tournament')}
                  >
                    <span className="inline-flex items-center gap-0.5">
                      {t('auto.MatchListPage.k39')}
                      {matchSortKey === 'tournament'
                        ? matchSortDir === 'asc' ? <MIcon name="expand_less" size={12} /> : <MIcon name="expand_more" size={12} />
                        : <MIcon name="unfold_more" size={12} className="opacity-30" />}
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
                      {t('auto.MatchListPage.k40')}
                      {matchSortKey === 'result'
                        ? matchSortDir === 'asc' ? <MIcon name="expand_less" size={12} /> : <MIcon name="expand_more" size={12} />
                        : <MIcon name="unfold_more" size={12} className="opacity-30" />}
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
                        {t('auto.MatchListPage.k41')}
                        {statusSortTarget ? (
                          <span className="text-blue-400 text-[9px] ml-0.5 font-bold">{t('auto.MatchListPage.k63')}</span>
                        ) : (
                          <MIcon name="expand_more" size={12} className="opacity-30" />
                        )}
                      </button>
                      {showStatusDropdown && (
                        <div className="absolute top-full left-0 mt-1 z-50 rounded-[var(--r-md)] shadow-lg border border-[var(--ss-border)] min-w-[90px] text-xs py-0.5 bg-[var(--ss-surface-1)]">
                          {([
                            { key: 'pending',    label: t('auto.MatchListPage.k20') },
                            { key: 'in_progress', label: t('auto.MatchListPage.k21') },
                            { key: 'complete',   label: t('auto.MatchListPage.k22') },
                          ] as const).map(({ key, label }) => (
                            <button
                              key={key}
                              className={`w-full text-left px-3 py-1.5 flex items-center gap-1.5 ${
                                statusSortTarget === key
                                  ? 'bg-[var(--ss-brand-tint)] font-semibold text-[var(--ss-brand)]'
                                  : 'hover:bg-[var(--ss-surface-2)]'
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
                  <MatchRow
                    key={m.id}
                    match={m}
                    selected={selectedMatchIds.has(m.id)}
                    onToggleSelect={toggleSelectMatch}
                    dl={dlByMatch[String(m.id)]}
                    onDownload={setDownloadModalMatch}
                    onEdit={handleStartEdit}
                    deleteConfirmId={deleteConfirmMatchId}
                    onDeleteConfirm={setDeleteConfirmMatchId}
                    onDeleteExecute={(id) => deleteMatch.mutate(id)}
                  />
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
          <div className={`${card} rounded-[var(--r-lg)] w-full max-w-2xl max-h-[90dvh] overflow-y-auto`}>
            <div className={`flex items-center justify-between px-6 py-4 border-b ${borderLine}`}>
              <h2 className={`text-lg font-semibold ${textHeading}`}>{editingMatchId !== null ? t('auto.MatchListPage.k42') : t('auto.MatchListPage.k29')}</h2>
              <button onClick={() => { setShowForm(false); setEditingMatchId(null); setForm(defaultForm()); resetPlayerFields() }} className={`${textMuted} hover:text-[var(--ss-t1)]`}><MIcon name="close" size={12} /></button>
            </div>
            <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* 大会名 */}
                <div className="col-span-1 sm:col-span-2">
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
                  label={t('auto.MatchListPage.k43')}
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
                  label={t('auto.MatchListPage.k44')}
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
                      label={t('auto.MatchListPage.k45')}
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
                      label={t('auto.MatchListPage.k46')}
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
                      {t('auto.MatchListPage.k47')}
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
                      {t('auto.MatchListPage.k48')}
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
                <div className="col-span-1 sm:col-span-2">
                  <label className={`block text-sm ${textSecondary} mb-1`}>{t('match.list.video_optional')}</label>
                  <div className="flex gap-2 items-center">
                    {typeof window.shuttlescope?.openVideoFile === 'function' && (
                      <button
                        type="button"
                        onClick={handlePickVideoFile}
                        className="flex items-center gap-1 px-2 py-2 bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] text-[var(--ss-t1)] border border-[var(--ss-border)] rounded-[var(--r-md)] text-xs whitespace-nowrap"
                      >
                        <MIcon name="folder_open" size={13} />
                        {t('auto.MatchListPage.k49')}
                      </button>
                    )}
                    <input
                      value={form.video_local_path ? form.video_local_path.split(/[/\\]/).pop() ?? '' : form.video_url}
                      onChange={(e) => setForm((f) => ({ ...f, video_url: e.target.value, video_local_path: '' }))}
                      readOnly={!!form.video_local_path}
                      className={`flex-1 ${inputClass} min-w-0`}
                      placeholder={t('auto.MatchListPage.k19')}
                    />
                    {!form.video_local_path && /^https?:\/\//i.test(form.video_url.trim()) && (
                      <button
                        type="button"
                        onClick={handleFetchTitle}
                        disabled={fetchingTitle}
                        className="flex items-center gap-1 px-2 py-2 bg-[var(--ss-brand-tint)] hover:opacity-90 text-[var(--ss-brand)] border border-[var(--ss-brand)] rounded-[var(--r-md)] text-xs whitespace-nowrap disabled:opacity-50"
                        title={t('match.list.fetch_title')}
                      >
                        <MIcon name="auto_awesome" size={13} />
                        {fetchingTitle ? t('match.list.fetch_title_loading') : t('match.list.fetch_title')}
                      </button>
                    )}
                    {form.video_local_path && (
                      <button
                        type="button"
                        onClick={() => setForm((f) => ({ ...f, video_local_path: '' }))}
                        className={`${textMuted} hover:text-[var(--ss-t1)] text-xs px-1`}
                        title={t('auto.MatchListPage.k12')}
                      ><MIcon name="close" size={12} /></button>
                    )}
                  </div>
                  {/* 編集中: 新規選択ファイル名 or 既存ファイル名（パスは露出しない） */}
                  {(form.video_local_path || editingVideoFilename) && (
                    <div className={`text-[10px] ${textMuted} mt-0.5 truncate inline-flex items-center gap-1`}>
                      <MIcon name="folder" size={10} />
                      {form.video_local_path
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
                        <div className="mt-2 p-2.5 rounded-[var(--r-md)] border border-[var(--ss-danger)] bg-[var(--ss-danger-tint)]">
                          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
                            <div className="flex items-start gap-1.5 text-xs flex-1 min-w-0 text-[var(--ss-danger)]">
                              <MIcon name="error" size={14} className="shrink-0 mt-0.5" />
                              <div className="min-w-0">
                                <div className="font-medium">{t('auto.MatchListPage.k27')}</div>
                                {dl.error && (
                                  <div className={`text-[11px] mt-0.5 break-words ${textMuted}`}>{dl.error}</div>
                                )}
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => {
                                if (editingMatchId == null) return
                                const m = matches.find((x) => x.id === editingMatchId)
                                if (m) setDownloadModalMatch(m)
                              }}
                              className="shrink-0 inline-flex items-center justify-center gap-1 px-3 py-1.5 rounded-[var(--r-md)] text-xs font-medium bg-[var(--ss-danger)] hover:opacity-90 text-white"
                            >
                              <MIcon name="download" size={12} />
                              {t('auto.MatchListPage.k50')}
                            </button>
                          </div>
                        </div>
                      )
                    }
                    return (
                      <div className="mt-2 p-2.5 rounded-[var(--r-md)] border border-[var(--ss-brand)] bg-[var(--ss-brand-tint)]">
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 text-xs mb-1.5">
                          <span className="flex items-center gap-1.5 font-medium text-[var(--ss-brand)]">
                            <MIcon name="download" size={13} className="animate-pulse shrink-0" />
                            <span className="truncate">
                              {dl.status === 'queued' && t('auto.MatchListPage.k51')}
                              {dl.status === 'pending' && t('auto.MatchListPage.k52')}
                              {dl.status === 'downloading' && t('auto.MatchListPage.k53', { percent: dl.percent ?? '' })}
                              {dl.status === 'processing' && t('auto.MatchListPage.k54')}
                              {dl.status === 'starting' && t('auto.MatchListPage.k55')}
                            </span>
                          </span>
                          <span className={`flex items-center gap-2 ${textMuted} text-[11px] flex-wrap`}>
                            {dl.speed && <span className="whitespace-nowrap">{dl.speed}</span>}
                            {dl.eta && dl.status === 'downloading' && (
                              <span className="whitespace-nowrap">{t('auto.MatchListPage.k56', { eta: dl.eta })}</span>
                            )}
                          </span>
                        </div>
                        <div className="h-2 rounded-full overflow-hidden bg-[var(--ss-brand-tint)]">
                          <div
                            className="h-full transition-all duration-300 bg-[var(--ss-brand)] animate-pulse"
                            style={dl.status === 'downloading'
                              ? { width: `${pctNum}%`, animationPlayState: 'paused' }
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
                          } catch (err: unknown) {
                            alert(t('match.list.reissue_video_token_failed') + ': ' + errorMessage(err))
                          }
                        }}
                        className="text-xs px-3 py-1.5 rounded-[var(--r-md)] border border-[var(--ss-warn)] text-[var(--ss-warn)] hover:bg-[var(--ss-warn-tint)]"
                        title={t('match.list.reissue_video_token_hint')}
                      >
                        <span className="inline-flex items-center gap-1"><MIcon name="refresh" size={11} />{t('match.list.reissue_video_token')}</span>
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
                        className={`flex-1 py-1.5 rounded-[var(--r-md)] text-sm border ${
                          form.initial_server === opt.value
                            ? 'bg-[var(--ss-brand)] border-[var(--ss-brand)] text-white'
                            : 'bg-[var(--ss-surface-1)] border-[var(--ss-border)] text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)]'
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
                        className={`flex-1 py-1.5 rounded-[var(--r-md)] text-sm border ${
                          analystSide === opt.value
                            ? 'bg-[var(--ss-brand)] border-[var(--ss-brand)] text-white'
                            : 'bg-[var(--ss-surface-1)] border-[var(--ss-border)] text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)]'
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* メモ */}
                <div className="col-span-1 sm:col-span-2">
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
                  <div className="col-span-1 sm:col-span-2">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={form.is_public_pool}
                        onChange={(e) => setForm({ ...form, is_public_pool: e.target.checked })}
                      />
                      <span>{t('auto.MatchListPage.k28')}</span>
                    </label>
                  </div>
                )}
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={createMatch.isPending || updateMatch.isPending}
                  className="flex-1 py-2 bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white rounded-[var(--r-md)] text-sm font-medium disabled:opacity-50"
                >
                  {editingMatchId !== null
                    ? (updateMatch.isPending ? t('auto.MatchListPage.k57') : t('auto.MatchListPage.k58'))
                    : (createMatch.isPending ? t('auto.MatchListPage.k59') : t('auto.MatchListPage.k60'))}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowForm(false); setEditingMatchId(null); setForm(defaultForm()); resetPlayerFields() }}
                  className="flex-1 py-2 bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] text-[var(--ss-t1)] rounded-[var(--r-md)] text-sm"
                >
                  {t('app.cancel')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* DL オプションモーダル (2026-05-08): 全部 / 範囲指定 / 手入力 を選択 */}
      <DownloadOptionsModal
        open={!!downloadModalMatch}
        onClose={() => setDownloadModalMatch(null)}
        matchId={downloadModalMatch?.id ?? 0}
        matchLabel={downloadModalMatch
          ? `${downloadModalMatch.tournament ?? ''}${downloadModalMatch.tournament ? ' - ' : ''}${downloadModalMatch.date ?? ''}`
          : ''}
        videoUrl={downloadModalMatch?.video_url ?? ''}
        initialQuality={downloadQuality}
        initialCookieBrowser={downloadCookieBrowser}
        onStarted={(jobId) => {
          if (downloadModalMatch && jobId) {
            setDownloadJobIds((prev) => ({ ...prev, [downloadModalMatch.id]: jobId }))
          }
          // モーダル側で onClose 呼ぶので何もしない
        }}
      />
    </div>
  )
}
