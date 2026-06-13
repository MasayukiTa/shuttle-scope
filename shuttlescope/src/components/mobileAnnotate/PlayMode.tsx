/**
 * MobileAnnotate / Play mode (R48 step 3)
 *
 * 動画再生 + 下部固定コントロール + クロップ矩形編集。
 *
 * クロップ:
 *   鳥瞰固定カメラの不要部分 (天井 / 観客席など) を切り抜いて再生する。
 *   矩形は normalized coords {x, y, w, h} in [0,1] で保持し localStorage に
 *   match_id ごと保存。CSS の object-position + transform: scale で
 *   クロップ領域だけが見えるように拡大表示する (clip-path より iOS Safari
 *   で安定するため)。
 *
 * 干渉ゼロ設計:
 *   - 動画上のタップ (コントロールバー以外) → pause + onTapVideo() 呼び出し
 *     呼び出し側 (MobileAnnotatePage) が Annotate mode に切替える。
 *   - 下部コントロールバーは「再生関連操作だけ」を持つ:
 *       ◀◀5  ◀1  ▶/❚❚  1▶  5▶   [スクラブ slider]   [0.5x][1x][1.5x][2x]
 *   - クロップ編集モードはツールバー右上の ✂ ボタンから入る。編集中は
 *     コートタップが矩形ハンドル操作になり、再生は強制停止される。
 */
import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'

import { apiGet } from '@/api/client'
// CLAUDE.md / メモリ規約に従い Material Symbols (MIcon) を使う。lucide-react は段階廃止。
import { MIcon } from '@/components/common/MIcon'
import { MobileCVOverlay } from '@/components/mobileAnnotate/MobileCVOverlay'
import { MobileCourtCalib } from '@/components/mobileAnnotate/MobileCourtCalib'
import { useTranslation } from 'react-i18next'

export interface CropRect {
  x: number; y: number; w: number; h: number  // 0..1 normalized
}

const FULL_CROP: CropRect = { x: 0, y: 0, w: 1, h: 1 }

function loadCrop(matchId: string | number): CropRect {
  try {
    const raw = localStorage.getItem(`ss_crop_${matchId}`)
    if (!raw) return FULL_CROP
    const c = JSON.parse(raw)
    if (typeof c.x === 'number' && typeof c.y === 'number' &&
        typeof c.w === 'number' && typeof c.h === 'number') {
      return c
    }
  } catch {}
  return FULL_CROP
}

function saveCrop(matchId: string | number, c: CropRect): void {
  try {
    localStorage.setItem(`ss_crop_${matchId}`, JSON.stringify(c))
  } catch {}
}


export interface QualityOption {
  quality: 'source' | 'uhd' | 'fhd' | 'hd' | string
  height: number
  ready: boolean
}

interface Props {
  matchId: string | number
  videoSrc: string
  /** 動画タップ時に呼ばれる (Annotate mode への切替 trigger) */
  onTapVideo: (currentTime: number) => void
  /** 動画再生時間取得 / 操作のため、親に ref を渡したい場合に */
  videoElRef?: (el: HTMLVideoElement | null) => void
  /** 利用可能な画質一覧 (backend の match レスポンスから) */
  qualities?: QualityOption[]
  /** 現在選択中の画質 ('source' / 'fhd' / 'hd') */
  currentQuality?: 'source' | 'uhd' | 'fhd' | 'hd' | string
  /** 画質変更コールバック */
  onQualityChange?: (q: 'source' | 'uhd' | 'fhd' | 'hd' | string) => void
  /** CV 候補のタイムスタンプ配列。seek bar 上にマーカー描画 */
  cvCandidateTimestamps?: number[]
  /** 過去アノテの続きから再開するための時刻 (秒)。0 なら chip 非表示。 */
  resumeFromSec?: number
  /** calib 編集中フラグを親に伝える (= 親側の overlay / chip を隠すため) */
  onCalibEditingChange?: (editing: boolean) => void
  /** videoSrc が無い / 失敗時の再取得トリガ (= 親の match query refetch)。 */
  onRetryVideo?: () => void
}

export function PlayMode({ matchId, videoSrc, onTapVideo, videoElRef, qualities, currentQuality, onQualityChange, cvCandidateTimestamps, resumeFromSec, onCalibEditingChange, onRetryVideo }: Props) {
  const { t } = useTranslation()
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [speed, setSpeed] = useState(1)
  const [crop, setCrop] = useState<CropRect>(() => loadCrop(matchId))
  const [cropEditing, setCropEditing] = useState(false)
  const [pendingCrop, setPendingCrop] = useState<CropRect>(crop)
  // contain = レターボックスで全面表示 (短辺基準、欠けない)。cover = viewport を
  // 埋める (長辺基準、上下/左右 crop)。アノテはコート全体が見えないと打点判定
  // できないので contain を default。Square ボタンで cover にも切替可。
  const [fitMode, setFitMode] = useState<'cover' | 'contain'>('contain')
  // 再生エラーを onscreen に出す (β: Safari Web Inspector に繋げない端末でも見えるよう)
  const [playError, setPlayError] = useState<string>('')
  // iOS Safari は要素単位 requestFullscreen を持たないため、ホーム画面追加を促す
  const [iosFsHint, setIosFsHint] = useState(false)
  // 画質切替時に「現在の currentTime + 再生中フラグ」を保持して、新 src の
  // loadedmetadata 後に復元する。これをしないと src 変更 = 動画 element が再 load
  // して 0 秒から再生になる。
  const pendingResume = useRef<{ time: number; wasPlaying: boolean } | null>(null)
  // PWA standalone モード判定 (= iOS ホーム画面追加 or Android インストール時)。
  // PWA はすでに URL バーなしフル表示なので Fullscreen ボタンを出しても役立たない。
  const isPwaStandalone = useMemo(() => {
    if (typeof window === 'undefined') return false
    try {
      // iOS Safari: navigator.standalone
      if ((navigator as unknown as { standalone?: boolean }).standalone === true) return true
      // Android Chrome / desktop PWA: matchMedia
      if (window.matchMedia('(display-mode: standalone)').matches) return true
    } catch { /* ignore */ }
    return false
  }, [])

  // CV オーバーレイの可視性 (個別 toggle で重ね描きの ON/OFF 切替可能)
  const [showCourt, setShowCourt] = useState(true)
  const [showShuttle, setShowShuttle] = useState(true)
  const [showPlayers, setShowPlayers] = useState(false)  // bbox は視認性影響大なので default OFF
  // コートキャリブ編集モード (親にも同期して overlay 隠す)
  const [calibEditing, _setCalibEditing] = useState(false)
  // calib 中に video element を hide して見せる "静止画" snapshot (data URL)。
  // iOS Safari は paused playsInline video の中央に消せない native overlay
  // (big play button) を出すため、pointer-events:none / ::webkit CSS では消えない。
  // → video 自体を display:none し、その瞬間のフレームを canvas → dataURL → <img>
  // で代替表示することで、iOS native overlay の発生原因 (= 可視 paused video)
  // を構造的に取り除く。
  const [calibSnapshot, setCalibSnapshot] = useState<string | null>(null)
  const setCalibEditing = useCallback((v: boolean) => {
    _setCalibEditing(v)
    onCalibEditingChange?.(v)
    if (!v) setCalibSnapshot(null)
  }, [onCalibEditingChange])
  // 既存キャリブ点 (編集モードに渡す初期値 + 保存後に上書き)
  const [calibPoints, setCalibPoints] = useState<{ x: number; y: number }[]>([])
  // 保存後に MobileCVOverlay を強制再 fetch させる version カウンタ
  const [calibVersion, setCalibVersion] = useState(0)

  // 過去解析の存在確認 (toggle OFF でも "解析済" バッジを出すため)。
  // 結果数だけ知りたいので length のみ抽出して keep。表示 toggle と独立に常時 fetch。
  const shuttleExistsQuery = useQuery({
    queryKey: ['mobile-shuttle-exists', matchId],
    queryFn: () => apiGet<{ success?: boolean; data?: unknown[] }>(`/api/tracknet/shuttle_track/${matchId}`),
    enabled: !!matchId,
    staleTime: 60_000,
    retry: 0,
  })
  const shuttleFrameCount = Array.isArray(shuttleExistsQuery.data?.data) ? shuttleExistsQuery.data!.data!.length : 0

  const yoloExistsQuery = useQuery({
    queryKey: ['mobile-yolo-exists', matchId],
    queryFn: () => apiGet<{ frames?: unknown[] }>(`/api/yolo/results/${matchId}`),
    enabled: !!matchId,
    staleTime: 60_000,
    retry: 0,
  })
  const yoloFrameCount = Array.isArray(yoloExistsQuery.data?.frames) ? yoloExistsQuery.data!.frames!.length : 0

  // 既存キャリブ点を初回読み込み (localStorage 共有経路 → backend fetch は MobileCVOverlay 側)
  useEffect(() => {
    try {
      const saved = localStorage.getItem(`court-calib-${matchId}`)
      if (saved) {
        const pts = JSON.parse(saved)
        if (Array.isArray(pts) && pts.length === 6) setCalibPoints(pts)
      }
    } catch { /* ignore */ }
  }, [matchId, calibVersion])
  // overlay 描画用に video element の実描画サイズを track する
  const [videoBox, setVideoBox] = useState({ w: 0, h: 0 })

  // 親に videoRef を露出
  useEffect(() => {
    videoElRef?.(videoRef.current)
    return () => { videoElRef?.(null) }
  }, [videoElRef])

  // overlay 用にコンテナ実寸を計測 (object-fit cover/contain でも overlay は
  // コンテナ全体に重ねるので、コンテナサイズと一致させる)
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => {
      setVideoBox({ w: el.clientWidth || 0, h: el.clientHeight || 0 })
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // playback rate
  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = speed
  }, [speed])

  // 画質切替で再 load される際の seek 位置 + 再生状態を保持。
  // useEffect で videoSrc 変化を検知すると、ブラウザが既に新 src で 0 秒から
  // ロードし始めた "後" になり currentTime が 0 で読み取られてしまう。
  // 解決: 画質 chip クリック ハンドラ内 (= React 再 render 前) で時刻 capture して
  // から onQualityChange を呼ぶ。
  const requestQualityChange = useCallback((q: string) => {
    const v = videoRef.current
    if (v && v.readyState >= 1) {
      pendingResume.current = {
        time: v.currentTime,
        wasPlaying: !v.paused,
      }
    }
    onQualityChange?.(q)
  }, [onQualityChange])

  // 動画再読み込み: videoSrc がある場合は video element を load() し直し、
  // 無い場合 (= サーバ準備中で URL 未発行) は親に match 再取得を促す。
  const retryVideo = useCallback(() => {
    setPlayError('')
    onRetryVideo?.()
    const v = videoRef.current
    if (v && videoSrc) {
      try { v.load() } catch { /* ignore */ }
    }
  }, [onRetryVideo, videoSrc])

  // videoSrc が無い間は数秒ごとに自動で再取得を試みる (= サーバが準備完了したら
  // 自動で再生に移行)。手動「再読み込み」ボタンと併用。
  useEffect(() => {
    if (videoSrc) return
    if (!onRetryVideo) return
    const id = window.setInterval(() => {
      onRetryVideo()
    }, 5000)
    return () => window.clearInterval(id)
  }, [videoSrc, onRetryVideo])

  // events
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onTime = () => setCurrentTime(v.currentTime)
    const onMeta = () => {
      setDuration(v.duration || 0)
      // 画質切替後の seek + 再生復元
      const pending = pendingResume.current
      if (pending) {
        pendingResume.current = null
        try {
          // duration が確定したら seek 可能。pending.time が duration を超える場合は
          // clamp する (variant の長さが微妙に違う可能性に備える)。
          const target = Math.max(0, Math.min(v.duration || pending.time, pending.time))
          v.currentTime = target
          if (pending.wasPlaying) {
            v.play().catch(() => { /* autoplay block 等は無視 */ })
          }
        } catch { /* ignore */ }
      } else {
        // 初回ロード時の自動再生試行 (iOS は user gesture が必要なケースが多いので
        // 失敗時は静かに無視。ユーザは下端 Play ボタンで開始できる)。
        v.play().catch(() => { /* autoplay block 等は無視 */ })
      }
    }
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    v.addEventListener('timeupdate', onTime)
    v.addEventListener('loadedmetadata', onMeta)
    v.addEventListener('play', onPlay)
    v.addEventListener('pause', onPause)
    return () => {
      v.removeEventListener('timeupdate', onTime)
      v.removeEventListener('loadedmetadata', onMeta)
      v.removeEventListener('play', onPlay)
      v.removeEventListener('pause', onPause)
    }
  }, [videoSrc])

  const togglePlay = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (!v.paused) {
      v.pause()
      return
    }
    setPlayError('')
    // iOS Safari: 初回 play 前に load() を打って metadata 取得を確実にする
    if (v.readyState < 2) {
      try { v.load() } catch {}
    }
    const p = v.play()
    if (p && typeof p.catch === 'function') {
      p.catch((err: unknown) => {
        const msg = err instanceof Error ? `${err.name}: ${err.message}` : String(err)
        console.error('[mobile-annot] play() rejected', msg, {
          readyState: v.readyState,
          networkState: v.networkState,
          error: v.error?.code,
          src: v.src,
        })
        setPlayError(msg)
      })
    }
  }, [])

  const seekBy = useCallback((delta: number) => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = Math.max(0, Math.min((duration || 1e9), v.currentTime + delta))
  }, [duration])

  const onScrub = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = parseFloat(e.target.value)
  }, [])

  /**
   * クロップ表示: 動画を container いっぱいに伸ばしつつ、クロップ領域 (x,y,w,h)
   * が container いっぱいに見えるように scale + translate する。
   *  - scale = 1/w (横) / 1/h (縦) → fit-fill にはなるが、横と縦が違うと
   *    アスペクト比歪み。簡易に max(1/w, 1/h) のみ採用 (一部見切れる)
   *  - 安全側で min(1/w, 1/h) を使うと余白が出る。今回は max-zoom で
   *    切り抜き優先 (どうせ余分な天井等を切るのが目的)。
   */
  const cropStyle: React.CSSProperties = (() => {
    const { x, y, w, h } = crop
    if (w >= 0.99 && h >= 0.99) {
      return { width: '100%', height: '100%', objectFit: fitMode }
    }
    const scale = Math.min(1 / w, 1 / h)
    // 中心オフセット
    const cx = x + w / 2
    const cy = y + h / 2
    const translateX = (0.5 - cx) * 100 * scale
    const translateY = (0.5 - cy) * 100 * scale
    return {
      width: '100%',
      height: '100%',
      objectFit: fitMode,
      transform: `translate(${translateX}%, ${translateY}%) scale(${scale})`,
      transformOrigin: 'center',
    }
  })()

  // フルスクリーン: **document.documentElement 全体** を全画面化することで
  // overlay (コートグリッド / シャトル / Pass ボタン / 右上 chip 等) を保ったまま
  // 画面いっぱいに広げる。
  //
  // 旧実装は videoRef.webkitEnterFullscreen() を呼んでいたが、これは iOS 純正
  // 動画プレーヤーに飛ぶので overlay / アノテボタンが全消失する (= ただの動画
  // 視聴になる) ため使用禁止。
  //
  // 戦略:
  //  - 標準 Fullscreen API (Desktop / Android Chrome) → requestFullscreen
  //  - iOS Safari は要素単位 requestFullscreen 非対応 → 「ホーム画面に追加」を
  //    1 回だけガイド (Add-to-Home-Screen で PWA フルスクリーン化が可能)
  const enterFullscreen = useCallback(() => {
    const target = document.documentElement as HTMLElement & {
      requestFullscreen?: () => Promise<void>
      webkitRequestFullscreen?: () => Promise<void> | void
      mozRequestFullScreen?: () => Promise<void> | void
      msRequestFullscreen?: () => Promise<void> | void
    }
    const reqFs =
      target.requestFullscreen ||
      target.webkitRequestFullscreen ||
      target.mozRequestFullScreen ||
      target.msRequestFullscreen
    if (typeof reqFs === 'function') {
      try {
        const p = reqFs.call(target)
        if (p && typeof p.catch === 'function') {
          p.catch(() => setIosFsHint(true))
        }
        return
      } catch {
        // fallthrough
      }
    }
    // iOS Safari (要素単位 requestFullscreen 不可)
    setIosFsHint(true)
  }, [])

  const startCropEdit = () => {
    const v = videoRef.current
    if (v && !v.paused) v.pause()
    setPendingCrop(crop)
    setCropEditing(true)
  }

  const commitCrop = () => {
    setCrop(pendingCrop)
    saveCrop(matchId, pendingCrop)
    setCropEditing(false)
  }

  const cancelCrop = () => {
    setPendingCrop(crop)
    setCropEditing(false)
  }

  const resetCrop = () => {
    setPendingCrop(FULL_CROP)
  }

  // クロップ編集: container 上のドラッグで矩形 4 隅をつまむ
  // 簡単 UX: container 上の touch 開始位置 → 終了位置 を新 crop の対角線にする
  const onCropTouch = (e: React.TouchEvent<HTMLDivElement>) => {
    if (!cropEditing) return
    e.preventDefault()
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    const t0 = e.touches[0]
    const startX = (t0.clientX - rect.left) / rect.width
    const startY = (t0.clientY - rect.top) / rect.height
    let endX = startX, endY = startY
    const onMove = (ev: TouchEvent) => {
      const t = ev.touches[0]
      endX = Math.max(0, Math.min(1, (t.clientX - rect.left) / rect.width))
      endY = Math.max(0, Math.min(1, (t.clientY - rect.top) / rect.height))
      const x = Math.min(startX, endX)
      const y = Math.min(startY, endY)
      const w = Math.max(0.1, Math.abs(endX - startX))
      const h = Math.max(0.1, Math.abs(endY - startY))
      setPendingCrop({ x, y, w, h })
    }
    const onEnd = () => {
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend', onEnd)
      window.removeEventListener('touchcancel', onEnd)
    }
    window.addEventListener('touchmove', onMove, { passive: false })
    window.addEventListener('touchend', onEnd)
    window.addEventListener('touchcancel', onEnd)
  }

  const fmt = (s: number) => {
    if (!isFinite(s)) return '--:--'
    const m = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  const visibleCrop = cropEditing ? pendingCrop : crop

  return (
    <div className="absolute inset-0 w-full h-full bg-black">
      {/* 動画領域: viewport 全面 */}
      <div
        ref={containerRef}
        className="absolute inset-0 overflow-hidden bg-black"
        onClick={(e) => {
          // 動画タップ = pause + Annotate mode へ。
          // ⚠️ 子の chip / overlay 上のタップが bubble して誤発火するのを防ぐため、
          // タップ対象が **container 自身 or <video> element のとき限定** で反応。
          // (旧版は子 div からの bubble で set 1 prompt が誤って出る事象あり)
          if (cropEditing) return
          const target = e.target as Element | null
          const isContainer = target === e.currentTarget
          const isVideo = target?.tagName === 'VIDEO'
          if (!isContainer && !isVideo) return
          e.stopPropagation()
          const v = videoRef.current
          if (v && !v.paused) v.pause()
          onTapVideo(v?.currentTime ?? 0)
        }}
        onTouchStart={cropEditing ? onCropTouch : undefined}
      >
        {!videoSrc ? (
          <div className="absolute inset-0 flex items-center justify-center text-white text-sm p-4">
            <div className="text-center max-w-md">
              <div className="text-base font-bold mb-2">{t('auto.PlayMode.k1')}</div>
              <div className="text-xs text-white/80 mb-3">{t('auto.PlayMode.no_video_preparing')}</div>
              <div className="text-xs text-white/80 leading-relaxed">
                {t('auto.PlayMode.no_video_cause_title')}<br />
                {t('auto.PlayMode.no_video_cause_1')}<br />
                {t('auto.PlayMode.no_video_cause_2')}<br />
                {t('auto.PlayMode.no_video_cause_3')}
              </div>
              {/* 再読み込みボタン (手動)。自動で 5 秒ごとにも再試行している。
                  タッチターゲット 44px を確保。 */}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); retryVideo() }}
                className="mt-4 inline-flex items-center gap-1.5 rounded font-bold ss-overlay-chip-accent shadow"
                style={{ minHeight: 44, padding: '0 1rem' }}
              >
                <MIcon name="refresh" size={18} />
                {t('auto.PlayMode.no_video_retry')}
              </button>
              <div className="text-[10px] text-white/60 mt-2">{t('auto.PlayMode.no_video_retrying')}</div>
              <div className="text-[10px] text-white/50 mt-3 font-mono break-all">
                {t('auto.PlayMode.match_id', { id: matchId })}
              </div>
            </div>
          </div>
        ) : (
          // <video> は **常時 mount**。
          // 当初 calib 中の中央タップ阻害を iOS native overlay と疑って unmount
          // したが、実際の犯人は __ss_error_bar__ (z=99999) で pe:none 修正済。
          // unmount すると `src` の再 load (HTTP Range + デコードバッファ再構築)
          // が走り、calib を閉じる度に "動画読み込み中" → 数秒のラグ + 帯域浪費。
          // 常時 mount にすればブラウザのバッファ・currentTime が保持され、
          // calib 出入りは無コストになる。
          // preload="auto" でアノテーション開始時にできる限り先読みさせる
          // (モバイル PWA は metered ネットワークの可能性あるが、アノテはローカル
          // LAN 経由想定なので積極的にバッファして良い)。
          <video
            ref={(el) => {
              videoRef.current = el
              if (el && !el.hasAttribute('webkit-playsinline')) {
                el.setAttribute('webkit-playsinline', '')
              }
            }}
            src={videoSrc}
            playsInline
            // preload="auto" は iOS Safari PWA で大量のバッファロード起動 +
            // メディア decoder スレッド占有で UI 応答性が壊滅する事象あり。
            // "metadata" に戻して、ブラウザ既定の playback buffer に任せる。
            // video element を unmount しなければ常識的な範囲で bufferd は保持。
            preload="metadata"
            style={cropStyle}
            onError={(e) => {
              const v = e.currentTarget
              const codeMap: Record<number, string> = {
                1: 'MEDIA_ERR_ABORTED',
                2: 'MEDIA_ERR_NETWORK',
                3: 'MEDIA_ERR_DECODE',
                4: 'MEDIA_ERR_SRC_NOT_SUPPORTED',
              }
              const detail = `video err ${codeMap[v.error?.code ?? -1] ?? v.error?.code} net=${v.networkState} ready=${v.readyState}`
              console.error('[mobile-annot] video error', detail, { src: v.src })
              setPlayError(detail)
            }}
          />
        )}

        {/* calib 中の snapshot img はもう画面に出さない (live video が下に
            常時表示されるため不要)。snapshot は MobileCourtCalib にルーペ用に
            渡すだけ。これにより calib 出入りで video の再 load が走らない。 */}

        {/* CV オーバーレイ (コートグリッド / シャトル軌跡 / プレイヤー bbox)
            video element の上に z-index 11/12/13 で重ねる。タップ透過させるので
            コートタップ判定 (= setScreen annotate) は阻害しない。 */}
        {!cropEditing && !calibEditing && videoBox.w > 0 && videoBox.h > 0 && (
          <MobileCVOverlay
            key={`cv-${calibVersion}`}
            matchId={matchId}
            currentSec={currentTime}
            videoWidth={videoBox.w}
            videoHeight={videoBox.h}
            showCourt={showCourt}
            showShuttle={showShuttle}
            showPlayers={showPlayers}
            // ⚠️ videoTransform は意図的に渡さない。
            // calib 中の snapshot は cropStyle (transform) 適用、calib SVG は
            // 非適用。なので点は "transform 後の見た目" 基準で norm 化される。
            // 確定後の grid にも transform を適用すると二重適用となり横に
            // 引き延ばされる。crop は calib 時と display 時で同一前提なので、
            // 両方とも grid は素の座標で描く方が整合する。
            // (crop を後から変更すると grid がズレるが、それは別途要対応)
          />
        )}

        {/* コートキャリブ編集 overlay (動画 pause 状態で 6 点設置 / 微調整) */}
        {calibEditing && videoBox.w > 0 && videoBox.h > 0 && (
          <MobileCourtCalib
            matchId={matchId}
            initial={calibPoints}
            videoWidth={videoBox.w}
            videoHeight={videoBox.h}
            snapshot={calibSnapshot}
            onClose={() => setCalibEditing(false)}
            onSaved={(pts) => {
              setCalibPoints(pts)
              setCalibVersion((n) => n + 1)
              setCalibEditing(false)
            }}
          />
        )}

        {/* クロップ編集 overlay: 現在の pending crop を視覚化 */}
        {cropEditing && (
          <>
            {/* 暗幕 (crop 外) */}
            <div
              className="absolute pointer-events-none border-2 border-yellow-400"
              style={{
                left: `${visibleCrop.x * 100}%`,
                top: `${visibleCrop.y * 100}%`,
                width: `${visibleCrop.w * 100}%`,
                height: `${visibleCrop.h * 100}%`,
                boxShadow: '0 0 0 9999px rgba(0,0,0,0.6)',
              }}
            />
            <div className="absolute top-2 left-2 right-2 text-center text-[11px] text-yellow-300 bg-black/60 rounded px-2 py-1">
              {t('auto.PlayMode.crop_drag_hint')}
            </div>
          </>
        )}

        {/* 「前回の続きから再開」chip — 既存ラリーがあって、現在の再生位置が
            最後のラリー終了時刻に近くないときだけ表示 */}
        {!cropEditing && resumeFromSec !== undefined && resumeFromSec > 1
          && Math.abs(currentTime - resumeFromSec) > 3 && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              const v = videoRef.current
              if (v) {
                try { v.currentTime = resumeFromSec } catch { /* ignore */ }
              }
            }}
            className="absolute left-2 z-30 px-2 py-1 rounded shadow text-[11px] font-mono ss-overlay-chip-accent"
            style={{ top: 'calc(max(0.5rem, env(safe-area-inset-top)) + 2.5rem)' }}
            title={t('auto.PlayMode.k4')}
          >
            {t('auto.PlayMode.resume_from', { time: fmt(resumeFromSec) })}
          </button>
        )}

        {/* iOS Safari フルスクリーン案内: requestFullscreen 非対応端末用 */}
        {iosFsHint && (
          <div
            className="absolute left-1/2 -translate-x-1/2 z-30 px-3 py-2 rounded shadow text-[11px] ss-overlay-chip"
            style={{ top: 'max(2.6rem, calc(env(safe-area-inset-top) + 2.2rem))', maxWidth: '90vw' }}
            onClick={(e) => { e.stopPropagation(); setIosFsHint(false) }}
          >
            {t('auto.PlayMode.ios_fs_hint_1')}
            <br />{t('auto.PlayMode.k2')} <b>{t('auto.PlayMode.k3')}</b> {t('auto.PlayMode.ios_fs_hint_2')}
          </div>
        )}

        {/* 再生エラー banner (β デバッグ用、原因不明な play 失敗を即視認できるよう
            画面上に表示する) */}
        {playError && (
          <div
            className="absolute left-1/2 -translate-x-1/2 z-30 px-3 py-1.5 rounded text-[11px] font-mono shadow ss-overlay-chip-danger"
            style={{ top: 'max(2.6rem, calc(env(safe-area-inset-top) + 2.2rem))' }}
            onClick={(e) => { e.stopPropagation(); setPlayError('') }}
          >
            {t('auto.PlayMode.play_error', { msg: playError })}
          </div>
        )}

        {/* 右上ツールクラスタ: house セマンティックトークンでテーマ自動切替。
            z-45 (= Pass1/2/3 overlay z-40 より上、calib editor z-50 より下)。
            set 1 未作成画面が出てもキャリブやフルスクリーンに到達できないと
            操作詰みになるため。
            NOTE: calib 編集中は隠す (= 編集集中、calib editor 自身に専用ボタンあり) */}
        {!calibEditing && (
        <div
          className="absolute right-2 flex gap-1"
          style={{ top: 'max(0.5rem, env(safe-area-inset-top))', zIndex: 45 }}
          // 親 containerRef の onClick (= 動画タップ → annotate モード) に伝播させない
          onClick={(e) => e.stopPropagation()}
          onTouchStart={(e) => e.stopPropagation()}
          onTouchEnd={(e) => e.stopPropagation()}
        >
          {!cropEditing ? (
            <>
              {/* オーバーレイトグル 3 種 (コート / シャトル / プレイヤー) */}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setShowCourt(!showCourt) }}
                className={`p-2 rounded shadow ${showCourt ? 'ss-overlay-chip-accent' : 'ss-overlay-chip'}`}
                aria-label={t('auto.PlayMode.k9')}
                title={t('auto.PlayMode.k5')}
              >
                <MIcon name="grid_on" size={16} />
              </button>
              {/* コートキャリブ編集 (動画 pause + 6 点設置 + 保存) */}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  const v = videoRef.current
                  if (v && !v.paused) v.pause()
                  // 現フレームを canvas に焼いて dataURL → MobileCourtCalib に渡し
                  // ルーペで指の真下を拡大表示する。
                  // ⚠️ canvas は **container サイズ** で作り、video の native frame
                  // (1920x1080 等) を objectFit:cover 相当に縮小+クロップして焼く。
                  // これで snapshot 1px = container 1px が成立 → ルーペ側で touch
                  // 座標をそのまま使える (objectFit による offset 計算不要)。
                  // 旧実装は snapshot を native サイズで作って ルーペ img に
                  // objectFit:cover を後付けしていたため、stage 内の box サイズ次第で
                  // cover の crop offset がズレ、左右タップで loupe 内容が大きくズレた。
                  try {
                    const cw = videoBox.w | 0
                    const ch = videoBox.h | 0
                    if (v && v.videoWidth > 0 && v.videoHeight > 0 && cw > 0 && ch > 0) {
                      const sw = v.videoWidth, sh = v.videoHeight
                      const cvs = document.createElement('canvas')
                      cvs.width = cw
                      cvs.height = ch
                      const ctx = cvs.getContext('2d')
                      if (ctx) {
                        // objectFit:cover 相当: video 全体を container を覆うよう
                        // 等比拡大 + 中央クロップ。
                        const scale = Math.max(cw / sw, ch / sh)
                        const dw = sw * scale
                        const dh = sh * scale
                        const dx = (cw - dw) / 2
                        const dy = (ch - dh) / 2
                        ctx.drawImage(v, 0, 0, sw, sh, dx, dy, dw, dh)
                        setCalibSnapshot(cvs.toDataURL('image/jpeg', 0.85))
                      }
                    }
                  } catch (err) {
                    console.warn('[calib] snapshot failed', err)
                  }
                  setCalibEditing(true)
                }}
                className="p-2 rounded shadow ss-overlay-chip"
                aria-label={t('auto.PlayMode.k10')}
                title={t('auto.PlayMode.k6')}
              >
                <MIcon name="edit" size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setShowShuttle(!showShuttle) }}
                className={`relative p-2 rounded shadow ${showShuttle ? 'ss-overlay-chip-accent' : 'ss-overlay-chip'}`}
                aria-label={t('auto.PlayMode.k11')}
                title={shuttleFrameCount > 0 ? `シャトル軌跡 (解析済 ${shuttleFrameCount} frames)` : 'シャトル軌跡表示切替 (未解析)'}
              >
                <MIcon name="my_location" size={16} />
                {shuttleFrameCount > 0 && (
                  // 解析済バッジ: 緑のドット + フレーム数。toggle OFF でも見える。
                  <span
                    className="absolute -top-1 -right-1 inline-flex items-center justify-center text-[8px] font-bold rounded-full"
                    style={{
                      minWidth: 14, height: 14, padding: '0 3px',
                      backgroundColor: '#16a34a', color: '#ffffff',
                      border: '1px solid #ffffff', lineHeight: 1,
                    }}
                  >
                    <MIcon name="check" size={9} />
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setShowPlayers(!showPlayers) }}
                className={`relative p-2 rounded shadow ${showPlayers ? 'ss-overlay-chip-accent' : 'ss-overlay-chip'}`}
                aria-label={t('auto.PlayMode.k12')}
                title={yoloFrameCount > 0 ? `プレイヤー位置 (解析済 ${yoloFrameCount} frames)` : 'プレイヤー位置 bbox 表示切替 (未解析)'}
              >
                <MIcon name="group" size={16} />
                {yoloFrameCount > 0 && (
                  <span
                    className="absolute -top-1 -right-1 inline-flex items-center justify-center text-[8px] font-bold rounded-full"
                    style={{
                      minWidth: 14, height: 14, padding: '0 3px',
                      backgroundColor: '#16a34a', color: '#ffffff',
                      border: '1px solid #ffffff', lineHeight: 1,
                    }}
                  >
                    <MIcon name="check" size={9} />
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setFitMode(fitMode === 'cover' ? 'contain' : 'cover') }}
                className="p-2 rounded shadow ss-overlay-chip"
                aria-label={t('auto.PlayMode.k13')}
                title={fitMode === 'cover' ? '全体表示 (contain) に切替' : 'フル表示 (cover) に切替'}
              >
                <MIcon name="crop_square" size={16} />
              </button>
              {/* Fullscreen ボタン: PWA standalone モードでは既にフル表示なので非表示。
                   通常 Safari でしか役に立たない (それでも iOS は <video> 以外 不可 → hint)。 */}
              {!isPwaStandalone && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); enterFullscreen() }}
                  className="p-2 rounded shadow ss-overlay-chip"
                  aria-label={t('auto.PlayMode.k14')}
                  title={t('auto.PlayMode.k7')}
                >
                  <MIcon name="fullscreen" size={16} />
                </button>
              )}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); startCropEdit() }}
                className="p-2 rounded shadow ss-overlay-chip"
                aria-label={t('auto.PlayMode.k15')}
                title={t('auto.PlayMode.k8')}
              >
                <MIcon name="content_cut" size={16} />
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); resetCrop() }}
                className="p-2 rounded shadow ss-overlay-chip"
                aria-label={t('auto.PlayMode.k16')}
              >
                <MIcon name="restart_alt" size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); cancelCrop() }}
                className="px-2 py-1 rounded text-xs shadow ss-overlay-chip"
              >
                {t('auto.PlayMode.cancel')}
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); commitCrop() }}
                className="px-2 py-1 rounded text-xs flex items-center gap-1 shadow ss-overlay-chip-accent"
              >
                <MIcon name="check" size={12} /> {t('auto.PlayMode.confirm')}
              </button>
            </>
          )}
        </div>
        )}
      </div>

      {/* 下部コントロールオーバーレイ: テーマ追従の chip 群。calib 中は隠す。 */}
      {!calibEditing && (
      <div
        className="absolute left-0 right-0 px-2 py-2 flex items-center gap-1.5 text-xs z-20"
        style={{ bottom: 'env(safe-area-inset-bottom)' }}
        onClick={(e) => e.stopPropagation()}
        onTouchStart={(e) => e.stopPropagation()}
      >
        <button type="button" onClick={() => seekBy(-5)}
                className="px-2 py-1 rounded shadow font-mono text-[11px] ss-overlay-chip">{t('auto.PlayMode.seek_back_5')}</button>
        <button type="button" onClick={() => seekBy(-1)}
                className="px-2 py-1 rounded shadow font-mono text-[11px] ss-overlay-chip">{t('auto.PlayMode.seek_back_1')}</button>
        <button type="button" onClick={togglePlay}
                className="px-2.5 py-1.5 rounded shadow flex items-center ss-overlay-chip-accent">
          {playing ? <MIcon name="pause" size={14} /> : <MIcon name="play_arrow" size={14} />}
        </button>
        <button type="button" onClick={() => seekBy(1)}
                className="px-2 py-1 rounded shadow font-mono text-[11px] ss-overlay-chip">1▶</button>
        <button type="button" onClick={() => seekBy(5)}
                className="px-2 py-1 rounded shadow font-mono text-[11px] ss-overlay-chip">5▶</button>
        <span className="font-mono text-[10px] mx-1 shrink-0 px-1.5 py-0.5 rounded ss-overlay-chip">
          {fmt(currentTime)} / {fmt(duration)}
        </span>
        {/* シーク bar + CV 候補マーカー (タップで該当時刻へ jump) */}
        <div className="flex-1 mx-1 relative h-5 flex items-center">
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={currentTime}
            onChange={onScrub}
            className="w-full ss-overlay-range"
            style={{ position: 'relative', zIndex: 2 }}
          />
          {/* CV candidate ドット: bar 上に分布。タップで video.currentTime にセット */}
          {duration > 0 && cvCandidateTimestamps && cvCandidateTimestamps.length > 0 && (
            <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 pointer-events-none" style={{ zIndex: 1, height: 6 }}>
              {cvCandidateTimestamps.map((t, i) => {
                const ratio = Math.max(0, Math.min(1, t / duration))
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      const v = videoRef.current
                      if (v) v.currentTime = t
                    }}
                    className="absolute -translate-x-1/2 rounded-full pointer-events-auto"
                    style={{
                      left: `${ratio * 100}%`,
                      top: -2,
                      width: 8,
                      height: 8,
                      backgroundColor: 'rgba(245,158,11,0.9)',
                      border: '1px solid rgba(0,0,0,0.5)',
                    }}
                    title={`候補 #${i + 1} @ ${t.toFixed(1)}s`}
                    aria-label={`候補 ${i + 1}`}
                  />
                )
              })}
            </div>
          )}
        </div>
        {/* 速度切替 */}
        {[0.5, 1, 1.5, 2].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSpeed(s)}
            className={`px-1.5 py-1 rounded text-[10px] font-mono shadow ${speed === s ? 'ss-overlay-chip-accent' : 'ss-overlay-chip'}`}
          >
            {t('auto.PlayMode.speed_x', { n: s })}
          </button>
        ))}
        {/* 画質切替: backend が 1080p/720p variant を生成済みなら選択肢に出す。
            ready=false (生成中) は disabled + 補助ラベル。 */}
        {qualities && qualities.length > 1 && onQualityChange && (
          <div className="flex gap-1">
            {qualities.map((q) => {
              const label =
                q.quality === 'source'
                  ? (q.height > 0 ? `${q.height}p` : 'src')
                  : q.quality === 'uhd'
                  ? '4K'
                  : q.quality === 'fhd'
                  ? '1080p'
                  : q.quality === 'hd'
                  ? '720p'
                  : String(q.quality)
              const isCurrent = (currentQuality || 'source') === q.quality
              return (
                <button
                  key={q.quality}
                  type="button"
                  disabled={!q.ready}
                  onClick={() => q.ready && requestQualityChange(q.quality)}
                  className={`px-1.5 py-1 rounded text-[10px] font-mono shadow ${isCurrent ? 'ss-overlay-chip-accent' : 'ss-overlay-chip'}`}
                  title={q.ready ? `画質 ${label}` : `画質 ${label} (準備中)`}
                  style={!q.ready ? { opacity: 0.5 } : undefined}
                >
                  {label}
                </button>
              )
            })}
          </div>
        )}
      </div>
      )}
    </div>
  )
}
