// ベンチマーク実行中プログレスバーコンポーネント
// job_id を受け取り 1.5 秒ごとにポーリングして進捗を表示する

import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { BenchmarkJob } from '@/api/benchmark'

/** ポーリング間隔（ミリ秒） */
const POLL_INTERVAL_MS = 1500

interface Props {
  /** 実行中フラグ（false になった時点でポーリング停止） */
  running: boolean
  /** 現在のジョブ（未取得の場合は null） */
  job: BenchmarkJob | null
  /** ポーリング時に呼び出すコールバック */
  onPoll: () => void
}

export function BenchmarkProgress({ running, job, onPoll }: Props) {
  const { t } = useTranslation()
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // 常に最新の onPoll を参照するための ref（stale closure 対策）
  const onPollRef = useRef(onPoll)
  useEffect(() => {
    onPollRef.current = onPoll
  }, [onPoll])

  // running が true の間だけ 1.5 秒ごとに onPoll を呼び出す
  useEffect(() => {
    if (!running) {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      return
    }

    // 開始直後にも 1 回呼んでおく
    onPollRef.current()
    intervalRef.current = setInterval(() => onPollRef.current(), POLL_INTERVAL_MS)

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [running])

  if (!running && !job) return null

  const progressFraction = job?.progress ?? 0
  const progressPct = Math.round(progressFraction * 100)

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400">
          {running ? t('benchmark.running') : t('benchmark.result')}
        </span>
        <span className="font-mono text-blue-300">{progressPct}%</span>
      </div>
      <div className="w-full h-2 rounded-full bg-gray-700 overflow-hidden">
        <div
          className="h-full bg-blue-500 transition-all duration-500"
          style={{ width: `${progressPct}%` }}
        />
      </div>
    </div>
  )
}
