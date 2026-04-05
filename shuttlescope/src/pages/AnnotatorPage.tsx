import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, RotateCcw, Users, ChevronLeft, ChevronRight, FolderOpen, Link } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'

import { VideoPlayer } from '@/components/video/VideoPlayer'
import { StreamingDownloadPanel } from '@/components/video/StreamingDownloadPanel'
import { WebViewPlayer } from '@/components/video/WebViewPlayer'
import { CourtDiagram } from '@/components/court/CourtDiagram'
import { ShotTypePanel } from '@/components/annotation/ShotTypePanel'
import { AttributePanel } from '@/components/annotation/AttributePanel'
import { StrokeHistory } from '@/components/annotation/StrokeHistory'
import { useAnnotationStore } from '@/store/annotationStore'
import { useKeyboard } from '@/hooks/useKeyboard'
import { useVideo } from '@/hooks/useVideo'
import { apiGet, apiPost, apiPut } from '@/api/client'
import { Match, Zone9, ShotType, GameSet } from '@/types'

// ─── 配信URL検出 ──────────────────────────────────────────────────────────────
// Electron では配信サービスの動画を直接再生できないため、yt-dlp でダウンロードする。
// localfile:// または直接再生できる URL 以外を検出する。

const STREAMING_SITE_NAMES: Record<string, string> = {
  'youtube.com': 'YouTube',
  'youtu.be': 'YouTube',
  'twitter.com': 'Twitter/X',
  'x.com': 'Twitter/X',
  't.co': 'Twitter/X',
  'instagram.com': 'Instagram',
  'tiktok.com': 'TikTok',
  'vm.tiktok.com': 'TikTok',
  'bilibili.com': 'Bilibili',
  'nicovideo.jp': 'ニコニコ動画',
  'nico.ms': 'ニコニコ動画',
  'twitch.tv': 'Twitch',
  'vimeo.com': 'Vimeo',
  'dailymotion.com': 'Dailymotion',
  'facebook.com': 'Facebook',
  'streamable.com': 'Streamable',
  'youku.com': 'Youku',
}

const DIRECT_VIDEO_EXTS = new Set(['.mp4', '.webm', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m4v', '.ts', '.mts'])

/**
 * URL が Electron で直接再生できない配信サービスのものか判定し、
 * サービス名を返す。直接再生可能な場合は null を返す。
 */
function detectStreamingSite(url: string): string | null {
  if (!url) return null
  // localfile:// はローカルファイル → 直接再生
  if (url.startsWith('localfile://')) return null
  // 拡張子が動画ファイルなら直接再生を試みる
  try {
    const pathname = new URL(url).pathname.toLowerCase()
    const ext = pathname.substring(pathname.lastIndexOf('.'))
    if (DIRECT_VIDEO_EXTS.has(ext)) return null
  } catch {
    // URL パース失敗は無視
  }
  // 既知の配信サービスに一致するか確認
  for (const [domain, name] of Object.entries(STREAMING_SITE_NAMES)) {
    if (url.includes(domain)) return name
  }
  // 未知の http(s) URL も配信URLとして扱う（yt-dlp が対応している可能性がある）
  if (url.startsWith('http://') || url.startsWith('https://')) {
    return 'Web動画'
  }
  return null
}

/**
 * 旧バージョンで保存された生のWindowsパスを localfile:// URL に変換する
 * 例: C:\path\video.mp4 → localfile:///C:/path/video.mp4
 */
function normalizeVideoPath(path: string): string {
  if (!path) return path
  if (/^[A-Za-z]:[/\\]/.test(path)) {
    return 'localfile:///' + path.replace(/\\/g, '/')
  }
  return path
}

// ─── END_TYPES ────────────────────────────────────────────────────────────────

const END_TYPES = [
  { value: 'ace', label: 'エース' },
  { value: 'forced_error', label: '強制エラー' },
  { value: 'unforced_error', label: '自滅' },
  { value: 'net', label: 'ネット' },
  { value: 'out', label: 'アウト' },
  { value: 'cant_reach', label: '届かず' },
]

export function AnnotatorPage() {
  const { matchId } = useParams<{ matchId: string }>()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const videoRef = useRef<HTMLVideoElement>(null)
  const { playbackRate, setPlaybackRate } = useVideo(videoRef)

  const store = useAnnotationStore()
  const [initialized, setInitialized] = useState(false)
  const [initError, setInitError] = useState<string | null>(null)
  const [urlInput, setUrlInput] = useState('')
  // DRM対応WebViewモード: yt-dlpでダウンロードできないDRM保護コンテンツに使用
  const [useWebView, setUseWebView] = useState(false)
  // Ref guard: prevent useEffect from re-running doInit on every Zustand state change
  const initStartedRef = useRef(false)

  // --- データフェッチ ---
  const { data: matchData } = useQuery({
    queryKey: ['match', matchId],
    queryFn: () => apiGet<{ success: boolean; data: Match }>(`/matches/${matchId}`),
    enabled: !!matchId,
  })

  const { data: annotationStateData } = useQuery({
    queryKey: ['annotation-state', matchId],
    queryFn: () =>
      apiGet<{
        success: boolean
        data: {
          match_id: number
          current_set_num: number
          current_rally_num: number
          score_a: number
          score_b: number
        }
      }>(`/annotation/${matchId}/state`),
    enabled: !!matchId,
  })

  const { data: setsData } = useQuery({
    queryKey: ['sets', matchId],
    queryFn: () => apiGet<{ success: boolean; data: GameSet[] }>(`/sets/match/${matchId}`),
    enabled: !!matchId,
  })

  // --- ストア初期化（セット作成 + ラリー番号取得） ---
  // NOTE: initStartedRef で多重実行を防止。store を deps に含めると
  //       store.init() → Zustand状態変化 → store 参照変化 → effect 再実行 の
  //       無限ループが起きるため、getState() で安定参照を使う。
  useEffect(() => {
    if (!matchId || !annotationStateData || !setsData) return
    if (initStartedRef.current) return
    initStartedRef.current = true

    const state = annotationStateData.data
    const sets = setsData.data

    const doInit = async () => {
      try {
        let setId: number

        // 現在のセット番号に対応するセットを探す
        const currentSet = sets.find((s) => s.set_num === state.current_set_num)
        if (currentSet) {
          setId = currentSet.id
        } else {
          // 存在しなければ作成（idempotent）
          const res = await apiPost<{ success: boolean; data: GameSet }>('/sets', {
            match_id: Number(matchId),
            set_num: state.current_set_num,
          })
          setId = res.data.id
        }

        // getState() で stable 参照を取得（リアクティブ購読を避ける）
        useAnnotationStore.getState().init(
          Number(matchId),
          setId,
          state.current_set_num,
          state.current_rally_num,
          state.score_a,
          state.score_b
        )
        setInitialized(true)
      } catch (err: any) {
        initStartedRef.current = false // リトライ可能にする
        setInitError(err?.message ?? '初期化に失敗しました')
      }
    }

    doInit()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId, annotationStateData, setsData])

  // --- ラリー保存 ---
  const batchSaveMutation = useMutation({
    mutationFn: (body: any) => apiPost('/strokes/batch', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-state', matchId] })
      queryClient.invalidateQueries({ queryKey: ['sets', matchId] })
    },
  })

  const handleConfirmRally = useCallback(
    async (winner: 'player_a' | 'player_b', endType: string) => {
      const s = useAnnotationStore.getState()
      const setId = s.currentSetId
      if (!setId) {
        alert('セットIDが未設定です。再読み込みしてください。')
        return
      }

      // confirmRally の前にスコア・ラリー番号をキャプチャ
      const strokes = [...s.currentStrokes]
      const rallyNum = s.currentRallyNum
      const scoreA = s.scoreA
      const scoreB = s.scoreB
      const newScoreA = winner === 'player_a' ? scoreA + 1 : scoreA
      const newScoreB = winner === 'player_b' ? scoreB + 1 : scoreB
      const rallyStart = s.rallyStartTimestamp

      s.confirmRally(winner, endType)

      try {
        await batchSaveMutation.mutateAsync({
          rally: {
            set_id: setId,
            rally_num: rallyNum,
            server: 'player_a',
            winner,
            end_type: endType,
            rally_length: strokes.length,
            score_a_after: newScoreA,
            score_b_after: newScoreB,
            is_deuce: newScoreA >= 20 && newScoreB >= 20,
            video_timestamp_start: rallyStart ?? undefined,
          },
          strokes: strokes.map((s) => ({
            stroke_num: s.stroke_num,
            player: s.player,
            shot_type: s.shot_type,
            hit_zone: s.hit_zone,
            land_zone: s.land_zone,
            is_backhand: s.is_backhand,
            is_around_head: s.is_around_head,
            above_net: s.above_net,
            timestamp_sec: s.timestamp_sec,
          })),
        })
      } catch (err: any) {
        alert(`保存エラー: ${err?.message ?? '不明なエラー'}`)
      }
    },
    [batchSaveMutation]
  )

  // --- セット終了 → 次のセット作成 ---
  const handleNextSet = useCallback(async () => {
    const s = useAnnotationStore.getState()
    const setId = s.currentSetId
    if (!setId) return

    const winner = s.scoreA > s.scoreB ? 'player_a' : 'player_b'
    try {
      // 現セット終了
      await apiPut(`/sets/${setId}/end`, {
        winner,
        score_a: s.scoreA,
        score_b: s.scoreB,
      })

      // 次のセット作成
      const nextSetNum = s.currentSetNum + 1
      const res = await apiPost<{ success: boolean; data: GameSet }>('/sets', {
        match_id: Number(matchId),
        set_num: nextSetNum,
      })

      useAnnotationStore.getState().nextSet(res.data.id, nextSetNum)
      queryClient.invalidateQueries({ queryKey: ['sets', matchId] })
    } catch (err: any) {
      alert(`セット移行エラー: ${err?.message ?? '不明なエラー'}`)
    }
  }, [matchId, queryClient])

  // --- 前セットへ戻る ---
  const handlePrevSet = useCallback(async () => {
    const s = useAnnotationStore.getState()
    const sets = setsData?.data ?? []
    const prevSetNum = s.currentSetNum - 1
    if (prevSetNum < 1) return

    const prevSet = sets.find((set) => set.set_num === prevSetNum)
    if (!prevSet) return

    try {
      const res = await apiGet<{ success: boolean; data: { count: number; next_rally_num: number } }>(
        `/sets/${prevSet.id}/rally_count`
      )
      useAnnotationStore.getState().init(
        Number(matchId),
        prevSet.id,
        prevSetNum,
        res.data.next_rally_num,
        prevSet.score_a ?? 0,
        prevSet.score_b ?? 0
      )
      queryClient.invalidateQueries({ queryKey: ['sets', matchId] })
    } catch (err: any) {
      alert(`前セット移行エラー: ${err?.message ?? '不明なエラー'}`)
    }
  }, [matchId, setsData, queryClient])

  // --- 動画ソース: match.video_url をURLInputに同期 ---
  useEffect(() => {
    if (matchData?.data?.video_url) setUrlInput(matchData.data.video_url)
  }, [matchData?.data?.video_url])

  // --- ファイルピッカー（Electron IPC） ---
  const handleFileOpen = useCallback(async () => {
    if (!window.shuttlescope?.openVideoFile) {
      alert('ファイル選択はElectronアプリ版のみ使用できます。')
      return
    }
    const fileUrl = await window.shuttlescope.openVideoFile()
    if (!fileUrl) return
    try {
      await apiPut(`/matches/${matchId}`, { video_local_path: fileUrl, video_url: '' })
      setUrlInput('')
      queryClient.invalidateQueries({ queryKey: ['match', matchId] })
    } catch (err: any) {
      alert(`保存エラー: ${err?.message ?? '不明なエラー'}`)
    }
  }, [matchId, queryClient])

  // --- URL入力保存 ---
  const handleUrlSave = useCallback(async () => {
    const url = urlInput.trim()
    if (!url) return
    try {
      await apiPut(`/matches/${matchId}`, { video_url: url, video_local_path: '' })
      queryClient.invalidateQueries({ queryKey: ['match', matchId] })
    } catch (err: any) {
      alert(`保存エラー: ${err?.message ?? '不明なエラー'}`)
    }
  }, [matchId, urlInput, queryClient])

  // --- キーボードショートカット ---
  useKeyboard({ videoRef, enabled: initialized })

  const match = matchData?.data

  // ステップラベル
  const stepLabel = {
    idle: store.isRallyActive
      ? `ショットキーを押してください（${store.currentPlayer === 'player_a' ? match?.player_a?.name ?? 'A' : match?.player_b?.name ?? 'B'} 打球中）`
      : 'ショットキーを押してラリー開始',
    land_zone: `着地ゾーンをクリック（${store.pendingStroke.shot_type ?? ''}）`,
    rally_end: 'ラリー終了 — 得点者と終了種別を選択',
  }[store.inputStep]

  if (initError) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-900 text-white">
        <div className="text-center">
          <div className="text-red-400 text-lg mb-2">初期化エラー</div>
          <div className="text-gray-400 text-sm mb-4">{initError}</div>
          <button onClick={() => navigate('/matches')} className="px-4 py-2 bg-blue-600 rounded text-sm">
            戻る
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-screen bg-gray-900 text-white overflow-hidden">
      {/* ヘッダー */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700 shrink-0">
        <button
          onClick={() => navigate('/matches')}
          className="flex items-center gap-1 text-gray-400 hover:text-white text-sm"
        >
          <ArrowLeft size={16} />
          戻る
        </button>
        <div className="text-sm font-medium">
          {match
            ? `${match.tournament} — ${match.player_a?.name ?? 'A'} vs ${match.player_b?.name ?? 'B'}`
            : 'ShuttleScope'}
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <div className="w-24 h-1.5 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all"
              style={{ width: `${(match?.annotation_progress ?? 0) * 100}%` }}
            />
          </div>
          <span>{Math.round((match?.annotation_progress ?? 0) * 100)}%</span>
        </div>
      </div>

      {/* メインレイアウト */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左: 動画エリア (60%) */}
        <div className="w-[60%] flex flex-col p-3 gap-2 overflow-y-auto">
          {(() => {
            // 動画ソース決定（旧形式の Windows パスを normalizeVideoPath で変換）
            const rawSrc = match?.video_local_path || match?.video_url || ''
            const videoSrc = normalizeVideoPath(rawSrc)
            const streamingSiteName = videoSrc ? detectStreamingSite(videoSrc) : null

            if (!videoSrc) {
              return (
                <div className="flex items-center justify-center bg-gray-800 rounded text-gray-500 text-sm border-2 border-dashed border-gray-700" style={{ aspectRatio: '16/9' }}>
                  動画が設定されていません
                </div>
              )
            }

            if (streamingSiteName) {
              // WebViewモード: DRM保護コンテンツをインブラウザで視聴
              if (useWebView) {
                return (
                  <div className="flex flex-col gap-1">
                    <WebViewPlayer url={videoSrc} siteName={streamingSiteName} />
                    <button
                      onClick={() => setUseWebView(false)}
                      className="text-xs text-gray-500 hover:text-gray-300 text-left px-1"
                    >
                      ← ダウンロード再生に戻る
                    </button>
                  </div>
                )
              }

              // yt-dlpダウンロードモード（デフォルト）
              return (
                <div className="flex flex-col gap-1">
                  <StreamingDownloadPanel
                    url={videoSrc}
                    matchId={matchId!}
                    siteName={streamingSiteName}
                    onDownloadComplete={() => {
                      queryClient.invalidateQueries({ queryKey: ['match', matchId] })
                    }}
                  />
                  {/* DRM保護コンテンツはWebViewモードで視聴 */}
                  <button
                    onClick={() => setUseWebView(true)}
                    className="text-xs text-gray-500 hover:text-blue-400 text-left px-1 flex items-center gap-1"
                    title="DRM保護コンテンツ（yt-dlpでダウンロードできない場合）はこちら"
                  >
                    🔒 DRM保護コンテンツ／ログイン必須サイトはブラウザ内視聴モードを使用
                  </button>
                </div>
              )
            }

            return (
              <VideoPlayer
                videoRefProp={videoRef}
                src={videoSrc}
                playbackRate={playbackRate}
                onPlaybackRateChange={setPlaybackRate}
              />
            )
          })()}

          {/* 動画ソース設定 */}
          <div className="bg-gray-800 rounded p-2 text-xs shrink-0">
            <div className="text-gray-400 font-medium mb-1.5">動画ソース</div>
            <div className="flex gap-1.5 items-center">
              <button
                onClick={handleFileOpen}
                className="flex items-center gap-1 px-2 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded whitespace-nowrap"
                title="ローカルファイルを選択"
              >
                <FolderOpen size={12} />
                ファイルを開く
              </button>
              <input
                type="text"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleUrlSave() }}
                placeholder="YouTube URL / 動画URL"
                className="flex-1 px-2 py-1.5 bg-gray-700 text-gray-200 rounded border border-gray-600 focus:border-blue-500 outline-none min-w-0"
              />
              <button
                onClick={handleUrlSave}
                className="flex items-center gap-1 px-2 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded whitespace-nowrap"
              >
                <Link size={12} />
                設定
              </button>
            </div>
            {(match?.video_local_path || match?.video_url) && (
              <div className="mt-1 text-gray-500 truncate">
                {match?.video_local_path
                  ? `📁 ${match.video_local_path.split(/[/\\]/).pop()?.replace('localfile:///', '') ?? match.video_local_path}`
                  : `🔗 ${match?.video_url}`}
              </div>
            )}
          </div>

          {/* ショートカットガイド */}
          <div className="bg-gray-800 rounded p-2 text-xs text-gray-400 shrink-0">
            <div className="font-medium text-gray-300 mb-1">キーボードショートカット</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
              <span><kbd className="bg-gray-700 px-1 rounded">Space</kbd> 再生/一時停止</span>
              <span><kbd className="bg-gray-700 px-1 rounded">Tab</kbd> プレイヤー切替</span>
              <span><kbd className="bg-gray-700 px-1 rounded">s/c/p…</kbd> ショット入力</span>
              <span><kbd className="bg-gray-700 px-1 rounded">Enter</kbd> ラリー終了確認</span>
              <span><kbd className="bg-gray-700 px-1 rounded">Ctrl+Z</kbd> 戻す</span>
              <span><kbd className="bg-gray-700 px-1 rounded">Esc</kbd> キャンセル</span>
              <span><kbd className="bg-gray-700 px-1 rounded">←/→</kbd> 1フレーム</span>
              <span><kbd className="bg-gray-700 px-1 rounded">Shift+←/→</kbd> 10秒</span>
            </div>
          </div>
        </div>

        {/* 右: 入力パネル (40%) */}
        <div className="w-[40%] flex flex-col border-l border-gray-700 overflow-y-auto">
          {/* ステップインジケーター */}
          <div
            className={clsx(
              'px-3 py-2 text-xs font-medium border-b border-gray-700 shrink-0',
              store.inputStep === 'idle' ? 'text-gray-400 bg-gray-800' : 'text-blue-300 bg-blue-900/30'
            )}
          >
            {initialized ? stepLabel : '読み込み中…'}
          </div>

          <div className="flex flex-col gap-3 p-3">
            {/* スコア表示 */}
            <div className="bg-gray-800 rounded p-2 flex items-center justify-between shrink-0">
              <div className="text-center min-w-[60px]">
                <div className="text-[10px] text-gray-400 truncate">{match?.player_a?.name ?? 'A'}</div>
                <div className="text-2xl font-bold">{store.scoreA}</div>
              </div>
              <div className="text-center text-xs text-gray-500">
                <div>Set {store.currentSetNum}</div>
                <div>Rally {store.currentRallyNum}</div>
              </div>
              <div className="text-center min-w-[60px]">
                <div className="text-[10px] text-gray-400 truncate">{match?.player_b?.name ?? 'B'}</div>
                <div className="text-2xl font-bold">{store.scoreB}</div>
              </div>
            </div>

            {/* プレイヤー切替 */}
            {store.isRallyActive && (
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => store.setPlayer('player_a')}
                  className={clsx(
                    'flex-1 py-1.5 rounded text-xs font-medium transition-colors',
                    store.currentPlayer === 'player_a'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                  )}
                >
                  {match?.player_a?.name ?? 'A'}
                </button>
                <button
                  onClick={() => store.togglePlayer()}
                  className="px-2 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs"
                  title="Tab でも切替可能"
                >
                  <Users size={12} />
                </button>
                <button
                  onClick={() => store.setPlayer('player_b')}
                  className={clsx(
                    'flex-1 py-1.5 rounded text-xs font-medium transition-colors',
                    store.currentPlayer === 'player_b'
                      ? 'bg-orange-600 text-white'
                      : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                  )}
                >
                  {match?.player_b?.name ?? 'B'}
                </button>
              </div>
            )}

            {/* ラリー終了確認パネル */}
            {store.inputStep === 'rally_end' && (
              <div className="border border-yellow-700/50 bg-yellow-900/20 rounded p-2 shrink-0">
                <div className="text-xs text-yellow-400 mb-2 font-medium">ラリー終了 — 得点者と終了種別を選択</div>
                <div className="grid grid-cols-2 gap-2">
                  {(
                    [
                      { winner: 'player_a' as const, label: match?.player_a?.name ?? 'A', color: 'blue' },
                      { winner: 'player_b' as const, label: match?.player_b?.name ?? 'B', color: 'orange' },
                    ] as const
                  ).map(({ winner, label, color }) => (
                    <div key={winner} className="flex flex-col gap-1">
                      <div
                        className={clsx(
                          'text-xs font-medium text-center pb-1 border-b',
                          color === 'blue' ? 'text-blue-400 border-blue-700' : 'text-orange-400 border-orange-700'
                        )}
                      >
                        {label} 得点
                      </div>
                      {END_TYPES.map(({ value, label: endLabel }) => (
                        <button
                          key={value}
                          onClick={() => handleConfirmRally(winner, value)}
                          disabled={batchSaveMutation.isPending}
                          className={clsx(
                            'px-2 py-1 rounded text-xs transition-colors',
                            color === 'blue'
                              ? 'bg-gray-700 hover:bg-blue-700 text-gray-200'
                              : 'bg-gray-700 hover:bg-orange-700 text-gray-200',
                            batchSaveMutation.isPending && 'opacity-50 cursor-not-allowed'
                          )}
                        >
                          {endLabel}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
                <button
                  onClick={() => store.cancelRallyEnd()}
                  className="w-full mt-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-400 rounded text-xs"
                >
                  ← キャンセル (Esc)
                </button>
              </div>
            )}

            {/* ショット種別パネル（ラリー中 & rally_end 以外） */}
            {store.isRallyActive && store.inputStep !== 'rally_end' && (
              <ShotTypePanel
                selected={store.pendingStroke.shot_type ?? null}
                onSelect={(st: ShotType) => {
                  const currentSec = videoRef.current?.currentTime ?? 0
                  store.inputShotType(st, currentSec)
                }}
                disabled={false}
                strokeNum={store.currentStrokeNum}
                lastShotType={
                  store.currentStrokes.length > 0
                    ? store.currentStrokes[store.currentStrokes.length - 1].shot_type
                    : null
                }
              />
            )}

            {/* 着地ゾーン選択（land_zone ステップ時） */}
            {store.inputStep === 'land_zone' && (
              <div className="flex flex-col gap-1 shrink-0">
                <div className="text-xs text-gray-400 text-center">
                  着地ゾーンをクリック（自動確定）
                </div>
                <div className="flex justify-center">
                  <CourtDiagram
                    mode="land"
                    selectedZone={store.pendingStroke.land_zone ?? null}
                    onZoneSelect={(zone: Zone9) => store.selectLandZone(zone)}
                    interactive={true}
                    label="着地点（相手コート）"
                  />
                </div>
                {/* 打点（自動推定済み） */}
                {store.pendingStroke.hit_zone && (
                  <div className="text-[10px] text-gray-500 text-center">
                    打点 (自動): {store.pendingStroke.hit_zone}
                  </div>
                )}
              </div>
            )}

            {/* 属性パネル（ラリー中 & idle/land_zone） */}
            {store.isRallyActive && store.inputStep !== 'rally_end' && (
              <AttributePanel
                attributes={{
                  is_backhand: store.pendingStroke.is_backhand,
                  is_around_head: store.pendingStroke.is_around_head,
                  above_net: store.pendingStroke.above_net,
                }}
                onChange={(attrs) => {
                  if (attrs.is_backhand !== store.pendingStroke.is_backhand)
                    store.toggleAttribute('is_backhand')
                  if (attrs.is_around_head !== store.pendingStroke.is_around_head)
                    store.toggleAttribute('is_around_head')
                  if (attrs.above_net !== store.pendingStroke.above_net)
                    store.setAboveNet(attrs.above_net)
                }}
                disabled={false}
              />
            )}

            {/* ラリー開始ボタン（待機中かつラリー未開始） */}
            {initialized && !store.isRallyActive && store.inputStep === 'idle' && (
              <button
                onClick={() => store.startRally(videoRef.current?.currentTime ?? 0)}
                className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium"
              >
                ▶ ラリー開始
              </button>
            )}

            {/* ストローク履歴 */}
            <StrokeHistory
              strokes={store.currentStrokes}
              playerAName={match?.player_a?.name ?? 'A'}
              playerBName={match?.player_b?.name ?? 'B'}
            />

            {/* アクションボタン */}
            <div className="flex flex-col gap-1.5 shrink-0">
              {/* ラリー終了ボタン */}
              {store.isRallyActive && store.currentStrokes.length > 0 && store.inputStep !== 'rally_end' && (
                <button
                  onClick={() => store.endRallyRequest()}
                  className="w-full py-2 bg-green-700 hover:bg-green-600 text-white rounded text-sm font-medium"
                >
                  ✅ ラリー終了 (Enter)
                </button>
              )}

              {/* アンドゥ */}
              {store.currentStrokes.length > 0 && (
                <button
                  onClick={() => store.undoLastStroke()}
                  className="flex items-center gap-1 justify-center py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm"
                >
                  <RotateCcw size={14} />
                  戻す (Ctrl+Z)
                </button>
              )}

              {/* ラリーリセット */}
              {store.isRallyActive && (
                <button
                  onClick={() => store.resetRally()}
                  className="w-full py-1.5 bg-red-900/50 hover:bg-red-800/50 text-red-400 rounded text-xs"
                >
                  ✕ ラリーキャンセル
                </button>
              )}
            </div>

            {/* セット管理 */}
            {initialized && !store.isRallyActive && (
              <div className="border border-gray-700 rounded p-2 text-xs shrink-0">
                <div className="text-gray-400 mb-1.5 font-medium">セット管理</div>
                <div className="flex gap-1.5">
                  <button
                    onClick={handlePrevSet}
                    disabled={store.currentSetNum <= 1}
                    className="flex items-center gap-1 flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded justify-center disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <ChevronLeft size={12} />
                    前のセット (Set {store.currentSetNum - 1})
                  </button>
                  <button
                    onClick={handleNextSet}
                    className="flex items-center gap-1 flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded justify-center"
                  >
                    <ChevronRight size={12} />
                    次のセットへ (Set {store.currentSetNum + 1})
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
