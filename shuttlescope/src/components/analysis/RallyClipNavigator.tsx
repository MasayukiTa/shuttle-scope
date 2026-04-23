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

  const { card, textPrimary, textMuted, textSecondary, border, rowHover, isLight } = useCardTheme()

  // フィルター状態
  const [filterWinner, setFilterWinner] = useState<string>('')
  const [filterEndType, setFilterEndType] = useState<string>('')
  const [filterSetNum, setFilterSetNum] = useState<string>('')
  const [showFilters, setShowFilters] = useState(false)

  // 動画 ref（親コンポーネントが <video> を持っている場合に使う代わりに
  // ここで独立した <video> タグを管理する）
  const videoRef = useRef<HTMLVideoElement | null>(null)
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
  const videoPath = data?.video_local_path
  const hasVideo = !!videoPath
  const hasTimestamps = data?.has_timestamps ?? false

  function jumpTo(rally: PlaylistRally) {
    setCurrentRallyId(rally.id)
    if (!videoRef.current || rally.video_timestamp_start == null) return
    videoRef.current.currentTime = rally.video_timestamp_start
    videoRef.current.play().catch(() => {})
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
            <span className={`text-xs px-2 py-0.5 rounded ${isLight ? 'bg-yellow-50 text-yellow-700 border border-yellow-200' : 'bg-yellow-900/30 text-yellow-400 border border-yellow-700/40'}`}>
              動画未保存
            </span>
          )}
          {hasVideo && !hasTimestamps && (
            <span className={`text-xs px-2 py-0.5 rounded ${isLight ? 'bg-gray-100 text-gray-500' : 'bg-gray-700 text-gray-400'}`}>
              タイムスタンプ未記録
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
          フィルター
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
                  <option key={n} value={String(n)}>Set {n}</option>
                ))}
              </select>
            </div>
          )}
          <div className="flex items-end">
            <button
              onClick={() => { setFilterWinner(''); setFilterEndType(''); setFilterSetNum('') }}
              className={`text-xs px-2 py-1 rounded border transition-colors ${isLight ? 'border-gray-300 text-gray-500 hover:bg-gray-100' : 'border-gray-600 text-gray-400 hover:bg-gray-700'}`}
            >
              クリア
            </button>
          </div>
        </div>
      )}

      {/* 動画プレイヤー（動画あるとき） */}
      {hasVideo && (
        <div className={`px-4 pt-3 pb-1`}>
          <video
            ref={videoRef}
            src={videoPath.startsWith('localfile://') ? videoPath : `localfile://${videoPath}`}
            controls
            className="w-full rounded max-h-56 bg-black"
            style={{ outline: 'none' }}
          />
          {currentRallyId != null && (() => {
            const r = rallies.find((x) => x.id === currentRallyId)
            return r ? (
              <p className={`text-[10px] mt-1 ${textMuted}`}>
                Set {r.set_num} — R.{r.rally_num}（{r.score_a_before}–{r.score_b_before}）
              </p>
            ) : null
          })()}
        </div>
      )}

      {/* ラリーリスト */}
      <div className="overflow-y-auto" style={{ maxHeight: '320px' }}>
        {isLoading && (
          <div className={`px-4 py-6 text-center text-sm ${textMuted}`}>{t('auto.RallyClipNavigator.k7')}</div>
        )}
        {!isLoading && rallies.length === 0 && (
          <div className={`px-4 py-6 text-center text-sm ${textMuted}`}>
            該当ラリーがありません
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
                  ? (isLight ? 'bg-blue-50 border-blue-100' : 'bg-blue-900/20 border-blue-800/30')
                  : `${border} ${rowHover}`
                }
                ${(!hasVideo || !hasTs) ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
              `}
            >
              {/* ジャンプアイコン */}
              <div className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center
                ${isActive
                  ? 'bg-blue-500 text-white'
                  : hasTs
                    ? (isLight ? 'bg-gray-100 text-gray-500' : 'bg-gray-700 text-gray-400')
                    : (isLight ? 'bg-gray-50 text-gray-300' : 'bg-gray-800 text-gray-600')
                }`}>
                {hasTs ? <Play size={10} /> : <Clock size={10} />}
              </div>

              {/* セット / ラリー番号 */}
              <div className="shrink-0 w-20">
                <span className={`text-xs font-medium ${isActive ? 'text-blue-400' : textSecondary}`}>
                  S{r.set_num} R.{r.rally_num}
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
                  勝: {winner}　{r.rally_length} ストローク
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
        <span>{rallies.length} ラリー</span>
        {hasTimestamps && (
          <span>{rallies.filter((r) => r.video_timestamp_start != null).length} 件にタイムスタンプあり</span>
        )}
      </div>
    </div>
  )
}
