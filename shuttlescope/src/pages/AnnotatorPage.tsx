import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, RotateCcw, Users, ChevronLeft, ChevronRight, FolderOpen, Link, ClipboardEdit, OctagonX, MonitorPlay, MonitorX, Play, Pause, Timer, SkipForward, Bookmark, BookmarkCheck, MessageSquare, Share2, Keyboard, MoreVertical, Clock, ChevronDown, ChevronUp, Monitor, Globe } from 'lucide-react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { clsx } from 'clsx'

import { VideoPlayer } from '@/components/video/VideoPlayer'
import { StreamingDownloadPanel } from '@/components/video/StreamingDownloadPanel'
import { WebViewPlayer } from '@/components/video/WebViewPlayer'
import { CourtDiagram } from '@/components/court/CourtDiagram'
import { ShotTypePanel } from '@/components/annotation/ShotTypePanel'
import { AttributePanel } from '@/components/annotation/AttributePanel'
import { StrokeHistory } from '@/components/annotation/StrokeHistory'
import { SetIntervalSummary } from '@/components/analysis/SetIntervalSummary'
import { SessionShareModal } from '@/components/annotation/SessionShareModal'
import { DeviceManagerPanel } from '@/components/session/DeviceManagerPanel'
import { WarmupNotesPanel } from '@/components/annotation/WarmupNotesPanel'
import { useAnnotationStore } from '@/store/annotationStore'
import { useKeyboard } from '@/hooks/useKeyboard'
import { useVideo } from '@/hooks/useVideo'
import { apiGet, apiPost, apiPut } from '@/api/client'
import { Match, Zone9, LandZone, ShotType, GameSet, Player, VideoSourceMode, DisplayInfo } from '@/types'
import { useMatchTimer } from '@/hooks/useMatchTimer'
import { useSettings } from '@/hooks/useSettings'
import { useIsMobile } from '@/hooks/useIsMobile'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useCVJobs } from '@/hooks/annotator/useCVJobs'
import { useSessionSharing } from '@/hooks/annotator/useSessionSharing'
import { useCVCandidates } from '@/hooks/annotator/useCVCandidates'
import { AnnotatorVideoPane } from '@/components/annotator/AnnotatorVideoPane'
import { CVAssistPanel } from '@/components/annotation/CVAssistPanel'
import { ReviewQueuePanel as CVReviewQueuePanel } from '@/components/annotation/ReviewQueuePanel'

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

// ─── コートチェンジ計算 ────────────────────────────────────────────────────────
// BWFルール: セット開始ごとにサイドチェンジ、第3セットは11点でサイドチェンジ
// setNum=1 → 0回チェンジ, setNum=2 → 1回, setNum=3 → 2回（+11pt時さらに1回）
function computePlayerASide(
  initial: 'top' | 'bottom',
  setNum: number,
  scoreA: number,
  scoreB: number
): 'top' | 'bottom' {
  const betweenSets = setNum - 1
  const midSet = setNum === 3 && Math.max(scoreA, scoreB) >= 11 ? 1 : 0
  const flipped = (betweenSets + midSet) % 2 === 1
  return flipped ? (initial === 'top' ? 'bottom' : 'top') : initial
}

// ─── END_TYPES ────────────────────────────────────────────────────────────────
// B-1: ace はバドミントン用語として誤解を招くため UI 表示を「ウィナー」に変更
// 内部コード値は backward-compat のため ace のまま維持

const END_TYPES = [
  { value: 'ace', label: 'ウィナー' },
  { value: 'forced_error', label: '強制エラー' },
  { value: 'unforced_error', label: '自滅' },
  { value: 'net', label: 'ネット' },
  { value: 'out', label: 'アウト' },
  { value: 'cant_reach', label: '届かず' },
]

// B-2: エンドタイプと最終打者から勝者を推定
// out/net → 打者の相手が勝つ（打者がアウト/ネット）
// cant_reach → 打者が勝つ（相手が取れない）
// ace → 打者が勝つ（クリーンウィナー）
// forced_error/unforced_error → 文脈依存のため手動選択
function getSuggestedWinner(
  endType: string | null,
  lastStriker: 'player_a' | 'player_b' | undefined
): 'player_a' | 'player_b' | null {
  if (!endType || !lastStriker) return null
  const opponent = lastStriker === 'player_a' ? 'player_b' : 'player_a'
  if (endType === 'out' || endType === 'net') return opponent
  if (endType === 'cant_reach' || endType === 'ace') return lastStriker
  return null
}

// B-3: 無効な勝者/エンドタイプの組み合わせを検出
function isWinnerBlocked(
  winner: 'player_a' | 'player_b',
  endType: string | null,
  lastStriker: 'player_a' | 'player_b' | undefined
): boolean {
  if (!endType || !lastStriker) return false
  // 打者自身がアウト/ネット → 打者は勝てない
  if ((endType === 'out' || endType === 'net') && winner === lastStriker) return true
  // 相手が取れなかった → 相手は勝てない
  if (endType === 'cant_reach' && winner !== lastStriker) return true
  return false
}

export function AnnotatorPage() {
  const { matchId } = useParams<{ matchId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const videoRef = useRef<HTMLVideoElement>(null)
  const { playbackRate, setPlaybackRate } = useVideo(videoRef)

  const store = useAnnotationStore()
  const { settings: appSettings } = useSettings()
  const isLight = useIsLightMode()
  const [initialized, setInitialized] = useState(false)
  const [initError, setInitError] = useState<string | null>(null)
  const [urlInput, setUrlInput] = useState('')
  // DRM対応WebViewモード: yt-dlpでダウンロードできないDRM保護コンテンツに使用
  const [useWebView, setUseWebView] = useState(false)
  // コートグリッドオーバーレイ
  const [courtGridVisible, setCourtGridVisible] = useState(false)
  // Ref guard: prevent useEffect from re-running doInit on every Zustand state change
  const initStartedRef = useRef(false)

  const isMobile = useIsMobile()

  // K-001: 試合中モード（localStorage 永続化 + ?matchDayMode=true URL パラメータで自動有効化）
  const [isMatchDayMode, setIsMatchDayMode] = useState(
    () =>
      localStorage.getItem('shuttlescope.matchDayMode') === 'true' ||
      searchParams.get('matchDayMode') === 'true'
  )

  // Annotation モード: basic（後追い入力最適化）/ detailed（エンリッチメント自動展開）
  const [annotationMode, setAnnotationMode] = useState<'basic' | 'detailed'>(
    () => {
      const stored = localStorage.getItem('shuttlescope.annotationMode')
      if (stored === 'detailed') return 'detailed'
      const param = searchParams.get('annotationMode')
      if (param === 'detailed') return 'detailed'
      return 'basic'
    }
  )
  const isBasicMode = annotationMode === 'basic'
  // モバイル時はタッチ操作用に大きいボタンを使う（isMatchDayMode と同等）
  const useLargeTouch = isMatchDayMode || isMobile
  // K-001: rally_end ステップでの選択中エンドタイプ
  const [pendingEndType, setPendingEndType] = useState<string | null>(null)

  // 一時保存（Auto-save）
  const autoSaveKey = matchId ? `shuttlescope.autosave.${matchId}` : null
  const [autoSaveRestored, setAutoSaveRestored] = useState(false)
  const [lastAutoSaveTime, setLastAutoSaveTime] = useState<number | null>(null)

  // C-1: セット移行確認ダイアログ
  const [setNavConfirm, setSetNavConfirm] = useState<{ direction: 'prev' | 'next' } | null>(null)

  // K-003: セット間サマリーモーダル
  const [showIntervalSummary, setShowIntervalSummary] = useState(false)
  const [intervalSummarySetId, setIntervalSummarySetId] = useState<number | null>(null)
  const [nextSetPending, setNextSetPending] = useState<{ id: number; num: number } | null>(null)

  // V4-U-001: 試合中補完パネル
  const [showInMatchPanel, setShowInMatchPanel] = useState(false)
  const [inMatchDominantHand, setInMatchDominantHand] = useState<string>('')
  const [inMatchOrganization, setInMatchOrganization] = useState<string>('')
  const [inMatchScoutingNotes, setInMatchScoutingNotes] = useState<string>('')
  const [inMatchSaved, setInMatchSaved] = useState(false)

  // 試合中モード: キーボード凡例オーバーレイ
  const [showLegendOverlay, setShowLegendOverlay] = useState(false)

  // 途中終了ダイアログ
  const [showExceptionDialog, setShowExceptionDialog] = useState(false)
  const [exceptionReason, setExceptionReason] = useState<'retired_a' | 'retired_b' | 'abandoned' | null>(null)

  // 11点インターバル解析
  const [showMidGameSummary, setShowMidGameSummary] = useState(false)
  const [midGameShown, setMidGameShown] = useState(false)  // セットごとにリセット

  // P1: 見逃しラリー・スコア補正・セット強制終了
  const [showSkipRallyDialog, setShowSkipRallyDialog] = useState(false)
  const [showScoreCorrection, setShowScoreCorrection] = useState(false)
  const [correctionTargetA, setCorrectionTargetA] = useState(0)
  const [correctionTargetB, setCorrectionTargetB] = useState(0)
  const [showForceSetEnd, setShowForceSetEnd] = useState(false)
  const [forceSetScoreA, setForceSetScoreA] = useState(0)
  const [forceSetScoreB, setForceSetScoreB] = useState(0)

  // アナリスト視点（セット1開始時のplayer_aの位置）
  const [playerAStart, setPlayerAStart] = useState<'top' | 'bottom'>(
    () => (localStorage.getItem(`shuttlescope.viewpoint.${matchId}`) as 'top' | 'bottom') ?? 'bottom'
  )

  // P2: 映像ソースモード + 手動タイマー
  const [videoSourceMode, setVideoSourceMode] = useState<VideoSourceMode>('local')
  const timer = useMatchTimer()

  // P4: デュアルモニター
  const [displays, setDisplays] = useState<DisplayInfo[]>([])
  const [videoWindowOpen, setVideoWindowOpen] = useState(false)

  // U-001: ブックマーク
  const [lastBookmarked, setLastBookmarked] = useState<number | null>(null)  // rally_id

  // Review Later
  const [lastSavedRallyId, setLastSavedRallyId] = useState<number | null>(null)
  const [reviewLaterAdded, setReviewLaterAdded] = useState(false)
  const [reviewQueueOpen, setReviewQueueOpen] = useState(false)

  // CV補助アノテーション
  const [showCVAssistPanel, setShowCVAssistPanel] = useState(false)
  const [cvReviewQueueOpen, setCVReviewQueueOpen] = useState(false)

  // S-003: コメント
  const [showCommentInput, setShowCommentInput] = useState(false)
  const [commentText, setCommentText] = useState('')
  const [commentRallyId, setCommentRallyId] = useState<number | null>(null)

  // モバイル: ヘッダーオーバーフローメニュー
  const [showMobileMenu, setShowMobileMenu] = useState(false)

  // G2: 直前確定ストロークへのエンリッチメント入力（return_quality / contact_height）
  // 落点確定後に表示し、次のショットキー押下で自動消滅
  const [enrichmentActive, setEnrichmentActive] = useState(false)

  // G3: ウォームアップメモパネル
  const [showWarmupPanel, setShowWarmupPanel] = useState(false)

  // 左パネル幅（ドラッグリサイズ）
  const [leftPanelWidth, setLeftPanelWidth] = useState<number | null>(null)
  const dragStartX = useRef<number | null>(null)
  const dragStartW = useRef<number>(0)
  const leftPanelRef = useRef<HTMLDivElement>(null)
  const handleResizeDragStart = useCallback((e: React.MouseEvent) => {
    dragStartX.current = e.clientX
    dragStartW.current = leftPanelRef.current?.offsetWidth ?? (window.innerWidth * 0.6)
    const onMove = (ev: MouseEvent) => {
      if (dragStartX.current === null) return
      const delta = ev.clientX - dragStartX.current
      const newW = Math.max(200, Math.min(window.innerWidth * 0.8, dragStartW.current + delta))
      setLeftPanelWidth(newW)
    }
    const onUp = () => {
      dragStartX.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [])

  // P3/P4: CV ジョブ（TrackNet + YOLO）— useCVJobs に委譲
  // match は後で解決されるため、後ほど useCVJobs を呼び出す（match データ取得後）

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

  // M-001: 初期化完了後、?seek= パラメータでビデオをシーク
  useEffect(() => {
    if (!initialized) return
    const seekTo = searchParams.get('seek')
    if (seekTo && videoRef.current) {
      videoRef.current.currentTime = Number(seekTo)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialized])

  // K-002: ラリー保存（fire-and-forget、UIをブロックしない）
  const midGameShownRef = useRef(midGameShown)
  useEffect(() => { midGameShownRef.current = midGameShown }, [midGameShown])

  const handleConfirmRally = useCallback(
    (winner: 'player_a' | 'player_b', endType: string) => {
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

      // UI を即時更新（fire-and-forget）
      s.confirmRally(winner, endType)
      setPendingEndType(null)
      // 一時保存をクリア
      if (autoSaveKey) localStorage.removeItem(autoSaveKey)
      setLastAutoSaveTime(null)

      // 11点インターバル: どちらかが11点に到達したとき（BWFルール）
      const prevMax = Math.max(scoreA, scoreB)
      const newMax = Math.max(newScoreA, newScoreB)
      if (prevMax < 11 && newMax >= 11 && !midGameShown) {
        setMidGameShown(true)
        setShowMidGameSummary(true)
      }

      // バックグラウンド保存
      const storeState = useAnnotationStore.getState()
      storeState.incrementPending()
      apiPost<{ success: boolean; data: { rally_id: number; stroke_count: number } }>('/strokes/batch', {
        rally: {
          set_id: setId,
          rally_num: rallyNum,
          server: strokes[0]?.player ?? 'player_a',
          winner,
          end_type: endType,
          rally_length: strokes.length,
          score_a_after: newScoreA,
          score_b_after: newScoreB,
          is_deuce: newScoreA >= 20 && newScoreB >= 20,
          video_timestamp_start: rallyStart ?? undefined,
          annotation_mode: isBasicMode ? 'manual_record' : 'assisted_record',
        },
        strokes: strokes.map((st) => ({
          stroke_num: st.stroke_num,
          player: st.player,
          shot_type: st.shot_type,
          hit_zone: st.hit_zone,
          land_zone: st.land_zone,
          is_backhand: st.is_backhand,
          is_around_head: st.is_around_head,
          above_net: st.above_net,
          timestamp_sec: st.timestamp_sec,
          // G2+移動系: オプションエンリッチメント
          return_quality: st.return_quality,
          contact_height: st.contact_height,
          contact_zone: st.contact_zone,
          movement_burden: st.movement_burden,
          movement_direction: st.movement_direction,
          source_method: isBasicMode ? 'manual' : 'assisted',
        })),
      }).then((res) => {
        useAnnotationStore.getState().decrementPending()
        queryClient.invalidateQueries({ queryKey: ['annotation-state', matchId] })
        queryClient.invalidateQueries({ queryKey: ['sets', matchId] })
        if (res?.data?.rally_id) {
          setLastSavedRallyId(res.data.rally_id)
          setReviewLaterAdded(false)
        }
      }).catch((err: any) => {
        useAnnotationStore.getState().decrementPending()
        useAnnotationStore.getState().addSaveError({
          rallyNum,
          error: err?.message ?? '保存失敗',
        })
      })
    },
    [matchId, queryClient]
  )

  // --- セット終了 → 次のセット作成 (K-003: サマリーモーダル表示) ---
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

      // K-003: 次のセット情報を保持し、サマリーモーダルを表示
      setIntervalSummarySetId(setId)
      setNextSetPending({ id: res.data.id, num: nextSetNum })
      setShowIntervalSummary(true)
    } catch (err: any) {
      alert(`セット移行エラー: ${err?.message ?? '不明なエラー'}`)
    }
  }, [matchId])

  // K-003: モーダルから「次のセットへ」
  const handleModalNextSet = useCallback(() => {
    if (!nextSetPending) return
    useAnnotationStore.getState().nextSet(nextSetPending.id, nextSetPending.num)
    queryClient.invalidateQueries({ queryKey: ['sets', matchId] })
    setShowIntervalSummary(false)
    setNextSetPending(null)
    setIntervalSummarySetId(null)
    setMidGameShown(false)  // 次セットのインターバルをリセット
  }, [nextSetPending, matchId, queryClient])

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

  // K-001: 試合中モード切替
  const toggleMatchDayMode = useCallback(() => {
    setIsMatchDayMode((prev) => {
      const next = !prev
      localStorage.setItem('shuttlescope.matchDayMode', String(next))
      return next
    })
  }, [])

  // Annotation モード切替
  const toggleAnnotationMode = useCallback(() => {
    setAnnotationMode((prev) => {
      const next = prev === 'basic' ? 'detailed' : 'basic'
      localStorage.setItem('shuttlescope.annotationMode', next)
      return next
    })
  }, [])

  // --- キーボードショートカット ---
  useKeyboard({
    videoRef,
    enabled: initialized,
    onEndTypeSelect: (endType) => {
      // rally_end ステップ中のみ有効（useKeyboard内でフィルタ済み）
      setPendingEndType((prev) => prev === endType ? null : endType)
    },
    onWinnerSelect: (winner) => {
      // A/B キーで勝者確定（pendingEndType が選択済み かつ 無効な組み合わせでない場合のみ）
      if (!pendingEndType) return
      const lastStroke = store.currentStrokes[store.currentStrokes.length - 1]
      if (isWinnerBlocked(winner, pendingEndType, lastStroke?.player)) return
      handleConfirmRally(winner, pendingEndType)
    },
    onSkipRallyOpen: () => setShowSkipRallyDialog(true),
    onToggleHitter: () => store.toggleHitterWithinTeam(),
  })

  // G2: ショット入力開始（land_zone へ遷移）でエンリッチメントストリップを自動消滅
  useEffect(() => {
    if (store.inputStep === 'land_zone') {
      setEnrichmentActive(false)
    }
  }, [store.inputStep])

  // G2: 落点確定（idle に戻る）かつラリー中かつストロークがある → エンリッチメントストリップ表示
  // ただし rally_end 遷移は除く（currentStrokes.length > prev + 1 で判定せず inputStep で判定）
  const prevInputStepRef = useRef<string>('idle')
  useEffect(() => {
    const prev = prevInputStepRef.current
    prevInputStepRef.current = store.inputStep
    // land_zone → idle の遷移 = 落点確定完了
    // Detailed モードのみ自動展開。Basic モードは手動展開のみ。
    if (prev === 'land_zone' && store.inputStep === 'idle' && store.isRallyActive && store.currentStrokes.length > 0) {
      if (annotationMode === 'detailed') {
        setEnrichmentActive(true)
      }
    }
    // rally_end や rally 終了でリセット
    if (store.inputStep === 'rally_end' || !store.isRallyActive) {
      setEnrichmentActive(false)
    }
  }, [store.inputStep, store.isRallyActive, store.currentStrokes.length])

  // rally_end に入ったときエンドタイプを自動プリフィル（B-4）
  // OOB → out, NET → net を先行選択してオペレーター負荷を削減
  useEffect(() => {
    if (store.inputStep !== 'rally_end') {
      setPendingEndType(null)
      return
    }
    const lastStroke = store.currentStrokes[store.currentStrokes.length - 1]
    const lz = lastStroke?.land_zone ? String(lastStroke.land_zone) : ''
    if (lz.startsWith('OB_')) {
      setPendingEndType('out')
    } else if (lz.startsWith('NET_')) {
      setPendingEndType('net')
    }
  }, [store.inputStep])

  // ─── 一時保存（Auto-save） ───────────────────────────────────────────────────
  // ストローク確定のたびに localStorage へ書き込み
  useEffect(() => {
    if (!autoSaveKey || !store.isRallyActive || store.currentStrokes.length === 0) return
    const now = Date.now()
    const data = {
      setId: store.currentSetId,
      rallyNum: store.currentRallyNum,
      strokes: store.currentStrokes,
      savedAt: now,
    }
    localStorage.setItem(autoSaveKey, JSON.stringify(data))
    setLastAutoSaveTime(now)
  }, [autoSaveKey, store.currentStrokes, store.isRallyActive, store.currentSetId, store.currentRallyNum])

  // 初期化完了後: 前回の未保存ストロークがあれば復元確認
  useEffect(() => {
    if (!initialized || !autoSaveKey || autoSaveRestored) return
    try {
      const raw = localStorage.getItem(autoSaveKey)
      if (!raw) return
      const saved = JSON.parse(raw) as { setId: number; rallyNum: number; strokes: any[]; savedAt: number }
      if (
        saved.strokes.length > 0 &&
        saved.setId === store.currentSetId &&
        saved.rallyNum === store.currentRallyNum
      ) {
        const age = Math.round((Date.now() - saved.savedAt) / 60000)
        const ok = window.confirm(
          `前回の未保存ストロークが見つかりました（${saved.strokes.length}本、約${age}分前）。\n復元しますか？`
        )
        if (ok) {
          // ストアに直接書き込み（store.startRally と同等の準備）
          store.startRally(store.rallyStartTimestamp ?? 0)
          for (const stroke of saved.strokes) {
            useAnnotationStore.setState((s) => ({
              currentStrokes: [...s.currentStrokes, stroke],
              currentStrokeNum: s.currentStrokeNum + 1,
            }))
          }
        } else {
          localStorage.removeItem(autoSaveKey)
        }
      }
    } catch {
      // parse失敗は無視
    }
    setAutoSaveRestored(true)
  }, [initialized]) // eslint-disable-line react-hooks/exhaustive-deps

  const match = matchData?.data

  // P3/P4: CV ジョブフック（TrackNet + YOLO バッチ解析・オーバーレイ）
  const {
    tracknetJob, setTracknetJob, shuttleFrames, shuttleOverlayVisible,
    setShuttleOverlayVisible, tracknetArtifactAt, handleTracknetBatch,
    yoloJob, setYoloJob, yoloFrames, yoloOverlayVisible,
    setYoloOverlayVisible, yoloArtifactMeta, handleYoloBatch,
    currentVideoSec, videoContainerRef,
  } = useCVJobs({
    matchId,
    match,
    tracknetEnabled: appSettings.tracknet_enabled,
    yoloEnabled: appSettings.yolo_enabled,
    tracknetBackend: appSettings.tracknet_backend,
    queryClient,
    t,
    videoRef,
  })

  // R-001/R-002: セッション共有フック
  const {
    activeSession,
    showSessionModal, setShowSessionModal,
    showDeviceManager, setShowDeviceManager,
    handleCreateOrGetSession,
    tunnelStatus, tunnelToggle, tunnelBase, tunnelPending, tunnelLastError, rebaseUrl,
    remoteStream, setRemoteStream,
    remoteStreamVideoRef,
    localCamStream, setLocalCamStream,
    localCamVideoRef,
    remoteHealth, setRemoteHealth,
  } = useSessionSharing({
    matchId,
    tunnelProvider: appSettings.tunnel_provider,
  })

  // CV補助アノテーション候補
  const {
    candidatesData,
    buildLoading: cvBuildLoading,
    buildError: cvBuildError,
    buildCandidates,
    applyCandidates,
    applyLoading: cvApplyLoading,
    applyResult: cvApplyResult,
    reviewQueue: cvReviewQueue,
    reviewQueueLoading: cvReviewQueueLoading,
    markReviewCompleted,
    getCandidateForRally,
    clearBuildError: clearCVBuildError,
  } = useCVCandidates({ matchId })

  // V4-U-001: 試合中補完パネルの相手選手ミューテーション
  const updateOpponent = useMutation({
    mutationFn: (body: Partial<Player>) =>
      apiPut(`/players/${match?.player_b_id}`, body),
    onSuccess: () => {
      setInMatchSaved(true)
      setTimeout(() => setInMatchSaved(false), 2000)
      queryClient.invalidateQueries({ queryKey: ['match', matchId] })
    },
  })

  // V4-U-001: パネルを開いたとき既存値で初期化
  useEffect(() => {
    if (showInMatchPanel && match?.player_b) {
      setInMatchDominantHand(match.player_b.dominant_hand ?? '')
      setInMatchOrganization(match.player_b.organization ?? '')
      setInMatchScoutingNotes(match.player_b.scouting_notes ?? '')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showInMatchPanel])

  // V4: initial_server を最初のラリー前にストアへ反映
  useEffect(() => {
    if (!initialized || !match?.initial_server) return
    const s = useAnnotationStore.getState()
    if (s.currentRallyNum === 1 && !s.isRallyActive) {
      s.setPlayer(match.initial_server as 'player_a' | 'player_b')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialized, match?.initial_server])

  // 先サーブ変更（DB 保存 + ストア反映）
  const handleInitialServerChange = useCallback(async (server: 'player_a' | 'player_b') => {
    if (!matchId) return
    try {
      await apiPut(`/matches/${matchId}`, { initial_server: server })
      queryClient.invalidateQueries({ queryKey: ['match', matchId] })
      // ラリー未開始なら即座にストアにも反映
      const s = useAnnotationStore.getState()
      if (s.currentRallyNum === 1 && !s.isRallyActive) {
        s.setPlayer(server)
      }
    } catch (err: any) {
      alert(`先サーブ変更エラー: ${err?.message ?? '不明なエラー'}`)
    }
  }, [matchId, queryClient])

  // アナリスト視点変更（localStorage 保存）
  const handleViewpointChange = useCallback((side: 'top' | 'bottom') => {
    setPlayerAStart(side)
    if (matchId) localStorage.setItem(`shuttlescope.viewpoint.${matchId}`, side)
  }, [matchId])

  // ダブルスモード検出 — match 読み込み後にストアへ反映
  useEffect(() => {
    if (!initialized || !match) return
    const isDoubles = match.format !== 'singles'
    useAnnotationStore.getState().setIsDoubles(isDoubles)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialized, match?.format])

  // アノテーター離脱時: バックグラウンド解析をキックして遷移
  const handleLeaveMatch = useCallback(() => {
    const videoPath = match?.video_local_path || match?.video_url || ''
    // localfile:/// プレフィックスを除去してファイルパスに変換
    const resolvedPath = videoPath.startsWith('localfile:///')
      ? videoPath.replace('localfile:///', '')
      : videoPath
    if (resolvedPath && matchId) {
      // fire-and-forget: 失敗しても離脱は妨げない
      apiPost('/video_import/path', {
        video_path: resolvedPath,
        match_id: Number(matchId),
      }).catch(() => {})
    }
    navigate('/matches')
  }, [match, matchId, navigate])

  // 途中終了: ダイアログ確定
  const handleException = useCallback(async () => {
    if (!exceptionReason) return
    // 入力中のラリーは破棄
    useAnnotationStore.getState().resetRally()
    try {
      await apiPut(`/matches/${matchId}`, {
        result: 'retired',
        exception_reason: exceptionReason,
        metadata_status: 'partial',
      })
      handleLeaveMatch()
    } catch (err: any) {
      alert(`途中終了の保存に失敗しました: ${err?.message ?? '不明なエラー'}`)
    }
  }, [exceptionReason, matchId, handleLeaveMatch])

  // P1: 見逃しラリー保存
  const handleSkipRally = useCallback((winner: 'player_a' | 'player_b') => {
    const s = useAnnotationStore.getState()
    const setId = s.currentSetId
    if (!setId) return

    const rallyNum = s.currentRallyNum
    const scoreA = s.scoreA
    const scoreB = s.scoreB
    const newScoreA = winner === 'player_a' ? scoreA + 1 : scoreA
    const newScoreB = winner === 'player_b' ? scoreB + 1 : scoreB

    // 11点インターバルチェック
    const prevMax = Math.max(scoreA, scoreB)
    const newMax = Math.max(newScoreA, newScoreB)
    if (prevMax < 11 && newMax >= 11 && !midGameShownRef.current) {
      setMidGameShown(true)
      setShowMidGameSummary(true)
    }

    s.skipRallyState(winner)
    setShowSkipRallyDialog(false)

    s.incrementPending()
    apiPost('/strokes/batch', {
      rally: {
        set_id: setId,
        rally_num: rallyNum,
        server: s.currentPlayer,
        winner,
        end_type: 'skipped',
        rally_length: 0,
        is_skipped: true,
        score_a_after: newScoreA,
        score_b_after: newScoreB,
        is_deuce: newScoreA >= 20 && newScoreB >= 20,
      },
      strokes: [],
    }).then(() => {
      useAnnotationStore.getState().decrementPending()
      queryClient.invalidateQueries({ queryKey: ['annotation-state', matchId] })
    }).catch((err: any) => {
      useAnnotationStore.getState().decrementPending()
      useAnnotationStore.getState().addSaveError({ rallyNum, error: err?.message ?? '保存失敗' })
    })
  }, [matchId, queryClient])

  // P1: スコア補正（差分をスキップラリーで埋める）
  const handleScoreCorrection = useCallback(async () => {
    const s = useAnnotationStore.getState()
    const setId = s.currentSetId
    if (!setId || s.isRallyActive) return

    const diffA = correctionTargetA - s.scoreA
    const diffB = correctionTargetB - s.scoreB
    if (diffA < 0 || diffB < 0) {
      alert(t('skip_rally.cannot_decrease'))
      return
    }
    if (diffA === 0 && diffB === 0) {
      setShowScoreCorrection(false)
      return
    }

    // 補完ラリーシーケンス（A点 + B点 を交互）
    const sequence: Array<'player_a' | 'player_b'> = []
    let a = diffA, b = diffB
    while (a > 0 || b > 0) {
      if (a > 0) { sequence.push('player_a'); a-- }
      if (b > 0) { sequence.push('player_b'); b-- }
    }

    let rallyNum = s.currentRallyNum
    let scoreA = s.scoreA
    let scoreB = s.scoreB

    s.incrementPending()
    try {
      for (const winner of sequence) {
        const newScoreA = winner === 'player_a' ? scoreA + 1 : scoreA
        const newScoreB = winner === 'player_b' ? scoreB + 1 : scoreB
        await apiPost('/strokes/batch', {
          rally: {
            set_id: setId,
            rally_num: rallyNum,
            server: winner,
            winner,
            end_type: 'skipped',
            rally_length: 0,
            is_skipped: true,
            score_a_after: newScoreA,
            score_b_after: newScoreB,
            is_deuce: newScoreA >= 20 && newScoreB >= 20,
          },
          strokes: [],
        })
        scoreA = newScoreA
        scoreB = newScoreB
        rallyNum++
      }
      useAnnotationStore.getState().applyScoreCorrection(correctionTargetA, correctionTargetB, rallyNum)
      queryClient.invalidateQueries({ queryKey: ['annotation-state', matchId] })
      setShowScoreCorrection(false)
    } catch (err: any) {
      alert(`スコア補正エラー: ${err?.message ?? '不明なエラー'}`)
    } finally {
      useAnnotationStore.getState().decrementPending()
    }
  }, [correctionTargetA, correctionTargetB, matchId, queryClient, t])

  // P1: セット強制終了（残りをスキップラリーで埋めてセット終了）
  const handleForceSetEnd = useCallback(async () => {
    const s = useAnnotationStore.getState()
    const setId = s.currentSetId
    if (!setId || s.isRallyActive) return

    const diffA = forceSetScoreA - s.scoreA
    const diffB = forceSetScoreB - s.scoreB
    if (diffA < 0 || diffB < 0) {
      alert(t('skip_rally.cannot_decrease'))
      return
    }

    // スコア補正
    const sequence: Array<'player_a' | 'player_b'> = []
    let a = diffA, b = diffB
    while (a > 0 || b > 0) {
      if (a > 0) { sequence.push('player_a'); a-- }
      if (b > 0) { sequence.push('player_b'); b-- }
    }

    let rallyNum = s.currentRallyNum
    let scoreA = s.scoreA
    let scoreB = s.scoreB

    s.incrementPending()
    try {
      for (const winner of sequence) {
        const newScoreA = winner === 'player_a' ? scoreA + 1 : scoreA
        const newScoreB = winner === 'player_b' ? scoreB + 1 : scoreB
        await apiPost('/strokes/batch', {
          rally: {
            set_id: setId, rally_num: rallyNum, server: winner, winner,
            end_type: 'skipped', rally_length: 0, is_skipped: true,
            score_a_after: newScoreA, score_b_after: newScoreB,
            is_deuce: newScoreA >= 20 && newScoreB >= 20,
          },
          strokes: [],
        })
        scoreA = newScoreA; scoreB = newScoreB; rallyNum++
      }
      useAnnotationStore.getState().applyScoreCorrection(forceSetScoreA, forceSetScoreB, rallyNum)
      setShowForceSetEnd(false)
      // セット終了フロー（handleNextSet と同じ）
      await handleNextSet()
    } catch (err: any) {
      alert(`セット強制終了エラー: ${err?.message ?? '不明なエラー'}`)
    } finally {
      useAnnotationStore.getState().decrementPending()
    }
  }, [forceSetScoreA, forceSetScoreB, matchId, queryClient, t, handleNextSet])

  // P4: 別モニタで動画を開く
  const handleOpenVideoWindow = useCallback(() => {
    const rawSrc = match?.video_local_path || match?.video_url || ''
    const src = normalizeVideoPath(rawSrc)
    if (!src || !window.shuttlescope?.openVideoWindow) return
    const secondary = displays.find((d) => !d.isPrimary) ?? displays[0]
    if (!secondary) return
    const startTime = videoRef.current?.currentTime ?? 0  // 現在の再生位置を引き継ぐ
    const isPaused = videoRef.current?.paused ?? true      // 停止状態も引き継ぐ
    window.shuttlescope.openVideoWindow(src, secondary.id, startTime, isPaused)
    setVideoWindowOpen(true)
    setVideoSourceMode('none')  // メイン側は映像なしモードに切替（video 要素を破棄して停止）
  }, [match, displays, videoRef])

  const handleCloseVideoWindow = useCallback(() => {
    window.shuttlescope?.closeVideoWindow?.()
    setVideoWindowOpen(false)
    setVideoSourceMode('local')
  }, [])

  // P2: 映像モード自動検出（match データが揃ったとき）
  useEffect(() => {
    if (!matchData?.data) return
    const m = matchData.data
    const rawSrc = m.video_local_path || m.video_url || ''
    if (!rawSrc) {
      setVideoSourceMode('none')
    } else {
      // 'webview' モードはカメラ/WebRTC専用。YouTube等の配信URLは 'local' のまま維持し、
    // レンダリング側の streamingSiteName チェックで StreamingDownloadPanel / WebViewPlayer を表示。
    setVideoSourceMode('local')
    }
  }, [matchData?.data?.video_local_path, matchData?.data?.video_url])

  // P2: タイムスタンプ取得（モードによって切替）
  const getTimestamp = useCallback((): number => {
    if (videoSourceMode === 'local' && videoRef.current) {
      return videoRef.current.currentTime
    }
    return timer.elapsedSec
  }, [videoSourceMode, timer.elapsedSec])

  // P4: ディスプレイ一覧取得
  useEffect(() => {
    window.shuttlescope?.getDisplays?.()?.then?.((d: DisplayInfo[]) => setDisplays(d ?? []))
  }, [])

  // P4: 別ウィンドウが閉じられたら状態をリセット
  useEffect(() => {
    const cleanup = window.shuttlescope?.onVideoWindowClosed?.(() => setVideoWindowOpen(false))
    return () => { cleanup?.() }
  }, [])

  // U-001: ブックマーク追加
  const handleBookmark = useCallback(async (rallyId: number | null, ts?: number) => {
    if (!matchId) return
    try {
      await apiPost('/bookmarks', {
        match_id: Number(matchId),
        rally_id: rallyId ?? undefined,
        bookmark_type: 'manual',
        video_timestamp_sec: ts ?? getTimestamp(),
      })
      setLastBookmarked(rallyId)
    } catch { /* bookmark failure is non-critical */ }
  }, [matchId, getTimestamp])

  // Review Later: 直前ラリーに review_later ノートでブックマーク
  const handleReviewLater = useCallback(async () => {
    if (!matchId || !lastSavedRallyId) return
    try {
      await apiPost('/bookmarks', {
        match_id: Number(matchId),
        rally_id: lastSavedRallyId,
        bookmark_type: 'manual',
        note: 'review_later',
      })
      setReviewLaterAdded(true)
      setTimeout(() => setReviewLaterAdded(false), 2000)
      queryClient.invalidateQueries({ queryKey: ['bookmarks-review', matchId] })
    } catch { /* non-critical */ }
  }, [matchId, lastSavedRallyId, queryClient])

  // T6: review_later ブックマーク一覧取得
  const { data: reviewBookmarksData } = useQuery({
    queryKey: ['bookmarks-review', matchId],
    queryFn: () =>
      apiGet<{ success: boolean; data: Array<{ id: number; rally_id: number | null; note: string | null; video_timestamp_sec: number | null }> }>(
        `/bookmarks?match_id=${matchId}`
      ),
    enabled: !!matchId,
    select: (res) => res?.data?.filter((b) => b.note === 'review_later') ?? [],
  })

  // S-003: コメント投稿
  const handleSubmitComment = useCallback(async () => {
    if (!matchId || !commentText.trim()) return
    try {
      await apiPost('/comments', {
        match_id: Number(matchId),
        rally_id: commentRallyId ?? undefined,
        text: commentText.trim(),
        author_role: 'analyst',
        is_flagged: false,
      })
      setCommentText('')
      setShowCommentInput(false)
      setCommentRallyId(null)
    } catch { /* ignore */ }
  }, [matchId, commentText, commentRallyId])

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
      <div className="flex items-center justify-between px-3 md:px-4 py-2 bg-gray-800 border-b border-gray-700 shrink-0">
        <button
          onClick={handleLeaveMatch}
          className={clsx(
            'flex items-center gap-1 text-gray-400 hover:text-white shrink-0',
            isMobile ? 'text-xs p-1' : 'text-sm'
          )}
        >
          <ArrowLeft size={isMobile ? 18 : 16} />
          {!isMobile && '戻る'}
        </button>
        <div className={clsx('font-medium truncate mx-2 min-w-0', isMobile ? 'text-xs' : 'text-sm')}>
          {match ? (() => {
            const isDoubles = match.format !== 'singles'
            const sideA = isDoubles && match.partner_a
              ? `${match.player_a?.name ?? 'A'} / ${match.partner_a.name}`
              : (match.player_a?.name ?? 'A')
            const sideB = isDoubles && match.partner_b
              ? `${match.player_b?.name ?? 'B'} / ${match.partner_b.name}`
              : (match.player_b?.name ?? 'B')
            return isMobile ? `${sideA} vs ${sideB}` : `${match.tournament} — ${sideA} vs ${sideB}`
          })() : 'ShuttleScope'}
        </div>

        {/* デスクトップ: 全ボタン表示 */}
        <div className="hidden md:flex items-center gap-2 text-xs text-gray-400 shrink-0">
          {/* K-002: 保存中バッジ */}
          {store.pendingSaveCount > 0 && (
            <span className="text-yellow-400 font-medium">
              {t('annotator.pending_saves')} {store.pendingSaveCount}
            </span>
          )}
          {store.saveErrors.length > 0 && (
            <button
              onClick={() => store.clearSaveErrors()}
              className="text-red-400 hover:text-red-300 font-medium"
              title={store.saveErrors.map((e) => `Rally ${e.rallyNum}: ${e.error}`).join('\n')}
            >
              {t('annotator.save_error_title')} {store.saveErrors.length}件 ✕
            </button>
          )}
          {/* V4-U-001: 試合中補完パネル */}
          {match?.player_b?.needs_review && (
            <button
              onClick={() => setShowInMatchPanel((v) => !v)}
              className={clsx(
                'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors',
                showInMatchPanel
                  ? 'bg-orange-500 text-white'
                  : 'bg-orange-500/20 text-orange-300 hover:bg-orange-500/40'
              )}
              title={t('in_match_panel.title')}
            >
              <ClipboardEdit size={12} />
              {t('in_match_panel.opponent_info')}
            </button>
          )}
          {/* P4: デュアルモニター */}
          {displays.length >= 2 && match && (match.video_local_path || match.video_url) && (
            videoWindowOpen ? (
              <button
                onClick={handleCloseVideoWindow}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-500 transition-colors"
                title={t('dual_monitor.close')}
              >
                <MonitorX size={12} />
                {t('dual_monitor.close')}
              </button>
            ) : (
              <button
                onClick={handleOpenVideoWindow}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
                title={t('dual_monitor.open')}
              >
                <MonitorPlay size={12} />
                {t('dual_monitor.open')}
              </button>
            )
          )}
          {/* 途中終了ボタン */}
          <button
            onClick={() => setShowExceptionDialog(true)}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-red-900/30 text-red-400 hover:bg-red-800/50 transition-colors"
            title={t('exception.title')}
          >
            <OctagonX size={12} />
            {t('exception.title')}
          </button>
          {/* Annotation モード切替 (手動記録 / 補助記録) */}
          <button
            onClick={toggleAnnotationMode}
            className={clsx(
              'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors',
              isBasicMode
                ? 'bg-emerald-700 text-white'
                : 'bg-purple-700 text-white'
            )}
            title={isBasicMode ? t('annotation_mode.basic_helper') : t('annotation_mode.detailed_helper')}
          >
            <span>{t('annotation_mode.label')}</span>
            {isBasicMode ? t('annotation_mode.basic') : t('annotation_mode.detailed')}
          </button>
          {/* T6: Review queue バッジ */}
          {(reviewBookmarksData?.length ?? 0) > 0 && (
            <button
              onClick={() => setReviewQueueOpen((v) => !v)}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-amber-700/40 text-amber-300 hover:bg-amber-700/60 transition-colors"
              title={t('review_later.queue_title')}
            >
              <Clock size={11} />
              {reviewBookmarksData!.length}{t('review_later.queue_badge')}
            </button>
          )}
          {/* K-001: 試合中モード切替 */}
          <button
            onClick={toggleMatchDayMode}
            className={clsx(
              'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors',
              isMatchDayMode
                ? 'bg-yellow-600 text-white'
                : 'bg-gray-700 text-gray-400 hover:text-white'
            )}
            title={isMatchDayMode ? t('annotator.match_day_mode_on') : t('annotator.match_day_mode_off')}
          >
            {t('annotator.match_day_mode')}
          </button>
          {/* P3: TrackNet バッチ解析ボタン */}
          {appSettings.tracknet_enabled && (match?.video_local_path || match?.video_url) && (
            tracknetJob && (tracknetJob.status === 'pending' || tracknetJob.status === 'running') ? (
              <div className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
                isLight ? 'bg-purple-100 text-purple-700' : 'bg-purple-900/40 text-purple-300'
              }`}>
                <span className="animate-pulse">●</span>
                {t('tracknet.batch_running')} {Math.round(tracknetJob.progress * 100)}%
              </div>
            ) : tracknetJob?.status === 'complete' ? (
              <div className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${
                isLight ? 'bg-green-100 text-green-700' : 'bg-green-900/40 text-green-300'
              }`}>
                ✓ {t('tracknet.updated_strokes', { count: tracknetJob.updated_strokes })}
              </div>
            ) : tracknetJob?.status === 'error' ? (
              <div className="flex flex-col items-start gap-0.5">
                <button
                  onClick={() => setTracknetJob(null)}
                  className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors ${
                    isLight ? 'bg-red-100 text-red-600 hover:bg-red-200' : 'bg-red-900/40 text-red-300 hover:bg-red-800/60'
                  }`}
                  title={tracknetJob.error ?? t('tracknet.batch_error')}
                >
                  ✗ {t('tracknet.batch_error_retry')}
                </button>
                {tracknetJob.error && (
                  <span className={`text-[9px] max-w-[160px] truncate ${isLight ? 'text-red-500' : 'text-red-400'}`} title={tracknetJob.error}>
                    {tracknetJob.error}
                  </span>
                )}
              </div>
            ) : (
              <button
                onClick={handleTracknetBatch}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors ${
                  isLight ? 'bg-purple-100 text-purple-700 hover:bg-purple-200' : 'bg-purple-900/40 text-purple-300 hover:bg-purple-800/60'
                }`}
                title={t('tracknet.batch_start')}
              >
                {t('tracknet.batch_start')}
              </button>
            )
          )}
          {/* CV オーバーレイグループ（YOLO + TrackNet） */}
          {appSettings.yolo_enabled && (match?.video_local_path || match?.video_url) && (
            <div className={`flex items-center gap-1 px-1.5 py-1 rounded border ${
              isLight ? 'border-gray-300 bg-gray-50' : 'border-gray-700 bg-gray-800/60'
            }`}>
              <span className={`text-[9px] font-bold uppercase tracking-wider pr-1 ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>CV</span>

              {/* アーティファクト鮮度ヒント */}
              {yoloArtifactMeta && (
                <span className={`text-[8px] ${isLight ? 'text-gray-400' : 'text-gray-600'}`} title={`最終解析: ${yoloArtifactMeta.created_at} / ${yoloArtifactMeta.frame_count}f`}>
                  {new Date(yoloArtifactMeta.created_at).toLocaleString('ja-JP', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                </span>
              )}

              {/* YOLO プレイヤー検出 */}
              {yoloJob && (yoloJob.status === 'pending' || yoloJob.status === 'running') ? (
                <div className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xs ${
                  isLight ? 'bg-blue-100 text-blue-700' : 'bg-blue-900/40 text-blue-300'
                }`}>
                  <span className="animate-pulse">●</span>
                  人物 {Math.round(yoloJob.progress * 100)}%
                </div>
              ) : yoloJob?.status === 'complete' ? (
                <button
                  onClick={() => setYoloOverlayVisible((v) => !v)}
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium transition-colors ${
                    yoloOverlayVisible
                      ? isLight ? 'bg-blue-200 text-blue-800' : 'bg-blue-700/60 text-blue-200'
                      : isLight ? 'bg-gray-200 text-gray-600 hover:bg-blue-100' : 'bg-gray-700 text-gray-400 hover:bg-blue-900/40'
                  }`}
                  title={yoloOverlayVisible ? '人物オーバーレイを非表示' : '人物オーバーレイを表示'}
                >
                  {yoloOverlayVisible ? '◉' : '○'} 人物
                </button>
              ) : yoloJob?.status === 'error' ? (
                <div className="flex flex-col items-start gap-0.5">
                  <button
                    onClick={() => setYoloJob(null)}
                    className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium ${
                      isLight ? 'bg-red-100 text-red-600' : 'bg-red-900/40 text-red-300'
                    }`}
                    title={yoloJob.error ?? t('yolo.batch_error')}
                  >
                    ✗ 人物
                  </button>
                  {yoloJob.error && (
                    <span className={`text-[9px] max-w-[140px] truncate ${isLight ? 'text-red-500' : 'text-red-400'}`} title={yoloJob.error}>
                      {yoloJob.error}
                    </span>
                  )}
                </div>
              ) : (
                <button
                  onClick={handleYoloBatch}
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium transition-colors ${
                    isLight ? 'bg-blue-100 text-blue-700 hover:bg-blue-200' : 'bg-blue-900/40 text-blue-300 hover:bg-blue-800/60'
                  }`}
                  title={t('yolo.batch_start')}
                >
                  + 人物検出
                </button>
              )}

              {/* シャトル軌跡トグル */}
              {shuttleFrames.length > 0 && (
                <button
                  onClick={() => setShuttleOverlayVisible((v) => !v)}
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium transition-colors ${
                    shuttleOverlayVisible
                      ? isLight ? 'bg-yellow-200 text-yellow-800' : 'bg-yellow-700/60 text-yellow-200'
                      : isLight ? 'bg-gray-200 text-gray-600 hover:bg-yellow-100' : 'bg-gray-700 text-gray-400 hover:bg-yellow-900/40'
                  }`}
                  title={shuttleOverlayVisible ? 'シャトル軌跡を非表示' : 'シャトル軌跡を表示'}
                >
                  {shuttleOverlayVisible ? '◉' : '○'} 軌跡
                </button>
              )}

              {/* コートグリッドオーバーレイ */}
              <button
                onClick={() => setCourtGridVisible((v) => !v)}
                className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium transition-colors ${
                  courtGridVisible
                    ? isLight ? 'bg-cyan-200 text-cyan-800' : 'bg-cyan-800/60 text-cyan-200'
                    : isLight ? 'bg-gray-200 text-gray-600 hover:bg-cyan-100' : 'bg-gray-700 text-gray-400 hover:bg-cyan-900/40'
                }`}
                title={courtGridVisible ? 'コートグリッドを非表示' : 'コートグリッドを表示'}
              >
                {courtGridVisible ? '◉' : '○'} グリッド
              </button>

              {/* 両方同時表示プリセット（両アーティファクトが揃っている場合） */}
              {yoloJob?.status === 'complete' && shuttleFrames.length > 0 && (
                <button
                  onClick={() => {
                    const bothOn = yoloOverlayVisible && shuttleOverlayVisible
                    setYoloOverlayVisible(!bothOn)
                    setShuttleOverlayVisible(!bothOn)
                  }}
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium transition-colors ${
                    yoloOverlayVisible && shuttleOverlayVisible
                      ? isLight ? 'bg-green-200 text-green-800' : 'bg-green-700/60 text-green-200'
                      : isLight ? 'bg-gray-200 text-gray-500 hover:bg-green-100' : 'bg-gray-700 text-gray-500 hover:bg-green-900/40'
                  }`}
                  title="人物・軌跡を両方同時に切り替え"
                >
                  {yoloOverlayVisible && shuttleOverlayVisible ? '◉' : '○'} 両方
                </button>
              )}
            </div>
          )}
          {/* CV補助: 候補生成・適用ボタン（TrackNet or YOLO が完了済みのとき表示） */}
          {(tracknetJob?.status === 'complete' || yoloJob?.status === 'complete') && (
            <div className={`flex items-center gap-1 px-1.5 py-1 rounded border ${
              isLight ? 'border-gray-300 bg-gray-50' : 'border-gray-700 bg-gray-800/60'
            }`}>
              <span className={`text-[9px] font-bold uppercase tracking-wider pr-1 ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>
                CV補助
              </span>
              {/* 候補生成 */}
              <button
                onClick={() => buildCandidates()}
                disabled={cvBuildLoading}
                className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors disabled:opacity-50 ${
                  candidatesData
                    ? isLight ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200' : 'bg-emerald-900/40 text-emerald-300 hover:bg-emerald-800/60'
                    : isLight ? 'bg-gray-200 text-gray-600 hover:bg-emerald-100' : 'bg-gray-700 text-gray-400 hover:bg-emerald-900/40'
                }`}
                title={candidatesData ? `候補生成済み (${candidatesData.built_at?.slice(0, 10)}) — 再生成` : 'CV候補を生成する'}
              >
                {cvBuildLoading ? '生成中...' : candidatesData ? '✓ 候補' : '候補生成'}
              </button>
              {/* 適用コントロール（高確信度・フィールド別・候補含む） */}
              {candidatesData && (
                <>
                  <button
                    onClick={() => applyCandidates('auto_filled', ['land_zone', 'hitter'])}
                    disabled={cvBuildLoading || cvApplyLoading}
                    className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors disabled:opacity-50 ${
                      isLight ? 'bg-blue-100 text-blue-700 hover:bg-blue-200' : 'bg-blue-900/40 text-blue-300 hover:bg-blue-800/60'
                    }`}
                    title="高確信度（auto_filled）のみ着地ゾーン・打者を適用"
                  >
                    高確信度適用
                  </button>
                  <button
                    onClick={() => applyCandidates('auto_filled', ['land_zone'])}
                    disabled={cvBuildLoading || cvApplyLoading}
                    className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors disabled:opacity-50 ${
                      isLight ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200' : 'bg-emerald-900/40 text-emerald-300 hover:bg-emerald-800/60'
                    }`}
                    title="高確信度の着地ゾーンのみ適用"
                  >
                    着地のみ
                  </button>
                  <button
                    onClick={() => applyCandidates('auto_filled', ['hitter'])}
                    disabled={cvBuildLoading || cvApplyLoading}
                    className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors disabled:opacity-50 ${
                      isLight ? 'bg-indigo-100 text-indigo-700 hover:bg-indigo-200' : 'bg-indigo-900/40 text-indigo-300 hover:bg-indigo-800/60'
                    }`}
                    title="高確信度の打者のみ適用"
                  >
                    打者のみ
                  </button>
                  <button
                    onClick={() => applyCandidates('suggested', ['land_zone', 'hitter'])}
                    disabled={cvBuildLoading || cvApplyLoading}
                    className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors disabled:opacity-50 ${
                      isLight ? 'bg-purple-100 text-purple-700 hover:bg-purple-200' : 'bg-purple-900/40 text-purple-300 hover:bg-purple-800/60'
                    }`}
                    title="高確信度 + 候補（suggested）を適用"
                  >
                    候補も含む
                  </button>
                </>
              )}
              {/* CV補助パネルトグル */}
              {candidatesData && (
                <button
                  onClick={() => setShowCVAssistPanel((v) => !v)}
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors ${
                    showCVAssistPanel
                      ? isLight ? 'bg-purple-200 text-purple-800' : 'bg-purple-700/60 text-purple-200'
                      : isLight ? 'bg-gray-200 text-gray-500 hover:bg-purple-100' : 'bg-gray-700 text-gray-500 hover:bg-purple-900/40'
                  }`}
                  title="CV補助パネルを表示"
                >
                  {showCVAssistPanel ? '◉' : '○'} CV詳細
                </button>
              )}
              {/* CV要確認キュー */}
              {cvReviewQueue.length > 0 && (
                <button
                  onClick={() => setCVReviewQueueOpen((v) => !v)}
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors ${
                    cvReviewQueueOpen
                      ? isLight ? 'bg-amber-200 text-amber-800' : 'bg-amber-700/60 text-amber-200'
                      : isLight ? 'bg-amber-100 text-amber-700' : 'bg-amber-900/40 text-amber-300'
                  }`}
                  title="CV要確認ラリーを表示"
                >
                  ⚠ {cvReviewQueue.filter(i => i.review_status !== 'completed').length}
                </button>
              )}
              {/* 適用結果フィードバック */}
              {cvApplyResult && (
                <span
                  className={`text-[9px] ${isLight ? 'text-emerald-600' : 'text-emerald-400'}`}
                  title={`着地: ${cvApplyResult.land_zone_count}件 / 打者: ${cvApplyResult.hitter_count}件`}
                >
                  {cvApplyResult.updated_strokes}件適用
                  {cvApplyResult.land_zone_count > 0 && ` (着地${cvApplyResult.land_zone_count})`}
                  {cvApplyResult.hitter_count > 0 && ` (打者${cvApplyResult.hitter_count})`}
                </span>
              )}
              {/* ビルドエラー */}
              {cvBuildError && (
                <span className={`text-[9px] max-w-[120px] truncate cursor-pointer ${isLight ? 'text-red-500' : 'text-red-400'}`}
                  title={cvBuildError}
                  onClick={clearCVBuildError}
                >
                  ⚠ {cvBuildError}
                </span>
              )}
            </div>
          )}

          {/* R-001/R-002: セッション共有ボタン */}
          {activeSession ? (
            <div className="flex items-center gap-1">
              <button
                onClick={() => {
                  if (tunnelPending) return  // 公開URL取得中はモーダルを開かない
                  setShowSessionModal(true)
                }}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                  tunnelPending
                    ? isLight
                      ? 'bg-amber-100 text-amber-600 cursor-wait'
                      : 'bg-amber-900/40 text-amber-400 cursor-wait'
                    : isLight
                      ? 'bg-blue-100 text-blue-700 hover:bg-blue-200'
                      : 'bg-blue-900/40 text-blue-300 hover:bg-blue-800/60'
                }`}
                title={tunnelPending ? 'トンネルURL取得中... しばらくお待ちください' : 'クリックしてQRコード・URLを表示'}
              >
                <Share2 size={12} />
                <span className="font-mono font-bold">
                  {tunnelPending ? '...' : activeSession.session_code}
                </span>
              </button>
              {/* トンネル起動/停止ボタン */}
              {tunnelStatus?.data?.available !== false && (
                <button
                  onClick={() => tunnelToggle.mutate()}
                  disabled={tunnelToggle.isPending}
                  title={tunnelStatus?.data?.running ? 'トンネル停止' : 'トンネル起動（HTTPS外部公開）'}
                  className={`flex items-center gap-1 px-1.5 py-1 rounded text-xs transition-colors disabled:opacity-50 ${
                    tunnelStatus?.data?.running
                      ? isLight
                        ? 'bg-green-100 text-green-700 hover:bg-red-100 hover:text-red-600'
                        : 'bg-green-800/60 text-green-300 hover:bg-red-900/50 hover:text-red-300'
                      : isLight
                        ? 'bg-gray-200 text-gray-500 hover:text-gray-700'
                        : 'bg-gray-700 text-gray-500 hover:text-gray-300'
                  }`}
                >
                  <Globe size={12} className={tunnelStatus?.data?.running ? 'animate-pulse' : ''} />
                  {tunnelPending ? '取得中...' : tunnelStatus?.data?.running ? '稼働中' : ''}
                </button>
              )}
              {/* トンネルエラー表示（タイムアウト・認証失敗など） */}
              {tunnelLastError && !tunnelStatus?.data?.running && (
                <span
                  className={`text-[9px] max-w-[180px] truncate cursor-help ${isLight ? 'text-red-500' : 'text-red-400'}`}
                  title={tunnelLastError}
                >
                  ⚠ {tunnelLastError.replace('[ngrok] ', '')}
                </span>
              )}
            </div>
          ) : (
            <button
              onClick={handleCreateOrGetSession}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors ${
                isLight
                  ? 'bg-gray-100 text-gray-500 hover:text-gray-800'
                  : 'bg-gray-700 text-gray-400 hover:text-white'
              }`}
              title={t('sharing.create_session')}
            >
              <Share2 size={12} />
              {t('sharing.share')}
            </button>
          )}
          {/* デバイス管理ボタン */}
          {activeSession && (
            <button
              onClick={() => setShowDeviceManager(true)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                isLight ? 'bg-gray-200 text-gray-500 hover:text-gray-800' : 'bg-gray-700 text-gray-400 hover:text-white'
              }`}
              title={t('lan_session.open_device_manager')}
            >
              <Monitor size={12} />
            </button>
          )}
          {/* リモートヘルスバナー */}
          {activeSession && remoteHealth && (
            <div
              className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] cursor-pointer ${
                isLight ? 'bg-gray-200 text-gray-700' : 'bg-black/30 text-gray-300'
              }`}
              onClick={() => setShowDeviceManager(true)}
              title="リモート接続状態（クリックでデバイス管理を開く）"
            >
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                remoteHealth.wsConnected ? 'bg-green-500' : 'bg-amber-400 animate-pulse'
              }`} />
              {/* トンネルプロバイダー名 */}
              {tunnelStatus?.data?.running && tunnelStatus.data.active_provider && (
                <span className={`font-medium ${
                  tunnelStatus.data.active_provider === 'ngrok'
                    ? isLight ? 'text-orange-600' : 'text-orange-400'
                    : isLight ? 'text-cyan-600' : 'text-cyan-400'
                }`}>
                  {tunnelStatus.data.active_provider === 'ngrok' ? 'ngrok' : 'CF'}
                </span>
              )}
              {tunnelStatus?.data?.running === false && (
                <span className={isLight ? 'text-gray-500' : 'text-gray-400'}>LAN</span>
              )}
              <span className={
                remoteHealth.wsConnected
                  ? isLight ? 'text-green-700' : 'text-green-400'
                  : isLight ? 'text-amber-600' : 'text-amber-400'
              }>
                {remoteHealth.wsConnected ? '接続' : '再接続中'}
              </span>
              {remoteHealth.connectionState === 'connected' && (
                <span className={`ml-1 ${isLight ? 'text-red-600' : 'text-red-400'}`}>● LIVE</span>
              )}
              {remoteHealth.turnInUse === true && (
                <span className={`ml-1 ${isLight ? 'text-blue-600' : 'text-blue-400'}`}>TURN</span>
              )}
            </div>
          )}
          <div className="w-24 h-1.5 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all"
              style={{ width: `${(match?.annotation_progress ?? 0) * 100}%` }}
            />
          </div>
          <span>{Math.round((match?.annotation_progress ?? 0) * 100)}%</span>
        </div>

        {/* モバイル: 進捗 + メニューボタン */}
        <div className="flex md:hidden items-center gap-2 shrink-0">
          {store.pendingSaveCount > 0 && (
            <span className="text-yellow-400 font-medium text-[10px]">
              {store.pendingSaveCount}
            </span>
          )}
          <div className="w-12 h-1.5 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all"
              style={{ width: `${(match?.annotation_progress ?? 0) * 100}%` }}
            />
          </div>
          <span className="text-[10px] text-gray-400">{Math.round((match?.annotation_progress ?? 0) * 100)}%</span>
          <button
            onClick={() => setShowMobileMenu((v) => !v)}
            className="p-1.5 rounded text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
          >
            <MoreVertical size={18} />
          </button>
        </div>
      </div>

      {/* モバイル: オーバーフローメニュー */}
      {isMobile && showMobileMenu && (
        <div
          className="fixed inset-0 z-50 bg-black/50"
          onClick={() => setShowMobileMenu(false)}
        >
          <div
            className="absolute top-12 right-2 w-56 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 途中終了 */}
            <button
              onClick={() => { setShowExceptionDialog(true); setShowMobileMenu(false) }}
              className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-red-400 hover:bg-gray-700"
            >
              <OctagonX size={14} />
              {t('exception.title')}
            </button>
            {/* 試合中モード */}
            <button
              onClick={() => { toggleMatchDayMode(); setShowMobileMenu(false) }}
              className={clsx(
                'w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-gray-700',
                isMatchDayMode ? 'text-yellow-400' : 'text-gray-300'
              )}
            >
              <Keyboard size={14} />
              {t('annotator.match_day_mode')}
            </button>
            {/* セッション共有 */}
            <button
              onClick={() => {
                if (activeSession) setShowSessionModal(true)
                else handleCreateOrGetSession()
                setShowMobileMenu(false)
              }}
              className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-300 hover:bg-gray-700"
            >
              <Share2 size={14} />
              {activeSession ? activeSession.session_code : t('sharing.share')}
            </button>
            {/* 暫定相手情報 */}
            {match?.player_b?.needs_review && (
              <button
                onClick={() => { setShowInMatchPanel((v) => !v); setShowMobileMenu(false) }}
                className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-orange-300 hover:bg-gray-700"
              >
                <ClipboardEdit size={14} />
                {t('in_match_panel.opponent_info')}
              </button>
            )}
            {/* エラー表示 */}
            {store.saveErrors.length > 0 && (
              <button
                onClick={() => { store.clearSaveErrors(); setShowMobileMenu(false) }}
                className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-red-400 hover:bg-gray-700"
              >
                {t('annotator.save_error_title')} {store.saveErrors.length}件
              </button>
            )}
          </div>
        </div>
      )}

      {/* T6: レビュー待ちラリーパネル */}
      {reviewQueueOpen && (
        <div className="bg-amber-900/20 border-b border-amber-700/40 px-4 py-2 shrink-0">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-medium text-amber-300 flex items-center gap-1.5">
              <Clock size={11} />
              {t('review_later.queue_title')}
            </span>
            <button
              onClick={() => setReviewQueueOpen(false)}
              className="text-gray-500 hover:text-gray-300 text-xs px-1"
            >
              {t('review_later.queue_close')}
            </button>
          </div>
          {(reviewBookmarksData?.length ?? 0) === 0 ? (
            <p className="text-xs text-gray-500">{t('review_later.queue_empty')}</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {reviewBookmarksData!.map((bm) => (
                <button
                  key={bm.id}
                  onClick={() => {
                    if (bm.video_timestamp_sec != null && videoRef.current) {
                      videoRef.current.currentTime = bm.video_timestamp_sec
                    }
                    setReviewQueueOpen(false)
                  }}
                  className="px-2 py-0.5 bg-amber-800/40 hover:bg-amber-700/60 text-amber-200 rounded text-xs border border-amber-700/30"
                >
                  ラリー #{bm.rally_id ?? '?'}
                  {bm.video_timestamp_sec != null && (
                    <span className="ml-1 opacity-60 text-[10px]">{Math.floor(bm.video_timestamp_sec / 60)}:{String(Math.floor(bm.video_timestamp_sec % 60)).padStart(2, '0')}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* CV要確認ラリーキュー */}
      {cvReviewQueueOpen && (
        <div className={`px-4 py-2 shrink-0 border-b ${
          isLight ? 'bg-amber-50 border-amber-200' : 'bg-amber-900/20 border-amber-700/40'
        }`}>
          <CVReviewQueuePanel
            items={cvReviewQueue}
            loading={cvReviewQueueLoading}
            candidatesData={candidatesData}
            onMarkCompleted={markReviewCompleted}
            onJumpToRally={(_rallyId, _rallyNum) => {
              // ラリーへのジャンプは動画タイムスタンプが必要 — 将来拡張
            }}
          />
        </div>
      )}

      {/* メインレイアウト */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左: 動画エリア — 試合中モード時/モバイル時は非表示 */}
        <div
          ref={leftPanelRef}
          className={clsx('flex flex-col p-3 gap-2 overflow-y-auto shrink-0', isMobile && 'hidden')}
          style={
            isMatchDayMode
              ? { display: 'none' }
              : leftPanelWidth != null
                ? { width: leftPanelWidth }
                : { width: videoSourceMode === 'none' ? 280 : '60%' }
          }
        >
          {(() => {
            // 別モニタ表示中はメイン側を非表示（video-only ウィンドウで再生中）
            if (videoSourceMode === 'none') {
              return (
                <div className="flex items-center justify-center bg-gray-900 rounded text-gray-500 text-xs border border-dashed border-gray-700 py-6 text-center">
                  別モニタで再生中
                </div>
              )
            }

            // 動画ソース決定（旧形式の Windows パスを normalizeVideoPath で変換）
            const rawSrc = match?.video_local_path || match?.video_url || ''
            const videoSrc = normalizeVideoPath(rawSrc)
            const streamingSiteName = videoSrc ? detectStreamingSite(videoSrc) : null

            // 中継ブラウザモード: DeviceManagerのWebRTCストリームまたはローカルカメラを表示
            if (videoSourceMode === 'webview') {
              if (localCamStream) {
                return (
                  <div className="relative w-full rounded overflow-hidden bg-black aspect-video">
                    <video
                      ref={localCamVideoRef}
                      autoPlay
                      playsInline
                      muted
                      className="w-full h-full object-contain"
                    />
                    <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-green-700 text-white text-xs px-2 py-0.5 rounded-full">
                      <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                      PCカメラ使用中
                    </div>
                  </div>
                )
              }
              if (remoteStream) {
                return (
                  <div className="relative w-full rounded overflow-hidden bg-black aspect-video">
                    <video
                      ref={remoteStreamVideoRef}
                      autoPlay
                      playsInline
                      muted
                      className="w-full h-full object-contain"
                    />
                    <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-red-600 text-white text-xs px-2 py-0.5 rounded-full">
                      <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                      iOSカメラ受信中
                    </div>
                  </div>
                )
              }
              return (
                <div className="flex items-center justify-center bg-gray-800 rounded text-gray-400 text-sm border-2 border-dashed border-gray-600 py-6 px-4 text-center gap-2 flex-col">
                  <span>カメラ映像待機中...</span>
                  <span className="text-xs text-gray-600">デバイス管理でカメラを起動してください</span>
                </div>
              )
            }

            if (!videoSrc) {
              return (
                <div className="flex items-center justify-center bg-gray-800 rounded text-gray-500 text-sm border-2 border-dashed border-gray-700 py-6 px-4 text-center gap-2 flex-col">
                  <span>動画が設定されていません</span>
                  <span className="text-xs text-gray-600">下の「ファイルを開く」またはURLを設定してください</span>
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
              <AnnotatorVideoPane
                videoRef={videoRef}
                videoContainerRef={videoContainerRef}
                src={videoSrc}
                playbackRate={playbackRate}
                onPlaybackRateChange={setPlaybackRate}
                yoloFrames={yoloFrames}
                yoloOverlayVisible={yoloOverlayVisible}
                currentVideoSec={currentVideoSec}
                shuttleFrames={shuttleFrames}
                shuttleOverlayVisible={shuttleOverlayVisible}
                courtGridMatchId={matchId ?? undefined}
                courtGridVisible={courtGridVisible}
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
            {/* P2: 映像モードセレクター */}
            <div className="mt-1.5 flex gap-1">
              {(
                [
                  { mode: 'local' as VideoSourceMode, label: t('video_source.mode_local') },
                  { mode: 'webview' as VideoSourceMode, label: t('video_source.mode_webview') },
                  { mode: 'none' as VideoSourceMode, label: t('video_source.mode_none') },
                ] as const
              ).map(({ mode, label }) => (
                <button
                  key={mode}
                  onClick={() => setVideoSourceMode(mode)}
                  className={clsx(
                    'flex-1 py-0.5 rounded text-[10px] border transition-colors',
                    videoSourceMode === mode
                      ? 'bg-blue-600 border-blue-500 text-white'
                      : 'bg-gray-700 border-gray-600 text-gray-400 hover:bg-gray-600'
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* ショートカットガイド */}
          <div className="bg-gray-800 rounded p-3 text-gray-300 shrink-0">
            <div className="font-semibold text-gray-200 mb-2 text-sm">キーボードショートカット</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Space</kbd> 再生/停止</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">←/→</kbd> 1フレーム</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Shift+←/→</kbd> 10秒</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Enter</kbd> ラリー開始/終了</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">N/C/P…G</kbd> ショット入力</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Q/W/E</kbd> BH/RH/NET属性</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Ctrl+Z</kbd> 戻す</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Esc</kbd> キャンセル</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">1–6</kbd> エンドタイプ</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">A/B</kbd> 勝者確定</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">K</kbd> 見逃しラリー</span>
              <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Backspace</kbd> 落点キャンセル</span>
            </div>
          </div>

          {/* テンキーガイド */}
          <div className="bg-gray-800 rounded p-3 text-gray-300 shrink-0">
            <div className="font-semibold text-gray-200 mb-2 text-sm">落点入力（land_zone中のみ）</div>
            <div className="flex gap-4 items-start">
              {/* ゾーンキー */}
              <div className="space-y-1 flex-1">
                {/* テンキー落点（主） */}
                <div className="text-[10px] text-gray-300 mb-0.5 font-medium">テンキー（推奨）</div>
                <div className="grid grid-cols-3 gap-1">
                  {[
                    { k: '7', zone: 'BL' }, { k: '8', zone: 'BC' }, { k: '9', zone: 'BR' },
                    { k: '4', zone: 'ML' }, { k: '5', zone: 'MC' }, { k: '6', zone: 'MR' },
                    { k: '1', zone: 'NL' }, { k: '2', zone: 'NC' }, { k: '3', zone: 'NR' },
                  ].map(({ k, zone }) => (
                    <div key={k} className="text-center">
                      <kbd className="block bg-gray-600 border border-gray-500 text-white rounded px-1.5 py-0.5 text-xs font-mono">{k}</kbd>
                      <span className="text-[11px] text-gray-300 font-medium">{zone}</span>
                    </div>
                  ))}
                </div>
                <div className="text-[11px] text-gray-500 mt-0.5">0/Num0 = スキップ　Esc/BS = キャンセル</div>
                {/* 文字キー落点（副・ノートPC向け） */}
                <div className="text-[10px] text-gray-500 mt-1.5 mb-0.5">文字キー（ノートPC向け）</div>
                <div className="grid grid-cols-3 gap-1">
                  {[
                    { k: 'U', zone: 'BL' }, { k: 'I', zone: 'BC' }, { k: 'O', zone: 'BR' },
                    { k: 'J', zone: 'ML' }, { k: 'K', zone: 'MC' }, { k: 'L', zone: 'MR' },
                    { k: 'M', zone: 'NL' }, { k: ',', zone: 'NC' }, { k: '.', zone: 'NR' },
                  ].map(({ k, zone }) => (
                    <div key={k} className="text-center">
                      <kbd className="block bg-gray-600 text-white rounded px-1.5 py-0.5 text-xs font-mono">{k}</kbd>
                      <span className="text-[11px] text-gray-400 font-medium">{zone}</span>
                    </div>
                  ))}
                </div>
                <div className="text-[11px] text-gray-500 mt-0.5">
                  Shift+U/I/O=OB後 Shift+J/L=OB側 -/=/\=NET
                </div>
              </div>
              {/* コートチェンジ情報 + 先サーブ/視点変更 */}
              <div className="flex-1 border-l border-gray-700 pl-3 space-y-1.5">
                <p className="text-xs text-gray-400 font-medium">コートチェンジ</p>
                {[1, 2, 3].map((sn) => {
                  const isCurrent = store.currentSetNum === sn
                  const aPos = computePlayerASide(playerAStart, sn, sn === store.currentSetNum ? store.scoreA : 0, sn === store.currentSetNum ? store.scoreB : 0)
                  return (
                    <div key={sn} className={`text-xs flex items-center gap-1.5 ${isCurrent ? 'text-yellow-300 font-medium' : 'text-gray-500'}`}>
                      <span className={`w-2 h-2 rounded-full inline-block shrink-0 ${isCurrent ? 'bg-yellow-400' : 'bg-gray-700'}`} />
                      <span>Set {sn}: A={aPos === 'top' ? '↑上' : '↓下'}</span>
                      {sn === 3 && <span className="text-gray-600 text-[10px]">(11pt↔)</span>}
                    </div>
                  )
                })}
                <p className="text-xs text-gray-500 mt-1"><span className="text-blue-400">■</span> 青=A　<span className="text-orange-400">■</span> 橙=B</p>

                {/* 先サーブ変更 */}
                <div className="pt-1.5 border-t border-gray-700 space-y-1">
                  <p className="text-xs text-gray-400 font-medium">先サーブ</p>
                  <div className="flex gap-1">
                    {([
                      { v: 'player_a' as const, label: 'A側' },
                      { v: 'player_b' as const, label: 'B側' },
                    ]).map(({ v, label }) => (
                      <button
                        key={v}
                        onClick={() => handleInitialServerChange(v)}
                        className={`flex-1 py-0.5 rounded text-xs border ${
                          match?.initial_server === v
                            ? 'bg-blue-600 border-blue-500 text-white'
                            : 'bg-gray-700 border-gray-600 text-gray-400 hover:bg-gray-600'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  {/* 視点変更 */}
                  <p className="text-xs text-gray-400 font-medium pt-0.5">アナリスト視点</p>
                  <div className="flex gap-1">
                    {([
                      { v: 'bottom' as const, label: '⬇ 手前' },
                      { v: 'top'    as const, label: '⬆ 奥側' },
                    ]).map(({ v, label }) => (
                      <button
                        key={v}
                        onClick={() => handleViewpointChange(v)}
                        className={`flex-1 py-0.5 rounded text-xs border ${
                          playerAStart === v
                            ? 'bg-blue-600 border-blue-500 text-white'
                            : 'bg-gray-700 border-gray-600 text-gray-400 hover:bg-gray-600'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ドラッグリサイズハンドル（デスクトップ・非試合中モード時のみ） */}
        {!isMatchDayMode && !isMobile && (
          <div
            onMouseDown={handleResizeDragStart}
            className="w-1 shrink-0 cursor-col-resize bg-gray-700 hover:bg-gray-500 transition-colors active:bg-gray-400"
            title="ドラッグで幅を変更"
          />
        )}

        {/* 右: 入力パネル — 試合中モード時/モバイル時はフルスクリーン */}
        <div className={clsx(
          'flex flex-col overflow-y-auto',
          (isMatchDayMode || isMobile) ? 'flex-1' : 'w-[40%] border-l border-gray-700'
        )}>
          {/* ステップインジケーター */}
          <div
            className={clsx(
              'flex items-center justify-between px-3 py-2 text-xs font-medium border-b border-gray-700 shrink-0',
              store.inputStep === 'idle' ? 'text-gray-400 bg-gray-800' : 'text-blue-300 bg-blue-900/30'
            )}
          >
            <span>{initialized ? stepLabel : '読み込み中…'}</span>
            {isMatchDayMode && (
              <button
                onClick={() => setShowLegendOverlay((v) => !v)}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-xs text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
                title="キーボードショートカット凡例"
              >
                <Keyboard size={12} />
              </button>
            )}
          </div>

          {/* 試合中モード: キーボード凡例オーバーレイ */}
          {isMatchDayMode && showLegendOverlay && (
            <div
              className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center"
              onClick={() => setShowLegendOverlay(false)}
            >
              <div
                className="bg-gray-900 border border-gray-700 rounded-lg p-5 max-w-lg w-full mx-4 space-y-4"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-semibold text-gray-200">キーボードショートカット</span>
                  <button
                    onClick={() => setShowLegendOverlay(false)}
                    className="text-gray-500 hover:text-white text-lg leading-none"
                  >
                    ✕
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-300">
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Space</kbd> 再生/停止</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">←/→</kbd> 1フレーム</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Shift+←/→</kbd> 10秒</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Enter</kbd> ラリー開始/終了</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">N/C/P…G</kbd> ショット入力</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Q/W/E</kbd> BH/RH/NET属性</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Ctrl+Z</kbd> 戻す</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Esc</kbd> キャンセル</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">1–6</kbd> エンドタイプ</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">A/B</kbd> 勝者確定</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">K</kbd> 見逃しラリー</span>
                  <span><kbd className="bg-gray-600 text-white px-1.5 py-0.5 rounded text-xs font-mono">Backspace</kbd> 落点キャンセル</span>
                </div>
                <div className="border-t border-gray-700 pt-3">
                  <div className="font-semibold text-gray-200 mb-2 text-xs">落点入力テンキー（land_zone中）</div>
                  <div className="flex gap-4 items-start">
                    <div className="space-y-1 flex-1">
                      <div className="text-[10px] text-gray-400 mb-0.5">テンキー（推奨）</div>
                      <div className="grid grid-cols-3 gap-1">
                        {[
                          { k: '7', zone: 'BL' }, { k: '8', zone: 'BC' }, { k: '9', zone: 'BR' },
                          { k: '4', zone: 'ML' }, { k: '5', zone: 'MC' }, { k: '6', zone: 'MR' },
                          { k: '1', zone: 'NL' }, { k: '2', zone: 'NC' }, { k: '3', zone: 'NR' },
                        ].map(({ k, zone }) => (
                          <div key={k} className="text-center">
                            <kbd className="block bg-gray-600 border border-gray-500 text-white rounded px-1.5 py-0.5 text-xs font-mono">{k}</kbd>
                            <span className="text-[11px] text-gray-300 font-medium">{zone}</span>
                          </div>
                        ))}
                      </div>
                      <div className="text-[11px] text-gray-500 mt-0.5">0/Num0 = スキップ　Esc/BS = キャンセル</div>
                      <div className="text-[10px] text-gray-500 mt-1.5 mb-0.5">文字キー（ノートPC向け）</div>
                      <div className="grid grid-cols-3 gap-1">
                        {[
                          { k: 'U', zone: 'BL' }, { k: 'I', zone: 'BC' }, { k: 'O', zone: 'BR' },
                          { k: 'J', zone: 'ML' }, { k: 'K', zone: 'MC' }, { k: 'L', zone: 'MR' },
                          { k: 'M', zone: 'NL' }, { k: ',', zone: 'NC' }, { k: '.', zone: 'NR' },
                        ].map(({ k, zone }) => (
                          <div key={k} className="text-center">
                            <kbd className="block bg-gray-600 text-white rounded px-1.5 py-0.5 text-xs font-mono">{k}</kbd>
                            <span className="text-[11px] text-gray-400 font-medium">{zone}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="flex-1 border-l border-gray-700 pl-3 space-y-1.5">
                      <p className="text-xs text-gray-400 font-medium">コートチェンジ</p>
                      {[1, 2, 3].map((sn) => {
                        const isCurrent = store.currentSetNum === sn
                        const aPos = computePlayerASide(playerAStart, sn, sn === store.currentSetNum ? store.scoreA : 0, sn === store.currentSetNum ? store.scoreB : 0)
                        return (
                          <div key={sn} className={`text-xs flex items-center gap-1.5 ${isCurrent ? 'text-yellow-300 font-medium' : 'text-gray-500'}`}>
                            <span className={`w-2 h-2 rounded-full inline-block shrink-0 ${isCurrent ? 'bg-yellow-400' : 'bg-gray-700'}`} />
                            <span>Set {sn}: A={aPos === 'top' ? '↑上' : '↓下'}</span>
                            {sn === 3 && <span className="text-gray-600 text-[10px]">(11pt↔)</span>}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
                <p className="text-[10px] text-gray-600 text-center">背景クリックで閉じる</p>
              </div>
            </div>
          )}

          {/* モバイル: スコアを sticky 固定 */}
          {isMobile && (
            <div className="sticky top-0 z-10 bg-gray-900 px-3 pt-2 pb-1 shrink-0">
              <div className="bg-gray-800 rounded-lg p-3 flex items-center justify-between">
                <div className="text-center min-w-[80px]">
                  <div className="text-xs text-gray-400 truncate">{match?.player_a?.name ?? 'A'}</div>
                  <div className="text-4xl font-bold">{store.scoreA}</div>
                </div>
                <div className="text-center">
                  <div className="text-sm text-gray-400">Set {store.currentSetNum}</div>
                  <div className="text-xs text-gray-500">Rally {store.currentRallyNum}</div>
                  {store.isRallyActive && store.currentStrokes.length > 0 && (
                    <div className="text-[10px] text-blue-400 mt-0.5">
                      {store.currentStrokes.length} shots
                    </div>
                  )}
                </div>
                <div className="text-center min-w-[80px]">
                  <div className="text-xs text-gray-400 truncate">{match?.player_b?.name ?? 'B'}</div>
                  <div className="text-4xl font-bold">{store.scoreB}</div>
                </div>
              </div>
            </div>
          )}

          <div className="flex flex-col gap-3 p-3">
            {/* スコア表示（デスクトップのみ — モバイルは上の sticky に移動） */}
            {!isMobile && (
            <div className={clsx('bg-gray-800 rounded flex items-center justify-between shrink-0', useLargeTouch ? 'p-3' : 'p-2')}>
              <div className={clsx('text-center', useLargeTouch ? 'min-w-[80px]' : 'min-w-[60px]')}>
                <div className={clsx('text-gray-400 truncate', useLargeTouch ? 'text-xs' : 'text-[10px]')}>{match?.player_a?.name ?? 'A'}</div>
                <div className={clsx('font-bold', useLargeTouch ? 'text-4xl' : 'text-2xl')}>{store.scoreA}</div>
              </div>
              <div className="text-center text-xs text-gray-500">
                <div>Set {store.currentSetNum}</div>
                <div>Rally {store.currentRallyNum}</div>
                {/* P2: タイマー（none/webviewモード） */}
                {videoSourceMode !== 'local' && (
                  <div className="mt-1 flex flex-col items-center gap-0.5">
                    <div className={clsx(
                      'font-mono text-sm font-bold',
                      timer.isRunning ? 'text-green-400' : 'text-gray-400'
                    )}>
                      {timer.displayTime}
                    </div>
                    <div className="flex gap-1">
                      {!timer.isRunning ? (
                        <button onClick={timer.start} className="px-1.5 py-0.5 bg-green-700 hover:bg-green-600 text-white rounded text-[9px] flex items-center gap-0.5">
                          <Play size={8} />{t('timer.start')}
                        </button>
                      ) : (
                        <button onClick={timer.pause} className="px-1.5 py-0.5 bg-yellow-700 hover:bg-yellow-600 text-white rounded text-[9px] flex items-center gap-0.5">
                          <Pause size={8} />{t('timer.pause')}
                        </button>
                      )}
                      <button onClick={timer.reset} className="px-1.5 py-0.5 bg-gray-600 hover:bg-gray-500 text-gray-300 rounded text-[9px]">
                        {t('timer.reset')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
              <div className={clsx('text-center', useLargeTouch ? 'min-w-[80px]' : 'min-w-[60px]')}>
                <div className={clsx('text-gray-400 truncate', useLargeTouch ? 'text-xs' : 'text-[10px]')}>{match?.player_b?.name ?? 'B'}</div>
                <div className={clsx('font-bold', useLargeTouch ? 'text-4xl' : 'text-2xl')}>{store.scoreB}</div>
              </div>
            </div>
            )}

            {/* D-1: 自動保存ステータス（デスクトップのみ） */}
            <div className={clsx('flex items-center justify-between text-[10px] shrink-0 px-0.5', isMobile && 'hidden')}>
              {store.isRallyActive && store.currentStrokes.length > 0 ? (
                lastAutoSaveTime ? (
                  <span className="text-green-500">
                    ✓ 自動保存済 {new Date(lastAutoSaveTime).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                ) : (
                  <span className="text-yellow-500 animate-pulse">● 未保存</span>
                )
              ) : (
                <span className="text-gray-600">—</span>
              )}
              {/* D-3: 手動保存ボタン */}
              {store.isRallyActive && store.currentStrokes.length > 0 && autoSaveKey && (
                <button
                  onClick={() => {
                    const now = Date.now()
                    const data = {
                      setId: store.currentSetId,
                      rallyNum: store.currentRallyNum,
                      strokes: store.currentStrokes,
                      savedAt: now,
                    }
                    localStorage.setItem(autoSaveKey, JSON.stringify(data))
                    setLastAutoSaveTime(now)
                  }}
                  className="text-gray-500 hover:text-green-400 px-1"
                  title="今すぐ保存"
                >
                  💾 保存
                </button>
              )}
            </div>

            {/* プレイヤー切替 */}
            {/* G1: land_zone ステップ中は打者アイデンティティを固定（仕様 §5.3 Step C） */}
            {store.isRallyActive && (() => {
              const aPos = computePlayerASide(playerAStart, store.currentSetNum, store.scoreA, store.scoreB)
              const posLabel = (player: 'player_a' | 'player_b') => {
                const side = player === 'player_a' ? aPos : (aPos === 'top' ? 'bottom' : 'top')
                return side === 'top' ? '↑' : '↓'
              }
              // G1: landing 中はプレイヤー切替を無効化（打者アイデンティティ保護）
              const playerToggleDisabled = store.inputStep === 'land_zone'
              return (
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => !playerToggleDisabled && store.setPlayer('player_a')}
                    disabled={playerToggleDisabled}
                    title={match?.player_a?.team ? `所属: ${match.player_a.team}` : match?.player_a?.name ?? 'A'}
                    className={clsx(
                      'flex-1 rounded font-medium transition-colors',
                      useLargeTouch ? 'py-3 text-sm' : 'py-1.5 text-xs',
                      store.currentPlayer === 'player_a'
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-700 text-gray-400 hover:bg-gray-600',
                      playerToggleDisabled && 'opacity-40 cursor-not-allowed grayscale',
                    )}
                  >
                    <span className="opacity-60 mr-0.5">{posLabel('player_a')}</span>{match?.player_a?.name ?? 'A'}
                  </button>
                  <button
                    onClick={() => !playerToggleDisabled && store.togglePlayer()}
                    disabled={playerToggleDisabled}
                    className={clsx(
                      'rounded transition-colors',
                      useLargeTouch ? 'px-3 py-3' : 'px-2 py-1.5 text-xs',
                      playerToggleDisabled
                        ? 'bg-gray-800 text-gray-600 cursor-not-allowed opacity-40 grayscale'
                        : 'bg-gray-700 hover:bg-gray-600 text-gray-300',
                    )}
                    title={playerToggleDisabled ? '落点入力中は切替できません' : 'プレイヤー切替'}
                  >
                    <Users size={useLargeTouch ? 16 : 12} />
                  </button>
                  <button
                    onClick={() => !playerToggleDisabled && store.setPlayer('player_b')}
                    disabled={playerToggleDisabled}
                    title={match?.player_b?.team ? `所属: ${match.player_b.team}` : match?.player_b?.name ?? 'B'}
                    className={clsx(
                      'flex-1 rounded font-medium transition-colors',
                      useLargeTouch ? 'py-3 text-sm' : 'py-1.5 text-xs',
                      store.currentPlayer === 'player_b'
                        ? 'bg-orange-600 text-white'
                        : 'bg-gray-700 text-gray-400 hover:bg-gray-600',
                      playerToggleDisabled && 'opacity-40 cursor-not-allowed grayscale',
                    )}
                  >
                    <span className="opacity-60 mr-0.5">{posLabel('player_b')}</span>{match?.player_b?.name ?? 'B'}
                  </button>
                </div>
              )
            })()}

            {/* ラリー終了確認パネル */}
            {store.inputStep === 'rally_end' && (() => {
              const lastStroke = store.currentStrokes[store.currentStrokes.length - 1]
              const lastStriker = lastStroke?.player
              const suggestedWinner = getSuggestedWinner(pendingEndType, lastStriker)
              return (
                <div className={clsx('border border-yellow-700/50 bg-yellow-900/20 rounded shrink-0', useLargeTouch ? 'p-3' : 'p-2')}>
                  <div className={clsx('text-yellow-400 mb-2 font-medium', useLargeTouch ? 'text-sm' : 'text-xs')}>
                    ラリー終了 — エンドタイプ→勝者の順に選択
                    {!isMobile && lastStriker && (
                      <span className="ml-1 text-gray-500">
                        （最終打者: {lastStriker === 'player_a' ? match?.player_a?.name ?? 'A' : match?.player_b?.name ?? 'B'}）
                      </span>
                    )}
                  </div>

                  {/* 統一2ステップモデル: エンドタイプ選択（1–6キー）→ 勝者確定（A/Bキー） */}
                  <div className="space-y-2">
                    {/* Step 1: エンドタイプ選択 */}
                    <div className={clsx('grid gap-1', useLargeTouch ? 'grid-cols-3' : 'grid-cols-3')}>
                      {END_TYPES.map(({ value, label: endLabel }, idx) => (
                        <button
                          key={value}
                          onClick={() => setPendingEndType((prev) => prev === value ? null : value)}
                          className={clsx(
                            'px-1 rounded text-xs font-medium transition-colors text-center',
                            useLargeTouch ? 'py-3' : 'py-1.5',
                            pendingEndType === value
                              ? 'bg-yellow-600 text-white border border-yellow-400'
                              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                          )}
                          title={`${idx + 1}: ${endLabel}`}
                        >
                          {!isMobile && <span className="block text-[9px] opacity-60 font-mono">{idx + 1}</span>}
                          <span className="block leading-tight">{endLabel}</span>
                        </button>
                      ))}
                    </div>

                    {/* Step 2: 勝者確定 */}
                    <div className="grid grid-cols-2 gap-2">
                      {(
                        [
                          { winner: 'player_a' as const, label: match?.player_a?.name ?? 'A', color: 'blue', key: 'A' },
                          { winner: 'player_b' as const, label: match?.player_b?.name ?? 'B', color: 'orange', key: 'B' },
                        ] as const
                      ).map(({ winner, label, color, key }) => {
                        const blocked = isWinnerBlocked(winner, pendingEndType, lastStriker)
                        const suggested = suggestedWinner === winner
                        const dimmed = !pendingEndType || blocked || (suggestedWinner !== null && !suggested)
                        return (
                          <button
                            key={winner}
                            onClick={() => !blocked && pendingEndType && handleConfirmRally(winner, pendingEndType)}
                            disabled={!pendingEndType || blocked}
                            className={clsx(
                              'relative rounded text-sm font-bold transition-colors',
                              useLargeTouch ? 'py-5' : 'py-2.5',
                              !pendingEndType || blocked
                                ? 'bg-gray-700 text-gray-500 cursor-not-allowed opacity-40'
                                : suggested
                                  ? color === 'blue'
                                    ? 'bg-blue-500 hover:bg-blue-400 text-white ring-2 ring-blue-300'
                                    : 'bg-orange-500 hover:bg-orange-400 text-white ring-2 ring-orange-300'
                                  : dimmed
                                    ? color === 'blue'
                                      ? 'bg-blue-900/40 hover:bg-blue-800/60 text-blue-300'
                                      : 'bg-orange-900/40 hover:bg-orange-800/60 text-orange-300'
                                    : color === 'blue'
                                      ? 'bg-blue-600 hover:bg-blue-500 text-white'
                                      : 'bg-orange-600 hover:bg-orange-500 text-white'
                            )}
                          >
                            {!isMobile && <span className="absolute top-0.5 right-1.5 text-[9px] font-mono opacity-60">{key}</span>}
                            {label} 得点
                            {suggested && pendingEndType && (
                              <span className="block text-[9px] opacity-70">← 推定</span>
                            )}
                          </button>
                        )
                      })}
                    </div>

                    {!pendingEndType && (
                      <p className={clsx('text-gray-500 text-center', useLargeTouch ? 'text-xs' : 'text-[10px]')}>
                        {isMobile ? 'エンドタイプを選択' : '1–6キーまたはボタンでエンドタイプを選択'}
                      </p>
                    )}
                    {pendingEndType && suggestedWinner && (
                      <p className={clsx('text-gray-300 text-center', useLargeTouch ? 'text-xs' : 'text-[10px]')}>
                        推定: {suggestedWinner === 'player_a' ? match?.player_a?.name ?? 'A' : match?.player_b?.name ?? 'B'} 得点 — {isMobile ? 'タップで確定' : 'A/Bキーまたはボタンで確定'}
                      </p>
                    )}
                  </div>

                  {/* T4: Soft warning — land_zone 未入力ストロークがある場合 */}
                  {store.currentStrokes.some((s) => !s.land_zone) && (
                    <p className="text-[10px] text-yellow-700/80 text-center py-0.5">
                      着地点が未入力のストロークがあります（後から補完可能）
                    </p>
                  )}

                  <button
                    onClick={() => store.cancelRallyEnd()}
                    className={clsx(
                      'w-full mt-2 bg-gray-700 hover:bg-gray-600 text-gray-400 rounded',
                      useLargeTouch ? 'py-2.5 text-sm' : 'py-1 text-xs'
                    )}
                  >
                    ← キャンセル {!isMobile && '(Esc)'}
                  </button>
                </div>
              )
            })()}

            {/* ダブルス打者パネル — 4選手を常時表示し直接選択できる */}
            {store.isDoubles && store.inputStep !== 'rally_end' && match && (() => {
              const nameA  = match.player_a?.name  ?? 'A'
              const namePA = match.partner_a?.name ?? '—'
              const nameB  = match.player_b?.name  ?? 'B'
              const namePB = match.partner_b?.name ?? '—'

              const isActiveA = store.currentPlayer === 'player_a'

              const btnCls = (key: string) => {
                const selected = store.currentHitter === key
                const teamA = key === 'player_a' || key === 'partner_a'
                const activeTeam = teamA ? isActiveA : !isActiveA
                return clsx(
                  'flex-1 rounded text-xs border transition-colors truncate',
                  useLargeTouch ? 'py-2' : 'py-1',
                  selected
                    ? teamA
                      ? isLight ? 'bg-blue-600 border-blue-400 text-white font-semibold' : 'bg-blue-600 border-blue-400 text-white font-semibold'
                      : isLight ? 'bg-orange-500 border-orange-400 text-white font-semibold' : 'bg-orange-600 border-orange-400 text-white font-semibold'
                    : activeTeam
                      ? isLight ? 'bg-gray-200 border-gray-400 text-gray-800 hover:bg-gray-300' : 'bg-gray-700 border-gray-500 text-gray-200 hover:bg-gray-600'
                      : isLight ? 'bg-gray-100 border-gray-200 text-gray-400 hover:bg-gray-200' : 'bg-gray-800 border-gray-700 text-gray-500 hover:bg-gray-700'
                )
              }

              return (
                <div className="flex flex-col gap-0.5 px-1">
                  {/* チームラベル */}
                  <div className="flex items-center text-[9px]">
                    <span className={clsx('flex-1 text-center', isActiveA
                      ? isLight ? 'text-blue-600 font-semibold' : 'text-blue-400 font-semibold'
                      : isLight ? 'text-gray-400' : 'text-gray-600')}>
                      自チーム
                    </span>
                    <span className={clsx('mx-1', isLight ? 'text-gray-300' : 'text-gray-600')}>打者</span>
                    <span className={clsx('flex-1 text-center', !isActiveA
                      ? isLight ? 'text-orange-600 font-semibold' : 'text-orange-400 font-semibold'
                      : isLight ? 'text-gray-400' : 'text-gray-600')}>
                      相手チーム
                    </span>
                  </div>
                  {/* 4選手ボタン行 */}
                  <div className="flex items-center gap-1">
                    <button onClick={() => store.setHitter('player_a')}  className={btnCls('player_a')}>{nameA}</button>
                    <button onClick={() => store.setHitter('partner_a')} className={btnCls('partner_a')}>{namePA}</button>
                    <div className={clsx('w-px self-stretch mx-0.5', isLight ? 'bg-gray-300' : 'bg-gray-600')} />
                    <button onClick={() => store.setHitter('partner_b')} className={btnCls('partner_b')}>{namePB}</button>
                    <button onClick={() => store.setHitter('player_b')}  className={btnCls('player_b')}>{nameB}</button>
                  </div>
                </div>
              )
            })()}

            {/* ショット種別パネル（ラリー中 & ショット選択ステップのみ） */}
            {store.isRallyActive && store.inputStep === 'idle' && (
              <>
                <ShotTypePanel
                  selected={store.pendingStroke.shot_type ?? null}
                  onSelect={(st: ShotType) => {
                    store.inputShotType(st, getTimestamp())
                  }}
                  disabled={false}
                  strokeNum={store.currentStrokeNum}
                  lastShotType={
                    store.currentStrokes.length > 0
                      ? store.currentStrokes[store.currentStrokes.length - 1].shot_type
                      : null
                  }
                  isMatchDayMode={useLargeTouch}
                />
                {/* T3: Basic モードで「ここまでで保存可能」ヒント */}
                {isBasicMode && (
                  <p className="text-[10px] text-gray-500 text-center px-1">
                    {t('annotation_mode.saveable_hint')}
                  </p>
                )}
              </>
            )}

            {/* 落点選択（land_zone ステップ時） */}
            {store.inputStep === 'land_zone' && (
              <div className="flex flex-col gap-1 shrink-0">
                <div className={clsx('text-center', useLargeTouch ? 'text-sm' : 'text-xs')}>
                  {/* player_bの返球は自コートに着地 → 下半分をクリック可能にする */}
                  {store.currentPlayer === 'player_b' ? (
                    <span className="text-orange-400 font-medium">
                      着地ゾーン（自コート↓） — {isMobile ? 'タップで選択' : 'テンキー1–9 or クリック'}
                    </span>
                  ) : (
                    <span className="text-blue-400 font-medium">
                      {t('annotator.land_zone')} — {isMobile ? 'タップで選択' : 'テンキー1–9 or クリック'}
                    </span>
                  )}
                </div>
                <div className="flex justify-center">
                  <CourtDiagram
                    mode={store.currentPlayer === 'player_b' ? 'hit' : 'land'}
                    selectedZone={store.pendingStroke.land_zone ?? null}
                    onZoneSelect={(zone: LandZone) => store.selectLandZone(zone)}
                    interactive={true}
                    showOOB={true}
                    label={undefined}
                    maxWidth={isMobile ? 340 : 200}
                    playerSides={(() => {
                      const aTop = computePlayerASide(playerAStart, store.currentSetNum, store.scoreA, store.scoreB) === 'top'
                      return { top: aTop ? 'a' : 'b', bottom: aTop ? 'b' : 'a' }
                    })()}
                    activePlayer={store.currentPlayer === 'player_a' ? 'a' : 'b'}
                  />
                </div>
                <button
                  onClick={() => store.skipLandZone()}
                  className={clsx(
                    'text-gray-500 hover:text-gray-300 text-center',
                    useLargeTouch ? 'py-2 text-sm' : 'py-0.5 text-xs'
                  )}
                >
                  {t('annotator.land_zone_skip')}
                  {isBasicMode && (
                    <span className="ml-1 text-[10px] text-gray-600">（後から補完可能）</span>
                  )}
                </button>
                {/* 打点（自動推定済み） */}
                {store.pendingStroke.hit_zone && (
                  <div className="text-[10px] text-gray-500 text-center">
                    {t('annotator.hit_zone')} (自動): {store.pendingStroke.hit_zone}
                  </div>
                )}
              </div>
            )}

            {/* 属性パネル（ラリー中 & idle/land_zone） */}
            {/* G1: land_zone ステップ中は属性パネルを disabled（落点確定を優先） */}
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
                disabled={store.inputStep === 'land_zone'}
              />
            )}

            {/* ラリー開始ボタン + 見逃しラリーボタン（待機中かつラリー未開始） */}
            {initialized && !store.isRallyActive && store.inputStep === 'idle' && (
              <div className={clsx('flex gap-1.5', isMobile && 'flex-wrap')}>
                <button
                  onClick={() => store.startRally(getTimestamp())}
                  className={clsx(
                    'flex-1 bg-blue-600 hover:bg-blue-500 text-white rounded font-medium',
                    useLargeTouch ? 'py-4 text-base' : 'py-2.5 text-sm'
                  )}
                >
                  ▶ ラリー開始
                </button>
                {/* モバイルでは見逃し・ブックマーク・コメント・ウォームアップを省略して画面を広く使う */}
                {!isMobile && (
                  <>
                    <button
                      onClick={() => setShowSkipRallyDialog(true)}
                      className="px-3 py-2.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs flex items-center gap-1 whitespace-nowrap"
                      title={t('skip_rally.hint')}
                    >
                      <SkipForward size={12} />
                      {t('skip_rally.button')}
                    </button>
                    {/* U-001: ブックマーク */}
                    <button
                      onClick={() => handleBookmark(null, getTimestamp())}
                      className={clsx(
                        'px-2.5 py-2.5 rounded text-xs flex items-center transition-colors',
                        lastBookmarked === null ? 'bg-gray-700 hover:bg-gray-600 text-gray-400' : 'bg-yellow-700/40 text-yellow-300'
                      )}
                      title={t('bookmark.add')}
                    >
                      <Bookmark size={13} />
                    </button>
                    {/* S-003: コメント */}
                    <button
                      onClick={() => { setShowCommentInput((v) => !v); setCommentRallyId(null) }}
                      className="px-2.5 py-2.5 bg-gray-700 hover:bg-gray-600 text-gray-400 rounded text-xs flex items-center transition-colors"
                      title={t('comment.add')}
                    >
                      <MessageSquare size={13} />
                    </button>
                    {/* T5: Review Later — 直前ラリーにレビューフラグ */}
                    {lastSavedRallyId != null && (
                      <button
                        onClick={handleReviewLater}
                        disabled={reviewLaterAdded}
                        className={clsx(
                          'px-2.5 py-2.5 rounded text-xs flex items-center gap-1 transition-colors whitespace-nowrap',
                          reviewLaterAdded
                            ? 'bg-amber-700/40 text-amber-300 cursor-default'
                            : 'bg-gray-700 hover:bg-amber-700/40 text-gray-400 hover:text-amber-300'
                        )}
                        title={t('review_later.hint')}
                      >
                        <Clock size={12} />
                        {reviewLaterAdded ? t('review_later.added') : t('review_later.button')}
                      </button>
                    )}
                    {/* G3: ウォームアップメモ */}
                    {store.currentSetNum === 1 && store.currentRallyNum === 1 && (
                      <button
                        onClick={() => setShowWarmupPanel((v) => !v)}
                        className={clsx(
                          'px-2.5 py-2.5 rounded text-xs flex items-center gap-1 transition-colors whitespace-nowrap',
                          showWarmupPanel
                            ? 'bg-blue-700 text-white'
                            : 'bg-gray-700 hover:bg-gray-600 text-blue-300'
                        )}
                        title={t('warmup.button')}
                      >
                        {t('warmup.button')}
                      </button>
                    )}
                  </>
                )}
              </div>
            )}

            {/* G3: ウォームアップメモパネル */}
            {showWarmupPanel && match && (
              <WarmupNotesPanel
                matchId={match.id}
                playerAId={match.player_a_id}
                playerBId={match.player_b_id}
                playerAName={match.player_a?.name ?? 'A'}
                playerBName={match.player_b?.name ?? 'B'}
                playerAHand={match.player_a?.dominant_hand ?? undefined}
                playerBHand={match.player_b?.dominant_hand ?? undefined}
                locked={store.isRallyActive}
                onClose={() => setShowWarmupPanel(false)}
              />
            )}

            {/* S-003: コメント入力フォーム（デスクトップのみ） */}
            {!isMobile && showCommentInput && (
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={commentText}
                  onChange={(e) => setCommentText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSubmitComment() }}
                  placeholder={t('comment.placeholder')}
                  className="flex-1 bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                  autoFocus
                />
                <button
                  onClick={handleSubmitComment}
                  disabled={!commentText.trim()}
                  className="px-2 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-xs text-white"
                >
                  {t('comment.submit')}
                </button>
                <button
                  onClick={() => { setShowCommentInput(false); setCommentText('') }}
                  className="px-2 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-400"
                >
                  ✕
                </button>
              </div>
            )}

            {/* ストローク履歴（モバイルでは最終ショットのみ表示） */}
            {isMobile ? (
              store.currentStrokes.length > 0 && (
                <div className="bg-gray-800 rounded px-3 py-2 text-xs text-gray-400 flex items-center justify-between shrink-0">
                  <span>
                    #{store.currentStrokes.length}{' '}
                    {store.currentStrokes[store.currentStrokes.length - 1]?.shot_type ?? ''}
                    {store.currentStrokes[store.currentStrokes.length - 1]?.land_zone
                      ? ` → ${store.currentStrokes[store.currentStrokes.length - 1].land_zone}`
                      : ''}
                  </span>
                  <span className="text-gray-600">
                    {store.currentStrokes.length} shots
                  </span>
                </div>
              )
            ) : (
              <StrokeHistory
                strokes={store.currentStrokes}
                playerAName={match?.player_a?.name ?? 'A'}
                playerBName={match?.player_b?.name ?? 'B'}
                partnerAName={match?.partner_a?.name}
                partnerBName={match?.partner_b?.name}
                playerATeam={match?.player_a?.team}
                playerBTeam={match?.player_b?.team}
                showLandZoneWarning={true}
              />
            )}

            {/* CV補助アノテーションパネル（showCVAssistPanel=true かつ候補あり） */}
            {!isMobile && showCVAssistPanel && candidatesData && (
              <div className={`rounded border p-2 shrink-0 ${
                isLight ? 'bg-purple-50 border-purple-200' : 'bg-purple-900/10 border-purple-700/30'
              }`}>
                <div className="flex items-center justify-between mb-1.5">
                  <span className={`text-[10px] font-semibold ${isLight ? 'text-purple-700' : 'text-purple-300'}`}>
                    CV補助候補
                  </span>
                  <button
                    onClick={() => setShowCVAssistPanel(false)}
                    className="text-gray-500 hover:text-gray-300 text-xs px-1"
                  >
                    ✕
                  </button>
                </div>
                <CVAssistPanel
                  rallyCandidates={
                    lastSavedRallyId != null
                      ? getCandidateForRally(lastSavedRallyId)
                      : null
                  }
                  currentStrokeNum={store.currentStrokeNum}
                />
              </div>
            )}

            {/* T2: Basic モード用 エンリッチメント手動展開ボタン */}
            {!isMobile && isBasicMode && store.isRallyActive && store.inputStep !== 'rally_end' && store.currentStrokes.length > 0 && !enrichmentActive && (
              <button
                onClick={() => setEnrichmentActive(true)}
                className="w-full flex items-center justify-center gap-1.5 py-1 text-[11px] text-gray-600 hover:text-gray-400 border border-gray-700 rounded transition-colors"
              >
                <ChevronDown size={11} />
                {t('annotation_mode.enrichment_hint')}
              </button>
            )}

            {/* G2+移動系: エンリッチメントストリップ（デスクトップのみ — モバイルでは省略） */}
            {!isMobile && enrichmentActive && store.currentStrokes.length > 0 && (() => {
              const last = store.currentStrokes[store.currentStrokes.length - 1]
              const RETURN_QUALITY = [
                { value: 'attack',    key: 'enrichment.return_quality_attack' },
                { value: 'neutral',   key: 'enrichment.return_quality_neutral' },
                { value: 'defensive', key: 'enrichment.return_quality_defensive' },
                { value: 'emergency', key: 'enrichment.return_quality_emergency' },
              ]
              const CONTACT_HEIGHT = [
                { value: 'overhead',  key: 'enrichment.contact_height_overhead' },
                { value: 'side',      key: 'enrichment.contact_height_side' },
                { value: 'underhand', key: 'enrichment.contact_height_underhand' },
                { value: 'scoop',     key: 'enrichment.contact_height_scoop' },
              ]
              const CONTACT_ZONE = [
                { value: 'front', key: 'enrichment.contact_zone_front' },
                { value: 'mid',   key: 'enrichment.contact_zone_mid' },
                { value: 'rear',  key: 'enrichment.contact_zone_rear' },
              ]
              const MOVEMENT_BURDEN = [
                { value: 'low',    key: 'enrichment.movement_burden_low' },
                { value: 'medium', key: 'enrichment.movement_burden_medium' },
                { value: 'high',   key: 'enrichment.movement_burden_high' },
              ]
              const MOVEMENT_DIRECTION = [
                { value: 'forward',   key: 'enrichment.movement_direction_forward' },
                { value: 'backward',  key: 'enrichment.movement_direction_backward' },
                { value: 'lateral',   key: 'enrichment.movement_direction_lateral' },
              ]
              const chipClass = (active: boolean) => clsx(
                'px-2.5 py-1.5 rounded border text-xs transition-colors',
                active
                  ? 'bg-gray-500 border-gray-400 text-white'
                  : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600',
              )
              return (
                <div className="border border-gray-600 bg-gray-800 rounded p-3 text-[11px] space-y-2 shrink-0">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-300 font-medium">
                      {isBasicMode ? t('annotation_mode.enrichment_hint') : t('enrichment.strip_label')}
                    </span>
                    <button
                      onClick={() => setEnrichmentActive(false)}
                      className="flex items-center gap-0.5 text-gray-500 hover:text-gray-300 text-xs px-1"
                    >
                      <ChevronUp size={11} />
                      折りたたむ
                    </button>
                  </div>
                  {/* 返球品質 */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-gray-400 min-w-[56px] text-xs">{t('enrichment.return_quality')}:</span>
                    {RETURN_QUALITY.map(({ value, key }) => (
                      <button key={value} onClick={() => {
                        const next = last.return_quality === value ? undefined : value
                        store.updateLastStrokeEnrichment({ returnQuality: next })
                      }} className={chipClass(last.return_quality === value)}>
                        {t(key)}
                      </button>
                    ))}
                  </div>
                  {/* 打点高さ */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-gray-400 min-w-[56px] text-xs">{t('enrichment.contact_height')}:</span>
                    {CONTACT_HEIGHT.map(({ value, key }) => (
                      <button key={value} onClick={() => {
                        const next = last.contact_height === value ? undefined : value
                        store.updateLastStrokeEnrichment({ contactHeight: next })
                      }} className={chipClass(last.contact_height === value)}>
                        {t(key)}
                      </button>
                    ))}
                  </div>
                  {/* 打点コート位置 */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-gray-400 min-w-[56px] text-xs">{t('enrichment.contact_zone')}:</span>
                    {CONTACT_ZONE.map(({ value, key }) => (
                      <button key={value} onClick={() => {
                        const next = last.contact_zone === value ? undefined : value
                        store.updateLastStrokeEnrichment({ contactZone: next })
                      }} className={chipClass(last.contact_zone === value)}>
                        {t(key)}
                      </button>
                    ))}
                  </div>
                  {/* 移動負荷 */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-gray-400 min-w-[56px] text-xs">{t('enrichment.movement_burden')}:</span>
                    {MOVEMENT_BURDEN.map(({ value, key }) => (
                      <button key={value} onClick={() => {
                        const next = last.movement_burden === value ? undefined : value
                        store.updateLastStrokeEnrichment({ movementBurden: next })
                      }} className={chipClass(last.movement_burden === value)}>
                        {t(key)}
                      </button>
                    ))}
                  </div>
                  {/* 移動方向 */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-gray-400 min-w-[56px] text-xs">{t('enrichment.movement_direction')}:</span>
                    {MOVEMENT_DIRECTION.map(({ value, key }) => (
                      <button key={value} onClick={() => {
                        const next = last.movement_direction === value ? undefined : value
                        store.updateLastStrokeEnrichment({ movementDirection: next })
                      }} className={chipClass(last.movement_direction === value)}>
                        {t(key)}
                      </button>
                    ))}
                  </div>
                  <div className="text-[10px] text-gray-500">{t('enrichment.expires_hint')}</div>
                </div>
              )
            })()}

            {/* アクションボタン */}
            <div className="flex flex-col gap-1.5 shrink-0">
              {/* ラリー終了ボタン */}
              {store.isRallyActive && store.currentStrokes.length > 0 && store.inputStep !== 'rally_end' && (
                <button
                  onClick={() => store.endRallyRequest()}
                  className={clsx(
                    'w-full bg-green-700 hover:bg-green-600 text-white rounded font-medium',
                    useLargeTouch ? 'py-4 text-base' : 'py-2 text-sm'
                  )}
                >
                  ラリー終了 {!isMobile && '(Enter)'}
                </button>
              )}

              {/* アンドゥ */}
              {store.currentStrokes.length > 0 && (
                <button
                  onClick={() => store.undoLastStroke()}
                  className={clsx(
                    'flex items-center gap-1 justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded',
                    useLargeTouch ? 'py-3 text-base' : 'py-1.5 text-sm'
                  )}
                >
                  <RotateCcw size={useLargeTouch ? 16 : 14} />
                  戻す {!isMobile && '(Ctrl+Z)'}
                </button>
              )}

              {/* ラリーリセット */}
              {store.isRallyActive && (
                <button
                  onClick={() => store.resetRally()}
                  className={clsx(
                    'w-full bg-red-900/50 hover:bg-red-800/50 text-red-400 rounded',
                    useLargeTouch ? 'py-2.5 text-sm' : 'py-1.5 text-xs'
                  )}
                >
                  ✕ ラリーキャンセル
                </button>
              )}
            </div>

            {/* セット管理（C-1: 確認ダイアログ付き）— モバイルでは折りたたみ */}
            {/* G1: ラリー中は管理操作をグレースケールでロック表示（Step A のみ有効） */}
            {initialized && !isMobile && (
              <div className={clsx(
                'border rounded p-2 text-xs shrink-0 transition-opacity',
                store.isRallyActive
                  ? 'border-gray-700/50 opacity-40 pointer-events-none'
                  : 'border-gray-700',
              )}>
                <div className="text-gray-400 mb-1.5 font-medium flex items-center gap-1.5">
                  管理操作
                  {store.isRallyActive && (
                    <span className="text-[10px] text-gray-600">（ラリー中は使用不可）</span>
                  )}
                </div>

                {/* C-1: セット移行確認ダイアログ */}
                {setNavConfirm ? (
                  <div className="bg-yellow-900/20 border border-yellow-700/50 rounded p-2 mb-1.5">
                    <p className="text-yellow-400 text-[11px] mb-2">
                      {setNavConfirm.direction === 'next'
                        ? `Set ${store.currentSetNum} を終了して Set ${store.currentSetNum + 1} へ移行しますか？`
                        : `Set ${store.currentSetNum - 1} へ戻りますか？（現在のセット進行は変わりません）`
                      }
                    </p>
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => {
                          const dir = setNavConfirm.direction
                          setSetNavConfirm(null)
                          if (dir === 'next') handleNextSet()
                          else handlePrevSet()
                        }}
                        className="flex-1 py-1 bg-yellow-700 hover:bg-yellow-600 text-white rounded text-[11px] font-medium"
                      >
                        確定
                      </button>
                      <button
                        onClick={() => setSetNavConfirm(null)}
                        className="flex-1 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-[11px]"
                      >
                        キャンセル
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex gap-1.5 mb-1.5">
                    <button
                      onClick={() => setSetNavConfirm({ direction: 'prev' })}
                      disabled={store.currentSetNum <= 1}
                      className="flex items-center gap-1 flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded justify-center disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <ChevronLeft size={12} />
                      前のセット (Set {store.currentSetNum - 1})
                    </button>
                    <button
                      onClick={() => setSetNavConfirm({ direction: 'next' })}
                      className="flex items-center gap-1 flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded justify-center"
                    >
                      <ChevronRight size={12} />
                      次のセットへ (Set {store.currentSetNum + 1})
                    </button>
                  </div>
                )}
                {/* P1: スコア補正・強制セット終了 */}
                <div className="flex gap-1.5">
                  <button
                    onClick={() => {
                      setCorrectionTargetA(store.scoreA)
                      setCorrectionTargetB(store.scoreB)
                      setShowScoreCorrection(true)
                    }}
                    className="flex-1 py-1 bg-gray-700 hover:bg-gray-600 text-gray-400 rounded text-[10px]"
                  >
                    {t('skip_rally.score_correction')}
                  </button>
                  <button
                    onClick={() => {
                      setForceSetScoreA(store.scoreA)
                      setForceSetScoreB(store.scoreB)
                      setShowForceSetEnd(true)
                    }}
                    className="flex-1 py-1 bg-gray-700 hover:bg-gray-600 text-gray-400 rounded text-[10px]"
                  >
                    {t('skip_rally.force_set_end')}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* V4-U-001: 試合中補完パネル（暫定相手選手情報の追記） */}
      {showInMatchPanel && match?.player_b && (
        <div className="fixed bottom-4 right-4 z-40 w-72 bg-gray-800 border border-orange-500/40 rounded-lg shadow-xl">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
            <div className="flex items-center gap-2 text-sm font-medium">
              <ClipboardEdit size={14} className="text-orange-400" />
              {t('in_match_panel.title')}
              {match.player_b.profile_status === 'provisional' && (
                <span className="text-xs text-yellow-400 bg-yellow-400/10 px-1.5 rounded">
                  {t('in_match_panel.provisional_badge')}
                </span>
              )}
            </div>
            <button
              onClick={() => setShowInMatchPanel(false)}
              className="text-gray-400 hover:text-white text-xs"
            >✕</button>
          </div>
          <div className="p-4 flex flex-col gap-3">
            <div className="text-xs text-gray-400 truncate">{match.player_b.name}</div>
            {/* 利き手 */}
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('in_match_panel.dominant_hand')}</label>
              <div className="flex gap-1.5">
                {[
                  { value: 'R', label: t('in_match_panel.hand_right') },
                  { value: 'L', label: t('in_match_panel.hand_left') },
                  { value: '', label: t('in_match_panel.hand_unknown') },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setInMatchDominantHand(opt.value)}
                    className={clsx(
                      'flex-1 py-1 rounded text-xs border',
                      inMatchDominantHand === opt.value
                        ? 'bg-blue-600 border-blue-500 text-white'
                        : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
            {/* 所属 */}
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('in_match_panel.organization')}</label>
              <input
                value={inMatchOrganization}
                onChange={(e) => setInMatchOrganization(e.target.value)}
                className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs"
                placeholder="チーム・所属"
              />
            </div>
            {/* メモ */}
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('in_match_panel.scouting_notes')}</label>
              <textarea
                value={inMatchScoutingNotes}
                onChange={(e) => setInMatchScoutingNotes(e.target.value)}
                rows={2}
                className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs resize-none"
                placeholder="気づいたこと、プレースタイルなど"
              />
            </div>
            {/* 保存 */}
            <button
              onClick={() => {
                updateOpponent.mutate({
                  dominant_hand: inMatchDominantHand || undefined,
                  organization: inMatchOrganization || undefined,
                  scouting_notes: inMatchScoutingNotes || undefined,
                  profile_status: 'partial',
                })
              }}
              disabled={updateOpponent.isPending}
              className="w-full py-1.5 bg-orange-600 hover:bg-orange-500 text-white rounded text-xs font-medium disabled:opacity-50"
            >
              {inMatchSaved ? t('in_match_panel.saved') : t('in_match_panel.save')}
            </button>
          </div>
        </div>
      )}

      {/* K-003: セット間サマリーモーダル */}
      {showIntervalSummary && intervalSummarySetId != null && (
        <SetIntervalSummary
          setId={intervalSummarySetId}
          playerAName={match?.player_a?.name ?? 'A'}
          playerBName={match?.player_b?.name ?? 'B'}
          onClose={handleModalNextSet}
          onNextSet={handleModalNextSet}
        />
      )}

      {/* 11点インターバル解析モーダル */}
      {showMidGameSummary && store.currentSetId != null && (
        <SetIntervalSummary
          setId={store.currentSetId}
          playerAName={match?.player_a?.name ?? 'A'}
          playerBName={match?.player_b?.name ?? 'B'}
          isMidGame={true}
          midGameScoreA={store.scoreA}
          midGameScoreB={store.scoreB}
          onClose={() => setShowMidGameSummary(false)}
          onNextSet={() => setShowMidGameSummary(false)}
        />
      )}

      {/* 途中終了ダイアログ */}
      {showExceptionDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-800 border border-red-700/50 rounded-lg w-80 shadow-2xl">
            <div className="px-4 py-3 border-b border-gray-700">
              <div className="flex items-center gap-2 text-sm font-medium text-red-400">
                <OctagonX size={16} />
                {t('exception.title')}
              </div>
              <div className="text-xs text-gray-400 mt-0.5">{t('exception.subtitle')}</div>
            </div>
            <div className="p-4 flex flex-col gap-2">
              {/* 終了理由選択 */}
              {(
                [
                  { value: 'retired_a', label: t('exception.retired_a') },
                  { value: 'retired_b', label: t('exception.retired_b') },
                  { value: 'abandoned', label: t('exception.abandoned') },
                ] as const
              ).map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setExceptionReason(value)}
                  className={clsx(
                    'w-full py-2 px-3 rounded text-sm text-left transition-colors border',
                    exceptionReason === value
                      ? 'bg-red-800/50 border-red-500 text-red-200'
                      : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
                  )}
                >
                  {label}
                </button>
              ))}
              {store.isRallyActive && (
                <div className="text-xs text-yellow-400 flex items-center gap-1 mt-1">
                  ⚠ {t('exception.mid_rally_warning')}
                </div>
              )}
            </div>
            <div className="px-4 pb-4 flex gap-2">
              <button
                onClick={() => {
                  setShowExceptionDialog(false)
                  setExceptionReason(null)
                }}
                className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm"
              >
                {t('exception.cancel')}
              </button>
              <button
                onClick={handleException}
                disabled={!exceptionReason}
                className="flex-1 py-2 bg-red-700 hover:bg-red-600 text-white rounded text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {t('exception.confirm')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* P1: 見逃しラリーダイアログ */}
      {showSkipRallyDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-800 border border-gray-600 rounded-lg w-72 shadow-2xl">
            <div className="px-4 py-3 border-b border-gray-700">
              <div className="text-sm font-medium text-gray-200 flex items-center gap-2">
                <SkipForward size={14} className="text-yellow-400" />
                {t('skip_rally.title')}
              </div>
              <div className="text-xs text-gray-400 mt-0.5">{t('skip_rally.hint')}</div>
            </div>
            <div className="p-4 grid grid-cols-2 gap-2">
              <button
                onClick={() => handleSkipRally('player_a')}
                className="py-4 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-bold"
              >
                {match?.player_a?.name ?? 'A'} 得点
              </button>
              <button
                onClick={() => handleSkipRally('player_b')}
                className="py-4 bg-orange-600 hover:bg-orange-500 text-white rounded text-sm font-bold"
              >
                {match?.player_b?.name ?? 'B'} 得点
              </button>
            </div>
            <div className="px-4 pb-4">
              <button
                onClick={() => setShowSkipRallyDialog(false)}
                className="w-full py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs"
              >
                キャンセル
              </button>
            </div>
          </div>
        </div>
      )}

      {/* P1: スコア補正ダイアログ */}
      {showScoreCorrection && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-800 border border-gray-600 rounded-lg w-80 shadow-2xl">
            <div className="px-4 py-3 border-b border-gray-700">
              <div className="text-sm font-medium text-gray-200">{t('skip_rally.score_correction_title')}</div>
              <div className="text-xs text-gray-400 mt-0.5">{t('skip_rally.score_correction_hint')}</div>
            </div>
            <div className="p-4 space-y-3">
              <div className="text-xs text-gray-400">
                {t('skip_rally.current')}: {match?.player_a?.name ?? 'A'} {store.scoreA} — {match?.player_b?.name ?? 'B'} {store.scoreB}
              </div>
              <div className="grid grid-cols-2 gap-3">
                {([
                  { label: match?.player_a?.name ?? 'A', val: correctionTargetA, setVal: setCorrectionTargetA },
                  { label: match?.player_b?.name ?? 'B', val: correctionTargetB, setVal: setCorrectionTargetB },
                ] as const).map(({ label, val, setVal }) => (
                  <div key={label}>
                    <div className="text-xs text-gray-400 mb-1 truncate">{label}</div>
                    <div className="flex items-center gap-1">
                      <button onClick={() => setVal(Math.max(0, val - 1))} className="w-7 h-7 bg-gray-700 hover:bg-gray-600 rounded text-gray-300 font-bold">−</button>
                      <span className="flex-1 text-center text-lg font-bold text-white">{val}</span>
                      <button onClick={() => setVal(val + 1)} className="w-7 h-7 bg-gray-700 hover:bg-gray-600 rounded text-gray-300 font-bold">＋</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="px-4 pb-4 flex gap-2">
              <button onClick={() => setShowScoreCorrection(false)} className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm">キャンセル</button>
              <button onClick={handleScoreCorrection} className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium">{t('skip_rally.apply')}</button>
            </div>
          </div>
        </div>
      )}

      {/* R-001/R-002: セッション共有モーダル（QRコード + パスワード） */}
      {showSessionModal && activeSession && (
        <SessionShareModal
          sessionCode={activeSession.session_code}
          coachUrls={(activeSession.coach_urls ?? []).map(rebaseUrl)}
          cameraSenderUrls={(activeSession.camera_sender_urls ?? []).map(rebaseUrl)}
          viewerUrls={(activeSession.camera_sender_urls ?? []).map((u) => rebaseUrl(u.replace('/camera/', '/viewer/')))}
          sessionPassword={activeSession.session_password}
          onClose={() => setShowSessionModal(false)}
        />
      )}

      {/* LAN デバイス管理パネル */}
      {showDeviceManager && activeSession && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowDeviceManager(false)}>
          <div onClick={(e) => e.stopPropagation()}>
            <DeviceManagerPanel
              sessionCode={activeSession.session_code}
              onClose={() => setShowDeviceManager(false)}
              onRemoteStream={(stream) => {
                setRemoteStream(stream)
                if (stream) setVideoSourceMode('webview')
              }}
              onLocalStream={(stream) => {
                setLocalCamStream(stream)
                if (stream) setVideoSourceMode('webview')
              }}
              onHealthChange={setRemoteHealth}
            />
          </div>
        </div>
      )}

      {/* P1: セット強制終了ダイアログ */}
      {showForceSetEnd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-800 border border-orange-700/50 rounded-lg w-80 shadow-2xl">
            <div className="px-4 py-3 border-b border-gray-700">
              <div className="text-sm font-medium text-orange-400">{t('skip_rally.force_set_end_title')}</div>
              <div className="text-xs text-gray-400 mt-0.5">{t('skip_rally.force_set_end_hint')}</div>
            </div>
            <div className="p-4 space-y-3">
              <div className="text-xs text-gray-400">{t('skip_rally.final_score')}</div>
              <div className="grid grid-cols-2 gap-3">
                {([
                  { label: match?.player_a?.name ?? 'A', val: forceSetScoreA, setVal: setForceSetScoreA },
                  { label: match?.player_b?.name ?? 'B', val: forceSetScoreB, setVal: setForceSetScoreB },
                ] as const).map(({ label, val, setVal }) => (
                  <div key={label}>
                    <div className="text-xs text-gray-400 mb-1 truncate">{label}</div>
                    <div className="flex items-center gap-1">
                      <button onClick={() => setVal(Math.max(0, val - 1))} className="w-7 h-7 bg-gray-700 hover:bg-gray-600 rounded text-gray-300 font-bold">−</button>
                      <span className="flex-1 text-center text-lg font-bold text-white">{val}</span>
                      <button onClick={() => setVal(val + 1)} className="w-7 h-7 bg-gray-700 hover:bg-gray-600 rounded text-gray-300 font-bold">＋</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="px-4 pb-4 flex gap-2">
              <button onClick={() => setShowForceSetEnd(false)} className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm">キャンセル</button>
              <button onClick={handleForceSetEnd} className="flex-1 py-2 bg-orange-600 hover:bg-orange-500 text-white rounded text-sm font-medium">{t('skip_rally.confirm_end')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
