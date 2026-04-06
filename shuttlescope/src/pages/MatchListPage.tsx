import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Play, Trash2, Download, Filter, Zap, AlertCircle } from 'lucide-react'
import { clsx } from 'clsx'
import { apiGet, apiPost, apiDelete } from '@/api/client'
import { Match, Player, TournamentLevel, MatchFormat, MatchResult, MATCH_ROUNDS } from '@/types'
import { QuickStartModal } from '@/components/annotation/QuickStartModal'

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
  result: MatchResult
  final_score: string
  video_url: string
  notes: string
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
  result: 'win',
  final_score: '',
  video_url: '',
  notes: '',
})

export function MatchListPage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [showForm, setShowForm] = useState(false)
  const [showQuickStart, setShowQuickStart] = useState(false)
  const [form, setForm] = useState<MatchFormData>(defaultForm())
  const [filterPlayer, setFilterPlayer] = useState<string>('')
  const [filterLevel, setFilterLevel] = useState<string>('')
  const [filterIncompleteOnly, setFilterIncompleteOnly] = useState(false)
  const [downloadJobIds, setDownloadJobIds] = useState<Record<number, string>>({})
  const [downloadQuality, setDownloadQuality] = useState<string>('720')
  const [downloadCookieBrowser, setDownloadCookieBrowser] = useState<string>('')

  // 試合一覧取得
  const { data: matchesData, isLoading } = useQuery({
    queryKey: ['matches', filterPlayer, filterLevel, filterIncompleteOnly],
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

  // 試合作成
  const createMatch = useMutation({
    mutationFn: (body: any) => apiPost('/matches', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['matches'] })
      setShowForm(false)
      setForm(defaultForm())
    },
  })

  // 試合削除
  const deleteMatch = useMutation({
    mutationFn: (id: number) => apiDelete(`/matches/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['matches'] }),
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.player_a_id || !form.player_b_id) {
      alert('選手を選択してください')
      return
    }
    createMatch.mutate({
      ...form,
      player_a_id: Number(form.player_a_id),
      player_b_id: Number(form.player_b_id),
      partner_a_id: form.partner_a_id ? Number(form.partner_a_id) : undefined,
      partner_b_id: form.partner_b_id ? Number(form.partner_b_id) : undefined,
    })
  }

  const matches = matchesData?.data ?? []
  const players = playersData?.data ?? []

  const statusColor = (status: string) => {
    switch (status) {
      case 'complete': return 'text-green-400'
      case 'in_progress': return 'text-yellow-400'
      case 'reviewed': return 'text-blue-400'
      default: return 'text-gray-400'
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-900 text-white">
      {/* ヘッダー */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
        <h1 className="text-xl font-semibold">{t('nav.matches')}</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowQuickStart(true)}
            className="flex items-center gap-2 px-4 py-2 bg-yellow-500 hover:bg-yellow-400 text-gray-900 font-semibold rounded text-sm"
          >
            <Zap size={15} />
            {t('quick_start.button')}
          </button>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm"
          >
            <Plus size={16} />
            試合登録
          </button>
        </div>
      </div>

      {/* フィルター */}
      <div className="flex items-center gap-4 px-6 py-3 bg-gray-800 border-b border-gray-700 text-sm">
        <Filter size={14} className="text-gray-400" />
        <select
          value={filterPlayer}
          onChange={(e) => setFilterPlayer(e.target.value)}
          className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"
        >
          <option value="">全選手</option>
          {players.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <select
          value={filterLevel}
          onChange={(e) => setFilterLevel(e.target.value)}
          className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"
        >
          <option value="">全大会レベル</option>
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
          <span className="text-gray-300">未完了のみ</span>
        </label>
        <div className="ml-auto flex items-center gap-2 text-sm text-gray-400">
          <Download size={13} />
          <span>画質:</span>
          <select
            value={downloadQuality}
            onChange={(e) => setDownloadQuality(e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"
          >
            <option value="360">360p</option>
            <option value="480">480p</option>
            <option value="720">720p (推奨)</option>
            <option value="1080">1080p</option>
            <option value="best">最高画質</option>
          </select>
          <select
            value={downloadCookieBrowser}
            onChange={(e) => setDownloadCookieBrowser(e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"
            title="ログイン必須サイトのCookieを取得するブラウザ"
          >
            <option value="">Cookie: なし</option>
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

      {/* 試合一覧テーブル */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isLoading ? (
          <div className="text-center text-gray-400 py-8">{t('app.loading')}</div>
        ) : matches.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            試合が登録されていません。「試合登録」ボタンで追加してください。
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 border-b border-gray-700">
                <th className="text-left py-2 pr-4">日付</th>
                <th className="text-left py-2 pr-4">大会名</th>
                <th className="text-left py-2 pr-4">レベル</th>
                <th className="text-left py-2 pr-4">形式</th>
                <th className="text-left py-2 pr-4">対戦相手</th>
                <th className="text-left py-2 pr-4">結果</th>
                <th className="text-left py-2 pr-4">進捗</th>
                <th className="text-left py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {matches.map((m) => (
                <tr key={m.id} className="border-b border-gray-800 hover:bg-gray-800/50">
                  <td className="py-2 pr-4 text-gray-300">{m.date}</td>
                  <td className="py-2 pr-4">{m.tournament}</td>
                  <td className="py-2 pr-4">
                    <span className="px-1.5 py-0.5 rounded bg-gray-700 text-xs">{m.tournament_level}</span>
                  </td>
                  <td className="py-2 pr-4 text-gray-300">{t(`match.formats.${m.format}`)}</td>
                  <td className="py-2 pr-4">
                    <span>{m.player_b?.name ?? `#${m.player_b_id}`}</span>
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
                    {m.final_score && <span className="text-gray-500 ml-1 text-xs">{m.final_score}</span>}
                  </td>
                  <td className="py-2 pr-4">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-blue-500"
                          style={{ width: `${m.annotation_progress * 100}%` }}
                        />
                      </div>
                      <span className={clsx('text-xs', statusColor(m.annotation_status))}>
                        {t(`match.statuses.${m.annotation_status}`)}
                      </span>
                    </div>
                  </td>
                  <td className="py-2">
                    <div className="flex items-center gap-1">
                      {/* アノテーション開始 */}
                      <button
                        onClick={() => navigate(`/annotator/${m.id}`)}
                        className="p-1.5 rounded bg-blue-700 hover:bg-blue-600 text-white"
                        title={t('match.start_annotation')}
                      >
                        <Play size={14} />
                      </button>
                      {/* 動画ダウンロード */}
                      {m.video_url && !m.video_local_path && (
                        <button
                          onClick={() => startDownload.mutate({
                            matchId: m.id,
                            quality: downloadQuality,
                            cookieBrowser: downloadCookieBrowser,
                          })}
                          className="p-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                          title={`動画ダウンロード (${downloadQuality}p${downloadCookieBrowser ? ` / Cookie: ${downloadCookieBrowser}` : ''})`}
                          disabled={startDownload.isPending}
                        >
                          <Download size={14} />
                        </button>
                      )}
                      {/* 削除 */}
                      <button
                        onClick={() => {
                          if (confirm(`試合「${m.tournament}」を削除しますか？`)) {
                            deleteMatch.mutate(m.id)
                          }
                        }}
                        className="p-1.5 rounded bg-red-900/50 hover:bg-red-700 text-red-400"
                        title="削除"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
          <div className="bg-gray-800 rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
              <h2 className="text-lg font-semibold">試合登録</h2>
              <button onClick={() => setShowForm(false)} className="text-gray-400 hover:text-white">✕</button>
            </div>
            <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="block text-sm text-gray-400 mb-1">{t('match.tournament')} *</label>
                  <input
                    value={form.tournament}
                    onChange={(e) => setForm({ ...form, tournament: e.target.value })}
                    required
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    placeholder="例: 全日本総合選手権"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('match.tournament_level')}</label>
                  <select
                    value={form.tournament_level}
                    onChange={(e) => setForm({ ...form, tournament_level: e.target.value as TournamentLevel })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  >
                    {['IC', 'IS', 'SJL', '全日本', '国内', 'その他'].map((l) => (
                      <option key={l} value={l}>{l}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('match.round')}</label>
                  <select
                    value={form.round}
                    onChange={(e) => setForm({ ...form, round: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  >
                    {MATCH_ROUNDS.map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('match.date')} *</label>
                  <input
                    type="date"
                    value={form.date}
                    onChange={(e) => setForm({ ...form, date: e.target.value })}
                    required
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('match.format')}</label>
                  <select
                    value={form.format}
                    onChange={(e) => setForm({ ...form, format: e.target.value as MatchFormat })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  >
                    <option value="singles">シングルス</option>
                    <option value="womens_doubles">女子ダブルス</option>
                    <option value="mixed_doubles">混合ダブルス</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">対象選手（A）*</label>
                  <select
                    value={form.player_a_id}
                    onChange={(e) => setForm({ ...form, player_a_id: e.target.value ? Number(e.target.value) : '' })}
                    required
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  >
                    <option value="">選択してください</option>
                    {players.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">対戦相手（B）*</label>
                  <select
                    value={form.player_b_id}
                    onChange={(e) => setForm({ ...form, player_b_id: e.target.value ? Number(e.target.value) : '' })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  >
                    <option value="">名前入力</option>
                    {players.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                {form.format !== 'singles' && (
                  <>
                    <div>
                      <label className="block text-sm text-gray-400 mb-1">自チーム相方</label>
                      <select
                        value={form.partner_a_id}
                        onChange={(e) => setForm({ ...form, partner_a_id: e.target.value ? Number(e.target.value) : '' })}
                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                      >
                        <option value="">なし</option>
                        {players.map((p) => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm text-gray-400 mb-1">相手チーム相方</label>
                      <select
                        value={form.partner_b_id}
                        onChange={(e) => setForm({ ...form, partner_b_id: e.target.value ? Number(e.target.value) : '' })}
                        className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                      >
                        <option value="">なし</option>
                        {players.map((p) => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                    </div>
                  </>
                )}
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('match.result')}</label>
                  <select
                    value={form.result}
                    onChange={(e) => setForm({ ...form, result: e.target.value as MatchResult })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  >
                    <option value="win">勝ち</option>
                    <option value="loss">負け</option>
                    <option value="walkover">不戦勝</option>
                    <option value="unfinished">未完了</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('match.score')}</label>
                  <input
                    value={form.final_score}
                    onChange={(e) => setForm({ ...form, final_score: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    placeholder="例: 21-15, 18-21, 21-19"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-sm text-gray-400 mb-1">{t('match.video_url')}</label>
                  <input
                    value={form.video_url}
                    onChange={(e) => setForm({ ...form, video_url: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    placeholder="YouTube URL（任意）"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-sm text-gray-400 mb-1">{t('match.notes')}</label>
                  <textarea
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                    rows={2}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  />
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={createMatch.isPending}
                  className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium disabled:opacity-50"
                >
                  {createMatch.isPending ? '登録中...' : '登録'}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowForm(false); setForm(defaultForm()) }}
                  className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
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
