import { useState, useRef, useCallback, useEffect } from 'react'

export interface MatchTimer {
  elapsedSec: number
  isRunning: boolean
  start: () => void
  pause: () => void
  reset: () => void
  /** 表示用文字列 MM:SS.T */
  displayTime: string
}

export function useMatchTimer(): MatchTimer {
  const [elapsedMs, setElapsedMs] = useState(0)
  const [isRunning, setIsRunning] = useState(false)
  const startedAtRef = useRef<number | null>(null)  // タイマー開始時のtimestamp
  const accumulatedRef = useRef(0)                  // 一時停止までの累積ms
  const rafRef = useRef<number | null>(null)

  const tick = useCallback(() => {
    if (startedAtRef.current == null) return
    const elapsed = accumulatedRef.current + (Date.now() - startedAtRef.current)
    setElapsedMs(elapsed)
    rafRef.current = requestAnimationFrame(tick)
  }, [])

  const start = useCallback(() => {
    if (isRunning) return
    startedAtRef.current = Date.now()
    setIsRunning(true)
    rafRef.current = requestAnimationFrame(tick)
  }, [isRunning, tick])

  const pause = useCallback(() => {
    if (!isRunning) return
    if (startedAtRef.current != null) {
      accumulatedRef.current += Date.now() - startedAtRef.current
      startedAtRef.current = null
    }
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    setIsRunning(false)
  }, [isRunning])

  const reset = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    startedAtRef.current = null
    accumulatedRef.current = 0
    setElapsedMs(0)
    setIsRunning(false)
  }, [])

  // アンマウント時にRAFをクリア
  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [])

  const elapsedSec = elapsedMs / 1000
  const totalSec = Math.floor(elapsedSec)
  const minutes = Math.floor(totalSec / 60).toString().padStart(2, '0')
  const seconds = (totalSec % 60).toString().padStart(2, '0')
  const tenths = Math.floor((elapsedMs % 1000) / 100)
  const displayTime = `${minutes}:${seconds}.${tenths}`

  return { elapsedSec, isRunning, start, pause, reset, displayTime }
}
