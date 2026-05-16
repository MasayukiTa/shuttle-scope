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
import { useEffect, useRef, useState, useCallback } from 'react'
import { Play, Pause, Scissors, RotateCcw, Check, Maximize2, Square, Grid3x3, Target, Users, Pencil } from 'lucide-react'
import { MobileCVOverlay } from '@/components/mobileAnnotate/MobileCVOverlay'
import { MobileCourtCalib } from '@/components/mobileAnnotate/MobileCourtCalib'

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
}

export function PlayMode({ matchId, videoSrc, onTapVideo, videoElRef, qualities, currentQuality, onQualityChange, cvCandidateTimestamps, resumeFromSec }: Props) {
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
  // CV オーバーレイの可視性 (個別 toggle で重ね描きの ON/OFF 切替可能)
  const [showCourt, setShowCourt] = useState(true)
  const [showShuttle, setShowShuttle] = useState(true)
  const [showPlayers, setShowPlayers] = useState(false)  // bbox は視認性影響大なので default OFF
  // コートキャリブ編集モード
  const [calibEditing, setCalibEditing] = useState(false)
  // 既存キャリブ点 (編集モードに渡す初期値 + 保存後に上書き)
  const [calibPoints, setCalibPoints] = useState<{ x: number; y: number }[]>([])
  // 保存後に MobileCVOverlay を強制再 fetch させる version カウンタ
  const [calibVersion, setCalibVersion] = useState(0)

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
    const target: any = document.documentElement
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
          // 動画タップ = pause + Annotate mode へ
          if (cropEditing) return
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
              <div className="text-base font-bold mb-2">動画が再生できません</div>
              <div className="text-xs text-white/80 leading-relaxed">
                考えられる原因:<br />
                ・この試合にまだ動画が登録されていない<br />
                ・動画 token (video_token) が発行されていない<br />
                ・サーバから動画ファイルが取得できない
              </div>
              <div className="text-[10px] text-white/50 mt-3 font-mono break-all">
                match_id={matchId}
              </div>
            </div>
          </div>
        ) : (
          <video
            ref={(el) => {
              videoRef.current = el
              // iOS Safari の旧版互換属性 (TS の型に無いので ref で setAttribute)
              if (el && !el.hasAttribute('webkit-playsinline')) {
                el.setAttribute('webkit-playsinline', '')
              }
            }}
            src={videoSrc}
            playsInline
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
          />
        )}

        {/* コートキャリブ編集 overlay (動画 pause 状態で 6 点設置 / 微調整) */}
        {calibEditing && videoBox.w > 0 && videoBox.h > 0 && (
          <MobileCourtCalib
            matchId={matchId}
            initial={calibPoints}
            videoWidth={videoBox.w}
            videoHeight={videoBox.h}
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
              切り抜き範囲をドラッグで指定 → 右下 ✓ で確定
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
            title="前回ラリー終了位置に seek"
          >
            ▶ {fmt(resumeFromSec)} から再開
          </button>
        )}

        {/* iOS Safari フルスクリーン案内: requestFullscreen 非対応端末用 */}
        {iosFsHint && (
          <div
            className="absolute left-1/2 -translate-x-1/2 z-30 px-3 py-2 rounded shadow text-[11px] ss-overlay-chip"
            style={{ top: 'max(2.6rem, calc(env(safe-area-inset-top) + 2.2rem))', maxWidth: '90vw' }}
            onClick={(e) => { e.stopPropagation(); setIosFsHint(false) }}
          >
            iPhone Safari は要素単位の全画面非対応です。
            <br />Safari 共有ボタン → <b>「ホーム画面に追加」</b> で PWA 起動すると
            URL バー無しの本物フルスクリーンになります。(タップで閉じる)
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
            {playError} (タップで閉じる)
          </div>
        )}

        {/* 右上ツールクラスタ: house セマンティックトークンでテーマ自動切替 */}
        <div
          className="absolute right-2 flex gap-1 z-20"
          style={{ top: 'max(0.5rem, env(safe-area-inset-top))' }}
        >
          {!cropEditing ? (
            <>
              {/* オーバーレイトグル 3 種 (コート / シャトル / プレイヤー) */}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setShowCourt(!showCourt) }}
                className={`p-2 rounded shadow ${showCourt ? 'ss-overlay-chip-accent' : 'ss-overlay-chip'}`}
                aria-label="コートグリッド"
                title="コートグリッド表示切替"
              >
                <Grid3x3 size={16} />
              </button>
              {/* コートキャリブ編集 (動画 pause + 6 点設置 + 保存) */}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  const v = videoRef.current
                  if (v && !v.paused) v.pause()
                  setCalibEditing(true)
                }}
                className="p-2 rounded shadow ss-overlay-chip"
                aria-label="コートキャリブ編集"
                title="コート 4 隅 + ネット 2 点を設置 / 微調整"
              >
                <Pencil size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setShowShuttle(!showShuttle) }}
                className={`p-2 rounded shadow ${showShuttle ? 'ss-overlay-chip-accent' : 'ss-overlay-chip'}`}
                aria-label="シャトル軌跡"
                title="シャトル軌跡表示切替"
              >
                <Target size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setShowPlayers(!showPlayers) }}
                className={`p-2 rounded shadow ${showPlayers ? 'ss-overlay-chip-accent' : 'ss-overlay-chip'}`}
                aria-label="プレイヤー位置"
                title="プレイヤー位置 bbox 表示切替"
              >
                <Users size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setFitMode(fitMode === 'cover' ? 'contain' : 'cover') }}
                className="p-2 rounded shadow ss-overlay-chip"
                aria-label="表示モード切替"
                title={fitMode === 'cover' ? '全体表示 (contain) に切替' : 'フル表示 (cover) に切替'}
              >
                <Square size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); enterFullscreen() }}
                className="p-2 rounded shadow ss-overlay-chip"
                aria-label="フルスクリーン"
                title="iOS native フルスクリーンに入る"
              >
                <Maximize2 size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); startCropEdit() }}
                className="p-2 rounded shadow ss-overlay-chip"
                aria-label="切り抜き編集"
                title="鳥瞰カメラの不要部分を切り抜く"
              >
                <Scissors size={16} />
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); resetCrop() }}
                className="p-2 rounded shadow ss-overlay-chip"
                aria-label="全画面に戻す"
              >
                <RotateCcw size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); cancelCrop() }}
                className="px-2 py-1 rounded text-xs shadow ss-overlay-chip"
              >
                取消
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); commitCrop() }}
                className="px-2 py-1 rounded text-xs flex items-center gap-1 shadow ss-overlay-chip-accent"
              >
                <Check size={12} /> 確定
              </button>
            </>
          )}
        </div>
      </div>

      {/* 下部コントロールオーバーレイ: テーマ追従の chip 群 */}
      <div
        className="absolute left-0 right-0 px-2 py-2 flex items-center gap-1.5 text-xs z-20"
        style={{ bottom: 'env(safe-area-inset-bottom)' }}
        onClick={(e) => e.stopPropagation()}
        onTouchStart={(e) => e.stopPropagation()}
      >
        <button type="button" onClick={() => seekBy(-5)}
                className="px-2 py-1 rounded shadow font-mono text-[11px] ss-overlay-chip">◀◀5</button>
        <button type="button" onClick={() => seekBy(-1)}
                className="px-2 py-1 rounded shadow font-mono text-[11px] ss-overlay-chip">◀1</button>
        <button type="button" onClick={togglePlay}
                className="px-2.5 py-1.5 rounded shadow flex items-center ss-overlay-chip-accent">
          {playing ? <Pause size={14} /> : <Play size={14} />}
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
            {s}x
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
    </div>
  )
}
