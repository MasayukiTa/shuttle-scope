import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { apiPost, apiGet } from '../../api/client'
import { errorMessage } from '@/utils/errors'

interface ShuttlescopeApi {
  youtubeLiveDrmStart: (url: string, jobId: string, token: string) => Promise<unknown>
  youtubeLiveDrmStop: () => Promise<unknown>
}
type WindowWithShuttlescope = Window & { shuttlescope?: ShuttlescopeApi }

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
  const isElectron = typeof window !== 'undefined' && !!(window as WindowWithShuttlescope).shuttlescope

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
        const ss = (window as WindowWithShuttlescope).shuttlescope!
        const token = sessionStorage.getItem('shuttlescope_token') ?? ''
        await ss.youtubeLiveDrmStart(url.trim(), result.job_id, token)
        setJob({ ...result, method: 'drm', status: 'recording' })
      }

      startPoll(result.job_id)
    } catch (err: unknown) {
      setErrorMsg(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const handleStop = async () => {
    if (!job) return
    setLoading(true)
    try {
      if (job.method === 'drm' && isElectron) {
        await (window as WindowWithShuttlescope).shuttlescope!.youtubeLiveDrmStop()
      }
      const result = await apiPost<JobStatus>(`/youtube_live/${job.job_id}/stop`, {})
      setJob(result)
      stopPoll()
    } catch (err: unknown) {
      setErrorMsg(errorMessage(err))
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
      <h3 className="text-base font-semibold text-[var(--ss-t1)]">
        {t('youtubeLive.title')}
      </h3>

      <div>
        <label className="block text-sm font-medium text-[var(--ss-t2)] mb-1">
          {t('youtubeLive.urlLabel')}
        </label>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t('youtubeLive.urlPlaceholder')}
          disabled={isRecording || loading}
          className="w-full rounded-ss-md border border-[var(--ss-border-strong)]
                     bg-[var(--ss-surface-1)] text-[var(--ss-t1)]
                     px-3 py-2 text-base focus:outline-none focus:border-[var(--ss-brand)] focus:ring-[3px] focus:ring-[var(--ss-focus-ring)]
                     disabled:opacity-50 transition-colors duration-fast ease-out"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-[var(--ss-t2)] mb-1">
          {t('youtubeLive.cookieBrowserLabel')}
        </label>
        <select
          value={cookieBrowser}
          onChange={(e) => setCookieBrowser(e.target.value)}
          disabled={isRecording || loading}
          className="rounded-ss-md border border-[var(--ss-border-strong)]
                     bg-[var(--ss-surface-1)] text-[var(--ss-t1)]
                     px-3 py-2 text-base focus:outline-none focus:border-[var(--ss-brand)] focus:ring-[3px] focus:ring-[var(--ss-focus-ring)]
                     disabled:opacity-50 transition-colors duration-fast ease-out"
        >
          <option value="">{t('youtubeLive.cookieBrowserNone')}</option>
          {COOKIE_BROWSERS.map((b) => (
            <option key={b} value={b}>
              {b.charAt(0).toUpperCase() + b.slice(1)}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-[var(--ss-t3)]">
          {t('youtubeLive.cookieBrowserHint')}
        </p>
      </div>

      <div className="flex gap-2">
        {!isRecording ? (
          <button
            onClick={handleStart}
            disabled={loading || !url.trim()}
            className="px-4 py-2 bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white text-sm font-medium
                       rounded-ss-md disabled:opacity-50 transition-colors duration-base ease-out"
          >
            {loading ? t('youtubeLive.probing') : t('youtubeLive.startRecording')}
          </button>
        ) : (
          <button
            onClick={handleStop}
            disabled={loading}
            className="px-4 py-2 bg-[var(--ss-bad)] hover:opacity-90 text-white text-sm font-medium
                       rounded-ss-md disabled:opacity-50 transition-colors duration-base ease-out"
          >
            {t('youtubeLive.stopRecording')}
          </button>
        )}
      </div>

      {errorMsg && (
        <div className="rounded-ss-md bg-[var(--ss-danger-tint)] border border-[var(--ss-danger-border)] p-3">
          <p className="text-sm text-[var(--ss-bad)]">{errorMsg}</p>
        </div>
      )}

      {job && (
        <div className="rounded-ss-md border border-[var(--ss-border)]
                        bg-[var(--ss-surface-2)] p-4 space-y-2">
          <div className="flex items-center gap-2">
            {isRecording && (
              <span className="inline-block w-2 h-2 rounded-full bg-[var(--ss-bad)] animate-pulse" />
            )}
            <span className="text-sm font-medium text-[var(--ss-t1)]">
              {job.status === 'recording'
                ? t('youtubeLive.recording')
                : job.status === 'probing'
                  ? t('youtubeLive.probing')
                  : job.status === 'stopped'
                    ? t('youtubeLive.stopped')
                    : t('youtubeLive.error')}
            </span>
            <span className="text-xs text-[var(--ss-t3)]">
              — {methodLabel(job.method)}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[var(--ss-t2)]">
            <span>{t('youtubeLive.fileSize')}:</span>
            <span className="ss-num">{formatBytes(job.file_size)}</span>
            <span>{t('youtubeLive.elapsed')}:</span>
            <span className="ss-num">{formatElapsed(job.elapsed)}</span>
            <span>{t('youtubeLive.jobId')}:</span>
            <span className="font-mono truncate ss-num">{job.job_id}</span>
          </div>

          {job.method === 'drm' && (
            <p className="text-xs text-[var(--ss-brand)]">
              {t('youtubeLive.drmCapturing')}
            </p>
          )}

          {job.error && (
            <p className="text-xs text-[var(--ss-bad)]">{job.error}</p>
          )}

          {job.status === 'stopped' && job.out_path && (
            <p className="text-xs text-[var(--ss-t3)] break-all">
              {t('youtubeLive.outPath')}: {job.out_path}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
