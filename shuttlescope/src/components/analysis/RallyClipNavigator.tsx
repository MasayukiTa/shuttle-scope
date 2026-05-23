/**
 * RallyClipNavigator — ラリー動画ジャンプコンポーネント (B: 高速レビュー導線)
 *
 * タイムスタンプ付きラリー一覧を表示し、クリックで動画をその地点へジャンプさせる。
 * 動画がローカル保存されていない場合はグレーアウトする。
 */
import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Play, Clock, Filter, ChevronDown } from 'lucide-react'
import { getPlaylist, PlaylistRally } from '@/api/review'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useTranslation } from 'react-i18next'

const END_TYPE_LABELS: Record<string, string> = {
  forced_error: '強制エラー',
  unforced_error: 'ミス',
  ace: 'エース',
  net_error: 'ネット',
  out_error: 'アウト',
  other: 'その他',
}

interface Props {
  matchId: number
  /** 試合の player_a 名（スコア表示用） */
  playerAName?: string
  /** 試合の player_b 名 */
  playerBName?: string
}

function fmtTime(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export function RallyClipNavigator({ matchId, playerAName = 'A', playerBName = 'B' }: Props) {
  const { t } = useTranslation()

  const { _card, textPrimary, textMuted, textSecondary, border, rowHover, isLight } = useCardTheme()

  // フィルター状態
  const [filterWinner, setFilterWinner] = useState<string>('')
  const [filterEndType, setFilterEndType] = useState<string>('')
  const [filterSetNum, setFilterSetNum] = useState<string>('')
  const [showFilters, setShowFilters] = useState(false)

  // 動画 ref。ポップアップ内 <video> を制御するために保持。
  // 旧版は in-frame に video を埋め込んでいたが、フレームサイズ依存で
  // 全画面切替時にエラーが頻発するため、オーバーレイポップアップ方式に変更
  // (2026-05-19、YouTube ポップアップに倣う構造)。
  const videoRef = useRef<HTMLVideoElement | null>(null)
  // ポップアップ表示状態 + 開いたときに jump する rally timestamp
  const [popupRally, setPopupRally] = useState<PlaylistRally | null>(null)
  const [currentRallyId, setCurrentRallyId] = useState<number | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['review', 'playlist', matchId, filterWinner, filterEndType, filterSetNum],
    queryFn: () =>
      getPlaylist(matchId, {
        winner: filterWinner || undefined,
        end_type: filterEndType || undefined,
        set_num: filterSetNum ? Number(filterSetNum) : undefined,
      }),
    enabled: matchId > 0,
  })

  const rallies = data?.rallies ?? []
  // Phase 1: 生パス video_local_path はバックエンドが返さない。
  // 不透明トークン video_token を app://video/{token} に組み立てる。
  const videoToken = data?.video_token
  const videoUrl = data?.video_url
  const videoPath = videoToken ? `app://video/${videoToken}` : (videoUrl || undefined)
  const hasVideo = !!videoPath
  const hasTimestamps = data?.has_timestamps ?? false

  function jumpTo(rally: PlaylistRally) {
    setCurrentRallyId(rally.id)
    // ポップアップ表示で再生する。動画パスが無いラリーは popup は開かない。
    if (rally.video_timestamp_start != null && hasVideo) {
      setPopupRally(rally)
    }
  }

  // popup 内 video が mount したら timestamp に seek + 再生
  function onPopupVideoMount(el: HTMLVideoElement | null) {
    videoRef.current = el
    if (el && popupRally?.video_timestamp_start != null) {
      try {
        el.currentTime = popupRally.video_timestamp_start
        void el.play().catch(() => { /* autoplay 失敗は無視、ユーザクリックで再生 */ })
      } catch { /* ignore */ }
    }
  }

  // popup 内で次/前ラリーへ
  function popupNext() {
    if (!popupRally) return
    const idx = rallies.findIndex((r) => r.id === popupRally.id)
    for (let i = idx + 1; i < rallies.length; i++) {
      if (rallies[i].video_timestamp_start != null) {
        setPopupRally(rallies[i])
        setCurrentRallyId(rallies[i].id)
        return
      }
    }
  }
  function popupPrev() {
    if (!popupRally) return
    const idx = rallies.findIndex((r) => r.id === popupRally.id)
    for (let i = idx - 1; i >= 0; i--) {
      if (rallies[i].video_timestamp_start != null) {
        setPopupRally(rallies[i])
        setCurrentRallyId(rallies[i].id)
        return
      }
    }
  }

  const setNums = [...new Set(rallies.map((r) => r.set_num))].sort((a, b) => a - b)

  return (
    <div className={`rounded-lg border ${isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'}`}>
      {/* ヘッダー */}
      <div className={`flex items-center justify-between px-4 py-3 border-b ${border}`}>
        <div className="flex items-center gap-2">
          <Play size={14} className="text-blue-500" />
          <span className={`text-sm font-semibold ${textPrimary}`}>{t('auto.RallyClipNavigator.k1')}</span>
          {!hasVideo && (
            // Design Language v1.2: 警告状態は B_BAD 文字色 + 無彩色 bg (同色相重ね禁止)
            <span
              className={`text-xs px-2 py-0.5 rounded border ${isLight ? 'bg-gray-50 border-gray-200' : 'bg-gray-800 border-gray-700'}`}
              style={{ color: '#b40426' /* B_BAD */ }}
            >
              {t('rally.no_video', 'Video not saved')}
            </span>
          )}
          {hasVideo && !hasTimestamps && (
            <span className={`text-xs px-2 py-0.5 rounded ${isLight ? 'bg-gray-100 text-gray-500' : 'bg-gray-700 text-gray-400'}`}>
              {t('rally.no_timestamps', 'No timestamps')}
            </span>
          )}
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${
            isLight ? 'text-gray-600 hover:bg-gray-100' : 'text-gray-400 hover:bg-gray-700'
          }`}
        >
          <Filter size={12} />
          {t('common.filter', 'Filter')}
          <ChevronDown size={12} className={`transition-transform ${showFilters ? 'rotate-180' : ''}`} />
        </button>
      </div>

      {/* フィルターパネル */}
      {showFilters && (
        <div className={`flex flex-wrap gap-3 px-4 py-3 border-b ${border} ${isLight ? 'bg-gray-50' : 'bg-gray-700/20'}`}>
          <div className="flex flex-col gap-1">
            <label className={`text-[10px] font-medium ${textMuted}`}>{t('auto.RallyClipNavigator.k2')}</label>
            <select
              value={filterWinner}
              onChange={(e) => setFilterWinner(e.target.value)}
              className={`text-xs px-2 py-1 rounded border ${isLight ? 'bg-white border-gray-300 text-gray-700' : 'bg-gray-700 border-gray-600 text-gray-200'}`}
            >
              <option value="">{t('auto.RallyClipNavigator.k3')}</option>
              <option value="player_a">{playerAName}</option>
              <option value="player_b">{playerBName}</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className={`text-[10px] font-medium ${textMuted}`}>{t('auto.RallyClipNavigator.k4')}</label>
            <select
              value={filterEndType}
              onChange={(e) => setFilterEndType(e.target.value)}
              className={`text-xs px-2 py-1 rounded border ${isLight ? 'bg-white border-gray-300 text-gray-700' : 'bg-gray-700 border-gray-600 text-gray-200'}`}
            >
              <option value="">{t('auto.RallyClipNavigator.k3')}</option>
              {Object.entries(END_TYPE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </div>
          {setNums.length > 1 && (
            <div className="flex flex-col gap-1">
              <label className={`text-[10px] font-medium ${textMuted}`}>{t('auto.RallyClipNavigator.k5')}</label>
              <select
                value={filterSetNum}
                onChange={(e) => setFilterSetNum(e.target.value)}
                className={`text-xs px-2 py-1 rounded border ${isLight ? 'bg-white border-gray-300 text-gray-700' : 'bg-gray-700 border-gray-600 text-gray-200'}`}
              >
                <option value="">{t('auto.RallyClipNavigator.k6')}</option>
                {setNums.map((n) => (
                  <option key={n} value={String(n)}>{t('rally.set_n', { n, defaultValue: 'Set {{n}}' })}</option>
                ))}
              </select>
            </div>
          )}
          <div className="flex items-end">
            <button
              onClick={() => { setFilterWinner(''); setFilterEndType(''); setFilterSetNum('') }}
              className={`text-xs px-2 py-1 rounded border transition-colors ${isLight ? 'border-gray-300 text-gray-500 hover:bg-gray-100' : 'border-gray-600 text-gray-400 hover:bg-gray-700'}`}
            >
              {t('common.clear', 'Clear')}
            </button>
          </div>
        </div>
      )}

      {/* 動画プレイヤーはオーバーレイポップアップで表示する (この位置では in-frame
         レンダしない)。フレーム内 video は全画面切替・サイズ変化でエラーが
         多発したため (YouTube ポップアップに倣う)。
         ポップアップは render 関数末尾で fixed inset-0 overlay として描画。 */}
      {hasVideo && currentRallyId != null && (() => {
        const r = rallies.find((x) => x.id === currentRallyId)
        return r ? (
          <div className={`px-4 pt-3 pb-1 text-[11px] ${textMuted}`}>
            {t('rally.selected', { set: r.set_num, rally: r.rally_num, a: r.score_a_before, b: r.score_b_before, defaultValue: 'Selected: Set {{set}} R.{{rally}} ({{a}}–{{b}})' })}
            {r.video_timestamp_start != null && t('rally.click_popup', ' — click to play in popup')}
          </div>
        ) : null
      })()}

      {/* ラリーリスト */}
      <div className="overflow-y-auto" style={{ maxHeight: '320px' }}>
        {isLoading && (
          <div className={`px-4 py-6 text-center text-sm ${textMuted}`}>{t('auto.RallyClipNavigator.k7')}</div>
        )}
        {!isLoading && rallies.length === 0 && (
          <div className={`px-4 py-6 text-center text-sm ${textMuted}`}>
            {t('rally.no_rallies', 'No matching rallies')}
          </div>
        )}
        {!isLoading && rallies.map((r) => {
          const isActive = r.id === currentRallyId
          const hasTs = r.video_timestamp_start != null
          const winner = r.winner === 'player_a' ? playerAName : playerBName
          const endLabel = END_TYPE_LABELS[r.end_type] ?? r.end_type

          return (
            <button
              key={r.id}
              type="button"
              disabled={!hasVideo || !hasTs}
              onClick={() => jumpTo(r)}
              className={`w-full text-left flex items-center gap-3 px-4 py-2.5 border-b transition-colors
                ${isActive
                  ? (isLight ? 'bg-gray-50' : 'bg-gray-700')
                  : `${border} ${rowHover}`
                }
                ${(!hasVideo || !hasTs) ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
              `}
              /* active 状態の表現: 左罫線縦バーは禁止 (詐欺サイト感)。
                 代わりにアイコン色と font-weight で示す (下記 div / span 側)。 */
            >
              {/* ジャンプアイコン: active のみ A_GOOD 色、それ以外無彩色 */}
              <div
                className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${
                  hasTs
                    ? (isLight ? 'bg-gray-200' : 'bg-gray-700')
                    : (isLight ? 'bg-gray-100' : 'bg-gray-800')
                }`}
                style={{
                  color: isActive
                    ? '#3b4cc0' /* A_GOOD */
                    : (isLight ? '#64748b' : '#94a3b8') /* N_GRAY[500]/[400] */,
                }}
              >
                {hasTs ? <Play size={10} /> : <Clock size={10} />}
              </div>

              {/* セット / ラリー番号 */}
              <div className="shrink-0 w-20">
                <span className={`text-xs font-medium ${isActive ? 'text-blue-400' : textSecondary}`}>
                  {t('rally.s_r', { s: r.set_num, r: r.rally_num, defaultValue: 'S{{s}} R.{{r}}' })}
                </span>
                <div className={`text-[10px] ${textMuted}`}>
                  {r.score_a_before}–{r.score_b_before}
                </div>
              </div>

              {/* タイムスタンプ */}
              <div className="shrink-0 w-14">
                {hasTs ? (
                  <span className={`text-[11px] font-mono ${isActive ? 'text-blue-400' : 'text-blue-500'}`}>
                    {fmtTime(r.video_timestamp_start!)}
                  </span>
                ) : (
                  <span className={`text-[10px] ${textMuted}`}>—</span>
                )}
              </div>

              {/* 終了種別 + 勝者 */}
              <div className="flex-1 min-w-0">
                <span className={`text-xs ${textPrimary}`}>{endLabel}</span>
                <div className={`text-[10px] truncate ${textMuted}`}>
                  {t('rally.winner_strokes', { winner, len: r.rally_length, defaultValue: 'Winner: {{winner}} · {{len}} strokes' })}
                </div>
              </div>

              {/* 継続時間 */}
              {r.duration_sec != null && (
                <div className={`shrink-0 text-[10px] ${textMuted}`}>
                  {r.duration_sec.toFixed(1)}s
                </div>
              )}
            </button>
          )
        })}
      </div>

      {/* フッター */}
      <div className={`px-4 py-2 text-[10px] ${textMuted} flex justify-between`}>
        <span>{t('rally.n_rallies', { n: rallies.length, defaultValue: '{{n}} rallies' })}</span>
        {hasTimestamps && (
          <span>{t('rally.n_with_timestamps', { n: rallies.filter((r) => r.video_timestamp_start != null).length, defaultValue: '{{n}} with timestamps' })}</span>
        )}
      </div>

      {/* オーバーレイポップアップ: 動画を全画面に近い大きさで再生。
         フレーム内 embed と違いサイズ変化やレイアウト依存エラーが起きない。
         背景クリック / ✕ / Esc で閉じる。 */}
      {popupRally && hasVideo && (
        <div
          className="fixed inset-0 z-[300] bg-black/85 flex items-center justify-center p-4"
          onClick={() => setPopupRally(null)}
          onKeyDown={(e) => { if (e.key === 'Escape') setPopupRally(null) }}
          tabIndex={-1}
        >
          <div
            className="w-full max-w-5xl bg-black rounded-lg overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-3 py-2 bg-gray-900 text-gray-100">
              <span className="text-sm font-medium">
                {t('rally.popup_title', { set: popupRally.set_num, rally: popupRally.rally_num, a: popupRally.score_a_before, b: popupRally.score_b_before, defaultValue: 'Set {{set}} — R.{{rally}} ({{a}}–{{b}})' })}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={popupPrev}
                  className="px-2 py-1 text-xs rounded hover:bg-gray-700 disabled:opacity-30"
                  title={t('rally.prev_title', 'Previous rally')}
                >{t('rally.prev', '‹ Prev')}</button>
                <button
                  type="button"
                  onClick={popupNext}
                  className="px-2 py-1 text-xs rounded hover:bg-gray-700 disabled:opacity-30"
                  title={t('rally.next_title', 'Next rally')}
                >{t('rally.next', 'Next ›')}</button>
                <button
                  type="button"
                  onClick={() => setPopupRally(null)}
                  className="px-2 py-1 text-sm rounded hover:bg-gray-700"
                  title="閉じる (Esc)"
                >✕</button>
              </div>
            </div>
            <video
              key={popupRally.id /* rally 切替で video element を作り直して seek を確実に */}
              ref={onPopupVideoMount}
              src={videoPath}
              controls
              autoPlay
              className="w-full bg-black"
              style={{ maxHeight: '75vh', outline: 'none' }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
