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
import { Play, Pause, Scissors, RotateCcw, Check, Maximize2, Square } from 'lucide-react'

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


interface Props {
  matchId: string | number
  videoSrc: string
  /** 動画タップ時に呼ばれる (Annotate mode への切替 trigger) */
  onTapVideo: (currentTime: number) => void
  /** 動画再生時間取得 / 操作のため、親に ref を渡したい場合に */
  videoElRef?: (el: HTMLVideoElement | null) => void
}

export function PlayMode({ matchId, videoSrc, onTapVideo, videoElRef }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [speed, setSpeed] = useState(1)
  const [crop, setCrop] = useState<CropRect>(() => loadCrop(matchId))
  const [cropEditing, setCropEditing] = useState(false)
  const [pendingCrop, setPendingCrop] = useState<CropRect>(crop)
  // cover = 動画で viewport を埋める (フル幅、上下 crop)。contain = レターボックスで全面表示。
  // モバイルアノテはコート中央を大きく見たいので cover を default。
  const [fitMode, setFitMode] = useState<'cover' | 'contain'>('cover')

  // 親に videoRef を露出
  useEffect(() => {
    videoElRef?.(videoRef.current)
    return () => { videoElRef?.(null) }
  }, [videoElRef])

  // playback rate
  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = speed
  }, [speed])

  // events
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onTime = () => setCurrentTime(v.currentTime)
    const onMeta = () => setDuration(v.duration || 0)
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
    if (v.paused) v.play().catch(() => {})
    else v.pause()
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

  // iOS Safari native fullscreen.
  // 仕様: webkitEnterFullscreen() は HAVE_METADATA (readyState >= 1) 以上、かつ
  // ユーザ gesture コンテキストで呼ぶ必要がある。metadata 未取得なら play() を
  // 試みて load を強制してから、loadedmetadata イベントで再試行する。
  // 加えて iOS は <video controls> でないと UI が出ないので、フルスクリーン突入
  // 時に controls を一時的に true にしておく (ネイティブプレーヤーで戻る/再生
  // が可能になる)。
  const enterFullscreen = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    v.controls = true
    const anyV = v as any
    const tryGo = () => {
      try {
        if (anyV.webkitEnterFullscreen) {
          anyV.webkitEnterFullscreen()
          return true
        }
        if (v.requestFullscreen) {
          void v.requestFullscreen().catch(() => {})
          return true
        }
      } catch {}
      return false
    }
    if (v.readyState >= 1) {
      tryGo()
      return
    }
    // readyState 0 (HAVE_NOTHING): metadata 未取得 → load() で強制取得して
    // loadedmetadata 受信後に再試行
    const onMeta = () => {
      v.removeEventListener('loadedmetadata', onMeta)
      tryGo()
    }
    v.addEventListener('loadedmetadata', onMeta)
    try { v.load() } catch {}
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
              // β 中に拾うため console に詳細
              console.error('[mobile-annot] video error', {
                error: v.error?.code,
                networkState: v.networkState,
                readyState: v.readyState,
                src: v.src,
              })
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

        {/* 右上ツールクラスタ: 白基調 (動画背景は何色でも来るので濃いアイコンで
            高コントラスト)。アクセントは橙 (ダーク青の house violation を避ける) */}
        <div
          className="absolute right-2 flex gap-1 z-20"
          style={{ top: 'max(0.5rem, env(safe-area-inset-top))' }}
        >
          {!cropEditing ? (
            <>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setFitMode(fitMode === 'cover' ? 'contain' : 'cover') }}
                className="p-2 rounded shadow"
                style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}
                aria-label="表示モード切替"
                title={fitMode === 'cover' ? '全体表示 (contain) に切替' : 'フル表示 (cover) に切替'}
              >
                <Square size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); enterFullscreen() }}
                className="p-2 rounded shadow"
                style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}
                aria-label="フルスクリーン"
                title="iOS native フルスクリーンに入る"
              >
                <Maximize2 size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); startCropEdit() }}
                className="p-2 rounded shadow"
                style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}
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
                className="p-2 rounded shadow"
                style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}
                aria-label="全画面に戻す"
              >
                <RotateCcw size={16} />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); cancelCrop() }}
                className="px-2 py-1 rounded text-xs shadow"
                style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}
              >
                取消
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); commitCrop() }}
                className="px-2 py-1 rounded text-xs flex items-center gap-1 shadow"
                style={{ backgroundColor: 'rgba(245,158,11,0.98)', color: '#ffffff' }}
              >
                <Check size={12} /> 確定
              </button>
            </>
          )}
        </div>
      </div>

      {/* 下部コントロールオーバーレイ: 白チップ + 橙アクセント (house style) */}
      <div
        className="absolute left-0 right-0 px-2 py-2 flex items-center gap-1.5 text-xs z-20"
        style={{ bottom: 'env(safe-area-inset-bottom)' }}
        onClick={(e) => e.stopPropagation()}
        onTouchStart={(e) => e.stopPropagation()}
      >
        <button type="button" onClick={() => seekBy(-5)}
                className="px-2 py-1 rounded shadow font-mono text-[11px]"
                style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}>◀◀5</button>
        <button type="button" onClick={() => seekBy(-1)}
                className="px-2 py-1 rounded shadow font-mono text-[11px]"
                style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}>◀1</button>
        <button type="button" onClick={togglePlay}
                className="px-2.5 py-1.5 rounded shadow flex items-center"
                style={{ backgroundColor: 'rgba(245,158,11,0.98)', color: '#ffffff' }}>
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <button type="button" onClick={() => seekBy(1)}
                className="px-2 py-1 rounded shadow font-mono text-[11px]"
                style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}>1▶</button>
        <button type="button" onClick={() => seekBy(5)}
                className="px-2 py-1 rounded shadow font-mono text-[11px]"
                style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}>5▶</button>
        <span
          className="font-mono text-[10px] mx-1 shrink-0 px-1.5 py-0.5 rounded"
          style={{ backgroundColor: 'rgba(255,255,255,0.85)', color: '#0f172a' }}
        >
          {fmt(currentTime)} / {fmt(duration)}
        </span>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime}
          onChange={onScrub}
          className="flex-1 mx-1"
          style={{ accentColor: '#f59e0b' }}
        />
        {/* 速度切替 */}
        {[0.5, 1, 1.5, 2].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSpeed(s)}
            className="px-1.5 py-1 rounded text-[10px] font-mono shadow"
            style={{
              backgroundColor: speed === s ? 'rgba(245,158,11,0.98)' : 'rgba(255,255,255,0.95)',
              color: speed === s ? '#ffffff' : '#0f172a',
            }}
          >
            {s}x
          </button>
        ))}
      </div>
    </div>
  )
}
