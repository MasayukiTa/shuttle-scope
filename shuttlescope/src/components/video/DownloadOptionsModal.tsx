/**
 * DownloadOptionsModal — 試合動画 DL 設定モーダル
 *
 * 用途:
 *   - MatchListPage / AnnotatorPage / 編集ページから「DL ボタン」で開く
 *   - タブ切替で 全部 / ピン留め (Phase 2) / 手入力 の 3 モード
 *   - 共通設定: 画質 / cookies.txt / video_password
 *
 * 切り抜きの背景:
 *   バドミントン Live は 3 時間配信で本試合 60 分のような構成が多く、
 *   全部 DL すると HDD/SSD を浪費する。`start_sec` / `end_sec` を yt-dlp の
 *   `download_ranges` callback に変換すると 5〜10 倍の容量効率になる。
 *
 * Phase 1 (本コミット):
 *   - 全部DL タブ (既存挙動の踏襲)
 *   - 手入力 タブ (HH:MM:SS - HH:MM:SS、推定サイズ表示)
 *   - cookies.txt / video_password / quality / cookie_browser を統合
 *
 * Phase 2 (後日):
 *   - ピン留めタブ (YouTube iframe + postMessage で `getCurrentTime` 取得)
 *   - chapters 自動取得 (yt-dlp metadata)
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Download, AlertCircle, Cookie, ChevronDown, Scissors } from 'lucide-react'
import { apiPost } from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'

// ── ヘルパ ───────────────────────────────────────────────────────────────────

/** "HH:MM:SS" / "MM:SS" / "SS" / "1.5h" → 秒。失敗時 NaN */
function parseTime(input: string): number {
  const s = input.trim()
  if (!s) return NaN
  // 1.5h / 30m / 90s 形式
  const unitMatch = s.match(/^(\d+(?:\.\d+)?)\s*([hms])$/i)
  if (unitMatch) {
    const v = parseFloat(unitMatch[1])
    const u = unitMatch[2].toLowerCase()
    return u === 'h' ? v * 3600 : u === 'm' ? v * 60 : v
  }
  // HH:MM:SS / MM:SS / SS
  const parts = s.split(':').map((p) => p.trim())
  if (parts.some((p) => p === '' || isNaN(Number(p)))) return NaN
  if (parts.length === 1) return Number(parts[0])
  if (parts.length === 2) return Number(parts[0]) * 60 + Number(parts[1])
  if (parts.length === 3) return Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2])
  return NaN
}

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return ''
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** 画質 → 概算 ビットレート (Mbps)。容量見積りに使う */
const QUALITY_KBPS: Record<string, number> = {
  '360': 1000, '480': 1500, '720': 4000, '1080': 8000, 'best': 12000,
}

function estimateSizeMB(quality: string, durationSec: number): number {
  const kbps = QUALITY_KBPS[quality] ?? 4000
  return Math.round((kbps * durationSec) / 8 / 1024)
}

// ── タブ定義 ─────────────────────────────────────────────────────────────────

type TabId = 'full' | 'manual' | 'pin'

const TABS: { id: TabId; label: string; hint?: string }[] = [
  { id: 'full',   label: '全部DL' },
  { id: 'pin',    label: 'ピン留め', hint: '(YouTube のみ、Phase 2)' },
  { id: 'manual', label: '手入力' },
]

// ── Props ────────────────────────────────────────────────────────────────────

interface Props {
  open: boolean
  onClose: () => void
  matchId: number
  /** 表示用ラベル: 試合名 / 大会 など */
  matchLabel?: string
  /** ダウンロード対象 URL */
  videoUrl: string
  /** DL 開始成功時のコールバック (job_id を返す) */
  onStarted?: (jobId: string) => void
  /** 既定値 */
  initialQuality?: string
  initialCookieBrowser?: string
  /** Electron loopback (cookie_browser 利用可) */
  isElectronLocal?: boolean
}

// ── 本体 ─────────────────────────────────────────────────────────────────────

export function DownloadOptionsModal({
  open,
  onClose,
  matchId,
  matchLabel,
  videoUrl,
  onStarted,
  initialQuality = '720',
  initialCookieBrowser = '',
  isElectronLocal = false,
}: Props) {
  const { t: _t } = useTranslation()
  const isLight = useIsLightMode()

  const [tab, setTab] = useState<TabId>('full')
  const [quality, setQuality] = useState(initialQuality)
  const [cookieBrowser, setCookieBrowser] = useState(initialCookieBrowser)
  const [cookiesTxt, setCookiesTxt] = useState('')
  const [cookiesFileName, setCookiesFileName] = useState('')
  const [cookiesError, setCookiesError] = useState('')
  const [videoPassword, setVideoPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [authPanelOpen, setAuthPanelOpen] = useState(false)

  // 範囲指定 (手入力タブ用)
  const [startInput, setStartInput] = useState('')
  const [endInput, setEndInput] = useState('')

  // submit
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  // ── 範囲算出 ──────────────────────────────────────────────────────────────
  const startSec = useMemo(() => {
    if (tab !== 'manual') return null
    const v = parseTime(startInput)
    return Number.isFinite(v) && v >= 0 ? v : null
  }, [tab, startInput])

  const endSec = useMemo(() => {
    if (tab !== 'manual') return null
    const v = parseTime(endInput)
    return Number.isFinite(v) && v > 0 ? v : null
  }, [tab, endInput])

  const rangeSeconds = useMemo(() => {
    if (tab === 'manual' && startSec !== null && endSec !== null) {
      return Math.max(0, endSec - startSec)
    }
    return null
  }, [tab, startSec, endSec])

  const rangeError = useMemo(() => {
    if (tab !== 'manual') return ''
    if (startInput && startSec === null) return '開始時刻の形式が不正です'
    if (endInput && endSec === null) return '終了時刻の形式が不正です'
    if (startSec !== null && endSec !== null && startSec >= endSec) {
      return '開始 < 終了になるよう指定してください'
    }
    return ''
  }, [tab, startInput, endInput, startSec, endSec])

  // ── ESC で閉じる ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  // ── cookies.txt 読み込み ──────────────────────────────────────────────────
  const handleCookiesFile = useCallback(async (file: File | null) => {
    setCookiesError('')
    if (!file) {
      setCookiesTxt('')
      setCookiesFileName('')
      return
    }
    if (file.size > 1024 * 1024) {
      setCookiesError('cookies.txt は 1MB 以下にしてください')
      return
    }
    try {
      const text = await file.text()
      if (!/Netscape HTTP Cookie File/i.test(text) && !/^# /m.test(text)) {
        setCookiesError('Netscape 形式の cookies.txt ではないようです')
        return
      }
      setCookiesTxt(text)
      setCookiesFileName(file.name)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'ファイル読み込みに失敗しました'
      setCookiesError(msg)
    }
  }, [])

  // ── 送信 ──────────────────────────────────────────────────────────────────
  const handleSubmit = useCallback(async () => {
    if (rangeError) {
      setSubmitError(rangeError)
      return
    }
    setSubmitError('')
    setSubmitting(true)
    try {
      const body: Record<string, unknown> = {
        quality,
        cookie_browser: isElectronLocal ? cookieBrowser : '',
      }
      if (cookiesTxt.trim()) body.cookies_txt = cookiesTxt
      if (videoPassword) body.video_password = videoPassword
      if (tab === 'manual') {
        if (startSec !== null) body.start_sec = startSec
        if (endSec !== null) body.end_sec = endSec
      }
      const res = await apiPost<{ success: boolean; data: { job_id: string } }>(
        `/matches/${matchId}/download`,
        body,
      )
      const jobId = res?.data?.job_id ?? ''
      onStarted?.(jobId)
      onClose()
    } catch (err: unknown) {
      let msg = 'ダウンロード開始に失敗しました'
      if (err instanceof Error) {
        try {
          const parsed = JSON.parse(err.message)
          const d = parsed?.detail
          if (typeof d === 'string') msg = d
          else if (Array.isArray(d)) {
            msg = d.map((e) => e?.msg ?? JSON.stringify(e)).join('; ')
          } else if (d) msg = JSON.stringify(d)
          else msg = err.message
        } catch {
          msg = err.message
        }
      }
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }, [rangeError, quality, isElectronLocal, cookieBrowser, cookiesTxt, videoPassword, tab, startSec, endSec, matchId, onStarted, onClose])

  if (!open) return null

  // ── スタイル ──────────────────────────────────────────────────────────────
  const panelBg     = isLight ? 'bg-white border border-gray-200' : 'bg-gray-800 border border-gray-700'
  const headerBg    = isLight ? 'border-b border-gray-200' : 'border-b border-gray-700'
  const tabActive   = isLight ? 'bg-blue-600 text-white' : 'bg-blue-600 text-white'
  const tabInactive = isLight ? 'bg-gray-100 text-gray-700 hover:bg-gray-200' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
  const labelColor  = isLight ? 'text-gray-700' : 'text-gray-300'
  const muteColor   = isLight ? 'text-gray-500' : 'text-gray-400'
  const inputCls    = isLight
    ? 'bg-white border border-gray-300 text-gray-900'
    : 'bg-gray-700 border border-gray-600 text-gray-100'

  return (
    <div
      className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="download-modal-title"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className={`${panelBg} rounded-lg w-full max-w-xl max-h-[90vh] flex flex-col`}>
        {/* ヘッダー */}
        <div className={`flex items-center justify-between px-5 py-3 ${headerBg}`}>
          <div className="flex items-center gap-2 min-w-0">
            <Download size={18} className="text-blue-400 shrink-0" />
            <div className="min-w-0">
              <h2 id="download-modal-title" className="text-base font-semibold truncate">
                動画ダウンロード
              </h2>
              {matchLabel && (
                <p className={`text-xs truncate ${muteColor}`}>{matchLabel}</p>
              )}
            </div>
          </div>
          <button onClick={onClose} aria-label="閉じる" className={muteColor + ' hover:opacity-80'}>
            <X size={18} />
          </button>
        </div>

        {/* URL 表示 */}
        <div className={`px-5 py-2 text-xs font-mono truncate ${muteColor}`}>{videoUrl}</div>

        {/* タブ */}
        <div className="px-5 pt-1 flex gap-1.5">
          {TABS.map((tabDef) => (
            <button
              key={tabDef.id}
              onClick={() => tabDef.id !== 'pin' && setTab(tabDef.id)}
              disabled={tabDef.id === 'pin'}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                tab === tabDef.id ? tabActive : tabInactive
              }`}
              title={tabDef.hint}
              aria-selected={tab === tabDef.id}
            >
              {tabDef.label}
              {tabDef.hint && <span className="ml-1 text-[10px] opacity-70">{tabDef.hint}</span>}
            </button>
          ))}
        </div>

        {/* タブ本体 */}
        <div className="px-5 py-3 flex-1 overflow-y-auto flex flex-col gap-3">
          {tab === 'full' && (
            <div className={`text-sm ${labelColor}`}>
              <p>動画全体をダウンロードします。</p>
              <p className={`text-xs mt-1 ${muteColor}`}>
                Live 配信が長時間 (3時間以上) の場合は<strong>「手入力」タブ</strong>で範囲を指定すると容量を節約できます。
              </p>
            </div>
          )}

          {tab === 'manual' && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <Scissors size={14} className={muteColor} />
                <span className={`text-sm ${labelColor}`}>切り抜き範囲 (HH:MM:SS / MM:SS / 秒)</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1">
                  <span className={`text-xs ${muteColor}`}>開始</span>
                  <input
                    type="text"
                    value={startInput}
                    onChange={(e) => setStartInput(e.target.value)}
                    placeholder="00:30:00"
                    className={`text-sm rounded px-2 py-1.5 ${inputCls}`}
                    aria-label="開始時刻"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className={`text-xs ${muteColor}`}>終了</span>
                  <input
                    type="text"
                    value={endInput}
                    onChange={(e) => setEndInput(e.target.value)}
                    placeholder="01:30:00"
                    className={`text-sm rounded px-2 py-1.5 ${inputCls}`}
                    aria-label="終了時刻"
                  />
                </label>
              </div>
              {/* 範囲・推定サイズ */}
              {rangeSeconds !== null && (
                <div className={`text-xs ${muteColor}`}>
                  範囲: <strong>{formatTime(rangeSeconds)}</strong>
                  {' '}(約 {rangeSeconds.toFixed(0)} 秒)
                  {' / '}推定サイズ: <strong>~{estimateSizeMB(quality, rangeSeconds)} MB</strong>
                  {' '}({quality === 'best' ? 'best' : `${quality}p`} 想定)
                </div>
              )}
              {rangeError && (
                <div className="text-xs text-red-500">{rangeError}</div>
              )}
            </div>
          )}

          {tab === 'pin' && (
            <div className={`text-sm ${labelColor}`}>
              <p>ピン留め (YouTube iframe で再生中の位置を ▶開始 / ■終了 でピン留め) は Phase 2 で実装予定です。</p>
              <p className={`text-xs mt-1 ${muteColor}`}>
                現状は「手入力」タブで HH:MM:SS を指定してください。
              </p>
            </div>
          )}

          {/* 共通: 画質 */}
          <div className="flex items-center gap-2">
            <label className={`text-sm ${labelColor}`}>画質</label>
            <select
              value={quality}
              onChange={(e) => setQuality(e.target.value)}
              className={`text-sm rounded px-2 py-1 ${inputCls}`}
            >
              <option value="360">360p</option>
              <option value="480">480p</option>
              <option value="720">720p</option>
              <option value="1080">1080p</option>
              <option value="best">最高画質</option>
            </select>
          </div>

          {/* 共通: cookie_browser (Electron loopback のみ) */}
          {isElectronLocal && (
            <div className="flex items-center gap-2">
              <Cookie size={14} className={muteColor} />
              <label className={`text-sm ${labelColor}`}>Cookie ブラウザ</label>
              <select
                value={cookieBrowser}
                onChange={(e) => setCookieBrowser(e.target.value)}
                className={`text-sm rounded px-2 py-1 flex-1 ${inputCls}`}
              >
                <option value="">使用しない</option>
                <option value="chrome">Chrome</option>
                <option value="edge">Edge</option>
                <option value="firefox">Firefox</option>
                <option value="brave">Brave</option>
              </select>
            </div>
          )}

          {/* 共通: cookies.txt + 動画パスワード (折りたたみ) */}
          <button
            type="button"
            onClick={() => setAuthPanelOpen((v) => !v)}
            className={`text-xs flex items-center gap-1 self-start ${muteColor}`}
            aria-expanded={authPanelOpen}
          >
            <ChevronDown size={12} className={authPanelOpen ? 'rotate-0' : '-rotate-90'} />
            会員限定サイト・パスワード保護動画
            {(cookiesFileName || videoPassword) && (
              <span className={`text-[10px] ${isLight ? 'text-emerald-600' : 'text-emerald-400'}`}>
                ✓ 設定済
              </span>
            )}
          </button>
          {authPanelOpen && (
            <div className="flex flex-col gap-2 pl-4 border-l border-dashed" style={{ borderColor: isLight ? '#cbd5e1' : '#374151' }}>
              {/* cookies.txt */}
              <div className="flex flex-col gap-1">
                <span className={`text-xs ${muteColor}`}>cookies.txt (Netscape 形式、1MB 以下)</span>
                <div className="flex items-center gap-2">
                  <input
                    type="file"
                    accept=".txt,text/plain"
                    onChange={(e) => handleCookiesFile(e.target.files?.[0] ?? null)}
                    className={`text-xs flex-1 ${labelColor}`}
                  />
                  {cookiesFileName && (
                    <button
                      type="button"
                      onClick={() => handleCookiesFile(null)}
                      className={`text-[10px] px-2 py-1 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300' : 'bg-gray-700 hover:bg-gray-600'}`}
                    >
                      ✕
                    </button>
                  )}
                </div>
                {cookiesFileName && !cookiesError && (
                  <div className={`text-[10px] ${isLight ? 'text-emerald-600' : 'text-emerald-400'}`}>
                    ✓ {cookiesFileName} ({Math.round(cookiesTxt.length / 1024)} KB)
                  </div>
                )}
                {cookiesError && (
                  <div className="text-[10px] text-red-500">⚠ {cookiesError}</div>
                )}
              </div>

              {/* video_password */}
              <div className="flex flex-col gap-1">
                <span className={`text-xs ${muteColor}`}>動画パスワード (Vimeo Showcase 等)</span>
                <div className="flex items-center gap-2">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={videoPassword}
                    onChange={(e) => setVideoPassword(e.target.value)}
                    placeholder="動画パスワード"
                    autoComplete="off"
                    maxLength={1024}
                    className={`text-sm rounded px-2 py-1 flex-1 ${inputCls}`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className={`text-[10px] px-2 py-1 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300' : 'bg-gray-700 hover:bg-gray-600'}`}
                  >
                    {showPassword ? '隠す' : '表示'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* エラー */}
          {submitError && (
            <div className="flex items-start gap-1.5 text-xs text-red-500">
              <AlertCircle size={12} className="shrink-0 mt-0.5" />
              <span className="break-words">{submitError}</span>
            </div>
          )}
        </div>

        {/* フッタ: 送信ボタン */}
        <div className={`px-5 py-3 flex items-center justify-end gap-2 ${headerBg}`}>
          <button
            onClick={onClose}
            className={`text-sm px-3 py-1.5 rounded ${
              isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-700' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
            }`}
          >
            キャンセル
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || !!rangeError || (tab === 'manual' && (startSec === null && endSec === null))}
            className="text-sm px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-medium flex items-center gap-1.5"
          >
            <Download size={14} />
            {submitting ? '開始中...' : tab === 'manual' ? '範囲をダウンロード' : 'ダウンロード'}
          </button>
        </div>
      </div>
    </div>
  )
}
