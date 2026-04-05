/**
 * 配信URLダウンロードパネル
 *
 * YouTube / Twitter / Bilibili / ニコニコ動画 / 登録制配信サイト など、
 * Electron で直接再生できない配信URLを検出したときに表示する。
 *
 * yt-dlp でダウンロードし、完了後は localfile:// 経由でローカル再生に自動切替する。
 * ログイン必須サイトは「Cookieブラウザ」で使用ブラウザを選択すると、
 * そのブラウザのCookieを自動取得して認証を通過できる。
 */
import { useState, useEffect, useCallback } from 'react'
import { Download, AlertCircle, CheckCircle, Loader2, Film, Cookie, ChevronDown } from 'lucide-react'
import { apiGet, apiPost } from '@/api/client'

interface StreamingDownloadPanelProps {
  /** 配信URL（表示 + ダウンロード元） */
  url: string
  /** 試合ID（ダウンロードAPI に使用） */
  matchId: string
  /** 検出されたサービス名（YouTube, Bilibili など） */
  siteName: string
  /** ダウンロード完了後に呼ばれるコールバック（match データ再取得を期待） */
  onDownloadComplete: () => void
}

type DLState = 'idle' | 'starting' | 'downloading' | 'processing' | 'complete' | 'error'

interface ProgressInfo {
  percent: string
  speed: string
  eta: string
}

const QUALITY_OPTIONS = [
  { value: '360', label: '360p' },
  { value: '480', label: '480p' },
  { value: '720', label: '720p（推奨）' },
  { value: '1080', label: '1080p' },
  { value: 'best', label: '最高画質' },
]

const COOKIE_BROWSER_OPTIONS = [
  { value: '', label: 'なし（公開動画）' },
  { value: 'chrome', label: 'Chrome' },
  { value: 'edge', label: 'Edge' },
  { value: 'firefox', label: 'Firefox' },
  { value: 'brave', label: 'Brave' },
  { value: 'opera', label: 'Opera' },
  { value: 'vivaldi', label: 'Vivaldi' },
  { value: 'chromium', label: 'Chromium' },
]

export function StreamingDownloadPanel({
  url,
  matchId,
  siteName,
  onDownloadComplete,
}: StreamingDownloadPanelProps) {
  const [quality, setQuality] = useState('720')
  const [cookieBrowser, setCookieBrowser] = useState('')
  const [dlState, setDlState] = useState<DLState>('idle')
  const [jobId, setJobId] = useState<string | null>(null)
  const [progress, setProgress] = useState<ProgressInfo>({ percent: '0%', speed: '', eta: '' })
  const [errorMsg, setErrorMsg] = useState('')

  // ── ダウンロード進捗ポーリング ──────────────────────────────────────────────
  useEffect(() => {
    if (!jobId || (dlState !== 'downloading' && dlState !== 'processing' && dlState !== 'starting')) return

    const poll = setInterval(async () => {
      try {
        const res = await apiGet<{
          success: boolean
          data: {
            status: string
            percent?: string
            speed?: string
            eta?: string
            error?: string
          }
        }>(`/matches/${matchId}/download/status`, { job_id: jobId })

        const d = res.data
        switch (d.status) {
          case 'complete':
            clearInterval(poll)
            setDlState('complete')
            setTimeout(onDownloadComplete, 800)
            break
          case 'error':
            clearInterval(poll)
            setDlState('error')
            setErrorMsg(d.error ?? '不明なエラー')
            break
          case 'downloading':
            setDlState('downloading')
            setProgress({
              percent: d.percent ?? '0%',
              speed: d.speed ?? '',
              eta: d.eta ?? '',
            })
            break
          case 'processing':
            setDlState('processing')
            break
          // pending / unknown は次のポーリングまで待機
        }
      } catch {
        // ネットワークエラーはスキップ
      }
    }, 1500)

    return () => clearInterval(poll)
  }, [jobId, dlState, matchId, onDownloadComplete])

  // ── ダウンロード開始 ────────────────────────────────────────────────────────
  const handleDownload = useCallback(async () => {
    setDlState('starting')
    setErrorMsg('')
    try {
      const res = await apiPost<{ success: boolean; data: { job_id: string } }>(
        `/matches/${matchId}/download`,
        { quality, cookie_browser: cookieBrowser }
      )
      setJobId(res.data.job_id)
      setDlState('downloading')
    } catch (err: any) {
      setDlState('error')
      setErrorMsg(err?.message ?? 'ダウンロード開始に失敗しました')
    }
  }, [matchId, quality, cookieBrowser])

  // ── リセット ────────────────────────────────────────────────────────────────
  const handleRetry = useCallback(() => {
    setDlState('idle')
    setJobId(null)
    setProgress({ percent: '0%', speed: '', eta: '' })
    setErrorMsg('')
  }, [])

  const isActive = dlState === 'starting' || dlState === 'downloading' || dlState === 'processing'
  const percentNum = Math.max(0, Math.min(100, parseFloat(progress.percent) || 0))
  const showCookieHint = !!cookieBrowser

  return (
    <div
      className="flex flex-col gap-3 bg-gray-800 rounded-lg overflow-hidden"
      style={{ aspectRatio: '16/9', justifyContent: 'center', padding: '20px 24px' }}
    >
      {/* ── サービス名 + URL ── */}
      <div className="flex items-center gap-2 flex-wrap">
        <Film size={16} className="text-blue-400 shrink-0" />
        <span className="text-sm font-semibold text-white">{siteName}</span>
        <span className="text-xs text-gray-500">配信URL</span>
      </div>

      <div className="text-xs text-gray-400 font-mono bg-gray-900/60 rounded px-2 py-1.5 truncate">
        {url}
      </div>

      {/* ── 説明バナー ── */}
      <div className="flex items-start gap-2 text-xs text-yellow-300 bg-yellow-900/20 border border-yellow-700/40 rounded p-2">
        <AlertCircle size={13} className="shrink-0 mt-0.5" />
        <span>
          配信URLはElectronで直接再生できません。yt-dlpでダウンロードしてから再生します。
          ログイン必須サイトは「Cookieブラウザ」を選択してください。
        </span>
      </div>

      {/* ── 完了 ── */}
      {dlState === 'complete' && (
        <div className="flex items-center gap-2 text-sm text-green-400 bg-green-900/20 border border-green-700/40 rounded p-3">
          <CheckCircle size={16} />
          <span>ダウンロード完了！再生を開始します...</span>
        </div>
      )}

      {/* ── エラー ── */}
      {dlState === 'error' && (
        <div className="flex flex-col gap-2">
          <div className="flex items-start gap-2 text-xs text-red-300 bg-red-900/20 border border-red-700/40 rounded p-2">
            <AlertCircle size={13} className="shrink-0 mt-0.5" />
            <span className="whitespace-pre-wrap break-all">{errorMsg}</span>
          </div>
          <button
            onClick={handleRetry}
            className="text-xs text-gray-400 hover:text-white underline text-left"
          >
            やり直す
          </button>
        </div>
      )}

      {/* ── 進捗バー（ダウンロード中） ── */}
      {isActive && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs text-gray-400">
            <div className="flex items-center gap-1.5">
              <Loader2 size={12} className="animate-spin text-blue-400" />
              <span>
                {dlState === 'starting'
                  ? '開始中...'
                  : dlState === 'processing'
                  ? 'マージ中...'
                  : progress.percent}
              </span>
            </div>
            <div className="flex gap-3 text-gray-500">
              {progress.speed && <span>{progress.speed}</span>}
              {progress.eta && dlState === 'downloading' && <span>残り {progress.eta}</span>}
            </div>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${
                dlState === 'processing'
                  ? 'bg-yellow-500 w-full animate-pulse'
                  : dlState === 'starting'
                  ? 'bg-blue-500 w-[3%]'
                  : 'bg-blue-500'
              }`}
              style={dlState === 'downloading' ? { width: `${percentNum}%` } : undefined}
            />
          </div>
          {showCookieHint && (
            <p className="text-xs text-gray-500">
              🍪 {COOKIE_BROWSER_OPTIONS.find(o => o.value === cookieBrowser)?.label ?? cookieBrowser} のCookieを使用中
            </p>
          )}
        </div>
      )}

      {/* ── 品質 + Cookie + ダウンロードボタン（idle / error 時） ── */}
      {(dlState === 'idle' || dlState === 'error') && (
        <div className="flex flex-col gap-2">
          {/* 1行目: 品質 + Cookie ブラウザ */}
          <div className="flex items-center gap-2">
            {/* 品質選択 */}
            <div className="flex items-center gap-1 min-w-0">
              <label className="text-xs text-gray-400 shrink-0">画質</label>
              <select
                value={quality}
                onChange={(e) => setQuality(e.target.value)}
                className="bg-gray-700 border border-gray-600 text-gray-200 text-xs rounded px-1.5 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {QUALITY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Cookie ブラウザ選択 */}
            <div className="flex items-center gap-1 flex-1 min-w-0">
              <Cookie size={12} className="text-gray-400 shrink-0" />
              <label className="text-xs text-gray-400 shrink-0">Cookie</label>
              <div className="relative flex-1 min-w-0">
                <select
                  value={cookieBrowser}
                  onChange={(e) => setCookieBrowser(e.target.value)}
                  className="w-full bg-gray-700 border border-gray-600 text-gray-200 text-xs rounded px-1.5 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500 appearance-none pr-5"
                >
                  {COOKIE_BROWSER_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <ChevronDown size={10} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
              </div>
            </div>
          </div>

          {/* Cookie 使用時の注意 */}
          {cookieBrowser && (
            <div className="text-xs text-blue-300 bg-blue-900/20 border border-blue-700/40 rounded px-2 py-1.5">
              🍪 <strong>{COOKIE_BROWSER_OPTIONS.find(o => o.value === cookieBrowser)?.label}</strong> のCookieを使用します。
              事前にそのブラウザでサイトへログインしておいてください。
              ダウンロード中はブラウザを閉じてください（Chromeは起動中でも動作する場合があります）。
            </div>
          )}

          {/* ダウンロードボタン */}
          <button
            onClick={handleDownload}
            className="flex items-center justify-center gap-2 w-full py-2 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white rounded text-sm font-medium transition-colors"
          >
            <Download size={15} />
            ダウンロードして再生
          </button>
        </div>
      )}
    </div>
  )
}
