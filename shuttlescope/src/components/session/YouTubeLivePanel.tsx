import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { apiPost, apiGet } from '../../api/client'

interface JobStatus {
  job_id: string
  status: 'probing' | 'recording' | 'stopped' | 'error'
  method: 'hls' | 'hls_ytdlp' | 'drm_pending' | 'drm' | 'drm_required'
  file_size: number
  elapsed: number
  error: string | null
  out_path: string
}

const COOKIE_BROWSERS = ['chrome', 'firefox', 'edge', 'brave', 'opera', 'vivaldi'] as const

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export function YouTubeLivePanel({ matchId }: { matchId?: number } = {}) {
  const { t } = useTranslation()
  const [url, setUrl] = useState('')
  const [cookieBrowser, setCookieBrowser] = useState('')
  const [job, setJob] = useState<JobStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isElectron = typeof window !== 'undefined' && !!(window as any).shuttlescope

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startPoll = useCallback(
    (jobId: string) => {
      stopPoll()
      pollRef.current = setInterval(async () => {
        try {
          const status = await apiGet<JobStatus>(`/youtube_live/${jobId}/status`)
          setJob(status)
          if (status.status === 'stopped' || status.status === 'error') stopPoll()
        } catch {
          // polling error ignored
        }
      }, 2000)
    },
    [stopPoll],
  )

  useEffect(() => () => stopPoll(), [stopPoll])

  const handleStart = async () => {
    if (!url.trim()) return
    setLoading(true)
    setErrorMsg(null)
    setJob(null)
    try {
      const result = await apiPost<JobStatus>('/youtube_live/start', {
        url: url.trim(),
        quality: 'best',
        cookie_browser: cookieBrowser || null,
        match_id: matchId ?? null,
      })
      setJob(result)

      if (result.method === 'drm_required') {
        if (!isElectron) {
          setErrorMsg(t('youtubeLive.noElectron'))
          setLoading(false)
          return
        }
        const ss = (window as any).shuttlescope
        const token = sessionStorage.getItem('shuttlescope_token') ?? ''
        await ss.youtubeLiveDrmStart(url.trim(), result.job_id, token)
        setJob({ ...result, method: 'drm', status: 'recording' })
      }

      startPoll(result.job_id)
    } catch (err: any) {
      setErrorMsg(err?.message ?? String(err))
    } finally {
      setLoading(false)
    }
  }

  const handleStop = async () => {
    if (!job) return
    setLoading(true)
    try {
      if (job.method === 'drm' && isElectron) {
        await (window as any).shuttlescope.youtubeLiveDrmStop()
      }
      const result = await apiPost<JobStatus>(`/youtube_live/${job.job_id}/stop`, {})
      setJob(result)
      stopPoll()
    } catch (err: any) {
      setErrorMsg(err?.message ?? String(err))
    } finally {
      setLoading(false)
    }
  }

  const isRecording = job?.status === 'recording' || job?.status === 'probing'

  const methodLabel = (method: string) => {
    if (method === 'hls') return t('youtubeLive.methodHls')
    if (method === 'hls_ytdlp') return `${t('youtubeLive.methodHls')} (yt-dlp)`
    if (method === 'drm' || method === 'drm_pending') return t('youtubeLive.methodDrm')
    if (method === 'drm_required') return t('youtubeLive.methodDrmRequired')
    return method
  }

  return (
    <div className="space-y-4">
      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
        {t('youtubeLive.title')}
      </h3>

      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          {t('youtubeLive.urlLabel')}
        </label>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t('youtubeLive.urlPlaceholder')}
          disabled={isRecording || loading}
          className="w-full rounded-md border border-gray-300 dark:border-gray-600
                     bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                     px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500
                     disabled:opacity-50"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          {t('youtubeLive.cookieBrowserLabel')}
        </label>
        <select
          value={cookieBrowser}
          onChange={(e) => setCookieBrowser(e.target.value)}
          disabled={isRecording || loading}
          className="rounded-md border border-gray-300 dark:border-gray-600
                     bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                     px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500
                     disabled:opacity-50"
        >
          <option value="">{t('youtubeLive.cookieBrowserNone')}</option>
          {COOKIE_BROWSERS.map((b) => (
            <option key={b} value={b}>
              {b.charAt(0).toUpperCase() + b.slice(1)}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          {t('youtubeLive.cookieBrowserHint')}
        </p>
      </div>

      <div className="flex gap-2">
        {!isRecording ? (
          <button
            onClick={handleStart}
            disabled={loading || !url.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium
                       rounded-md disabled:opacity-50 transition-colors"
          >
            {loading ? t('youtubeLive.probing') : t('youtubeLive.startRecording')}
          </button>
        ) : (
          <button
            onClick={handleStop}
            disabled={loading}
            className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-medium
                       rounded-md disabled:opacity-50 transition-colors"
          >
            {t('youtubeLive.stopRecording')}
          </button>
        )}
      </div>

      {errorMsg && (
        <div className="rounded-md bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-3">
          <p className="text-sm text-red-700 dark:text-red-400">{errorMsg}</p>
        </div>
      )}

      {job && (
        <div className="rounded-md border border-gray-200 dark:border-gray-700
                        bg-gray-50 dark:bg-gray-800/50 p-4 space-y-2">
          <div className="flex items-center gap-2">
            {isRecording && (
              <span className="inline-block w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            )}
            <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {job.status === 'recording'
                ? t('youtubeLive.recording')
                : job.status === 'probing'
                  ? t('youtubeLive.probing')
                  : job.status === 'stopped'
                    ? t('youtubeLive.stopped')
                    : t('youtubeLive.error')}
            </span>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              — {methodLabel(job.method)}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-600 dark:text-gray-400">
            <span>{t('youtubeLive.fileSize')}:</span>
            <span>{formatBytes(job.file_size)}</span>
            <span>{t('youtubeLive.elapsed')}:</span>
            <span>{formatElapsed(job.elapsed)}</span>
            <span>{t('youtubeLive.jobId')}:</span>
            <span className="font-mono truncate">{job.job_id}</span>
          </div>

          {job.method === 'drm' && (
            <p className="text-xs text-blue-600 dark:text-blue-400">
              {t('youtubeLive.drmCapturing')}
            </p>
          )}

          {job.error && (
            <p className="text-xs text-red-600 dark:text-red-400">{job.error}</p>
          )}

          {job.status === 'stopped' && job.out_path && (
            <p className="text-xs text-gray-500 dark:text-gray-500 break-all">
              {t('youtubeLive.outPath')}: {job.out_path}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
