// ターゲット選択コンポーネント
// 5 種のベンチマーク対象チェックボックスと n_frames スライダーを提供する

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BenchmarkTarget } from '@/api/benchmark'

/** 全ターゲット一覧 */
const ALL_TARGETS: BenchmarkTarget[] = [
  'tracknet',
  'pose',
  'yolo',
  'pipeline_full',
  'clip_extract',
  'statistics',
]

const MIN_FRAMES = 1
const MAX_FRAMES = 300
const SNAP_STEP = 5   // ドラッグ停止後に 5 の倍数へスナップ

interface Props {
  selected: BenchmarkTarget[]
  onTargetsChange: (targets: BenchmarkTarget[]) => void
  nFrames: number
  onNFramesChange: (n: number) => void
}

export function TargetSelector({
  selected,
  onTargetsChange,
  nFrames,
  onNFramesChange,
}: Props) {
  const { t } = useTranslation()
  // スライダーをドラッグ中の表示値（1 単位）— 離したときに 5 倍数スナップ
  const [dragging, setDragging] = useState(false)
  const [displayValue, setDisplayValue] = useState(nFrames)

  function toggleTarget(target: BenchmarkTarget) {
    if (selected.includes(target)) {
      onTargetsChange(selected.filter((x) => x !== target))
    } else {
      onTargetsChange([...selected, target])
    }
  }

  function handleSliderChange(raw: number) {
    setDisplayValue(raw)
  }

  function handleSliderCommit(raw: number) {
    // 5 の倍数へスナップ（1〜4 は 5 へ、端数は四捨五入）
    const snapped = Math.max(MIN_FRAMES, Math.round(raw / SNAP_STEP) * SNAP_STEP)
    setDisplayValue(snapped)
    setDragging(false)
    onNFramesChange(snapped)
  }

  function handleNumberInput(val: string) {
    const n = parseInt(val, 10)
    if (!isNaN(n)) {
      const clamped = Math.max(MIN_FRAMES, Math.min(MAX_FRAMES, n))
      setDisplayValue(clamped)
      onNFramesChange(clamped)
    }
  }

  // スライダー上の 5 刻みマーカー位置（%）
  const snapMarkers = Array.from(
    { length: Math.floor((MAX_FRAMES - MIN_FRAMES) / SNAP_STEP) + 1 },
    (_, i) => MIN_FRAMES + i * SNAP_STEP,
  ).filter((v) => v % 50 === 0 || v === MIN_FRAMES || v === MAX_FRAMES)

  return (
    <div className="space-y-3">
      {/* ターゲット選択 */}
      <p className="text-xs font-medium text-gray-400">{t('benchmark.select_targets')}</p>
      <div className="flex flex-wrap gap-2">
        {ALL_TARGETS.map((target) => {
          const checked = selected.includes(target)
          return (
            <label
              key={target}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded border text-xs cursor-pointer transition-colors ${
                checked
                  ? 'border-blue-500 bg-blue-600 text-white'
                  : 'border-gray-600 bg-gray-800/40 text-gray-300 hover:border-gray-500'
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleTarget(target)}
                className="accent-blue-500"
              />
              {t(`benchmark.targets.${target}`)}
            </label>
          )
        })}
      </div>

      {/* n_frames スライダー */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-3 text-xs">
          <span className="text-gray-400 shrink-0">{t('auto.TargetSelector.k1')}</span>
          <div className="flex items-center gap-1.5 ml-auto">
            {/* 数値直接入力 */}
            <input
              type="number"
              min={MIN_FRAMES}
              max={MAX_FRAMES}
              value={displayValue}
              onChange={(e) => handleNumberInput(e.target.value)}
              className="w-16 bg-gray-700 border border-gray-600 rounded px-2 py-0.5 text-xs font-mono text-blue-300 text-right focus:outline-none focus:border-blue-500"
            />
            <span className="text-gray-500">frames</span>
          </div>
        </div>

        {/* スライダー本体 — 1 単位でドラッグ可、離したら 5 スナップ */}
        <div className="relative">
          <input
            type="range"
            min={MIN_FRAMES}
            max={MAX_FRAMES}
            step={1}
            value={displayValue}
            onMouseDown={() => setDragging(true)}
            onTouchStart={() => setDragging(true)}
            onChange={(e) => handleSliderChange(Number(e.target.value))}
            onMouseUp={(e) => handleSliderCommit(Number((e.target as HTMLInputElement).value))}
            onTouchEnd={(e) => handleSliderCommit(Number((e.target as HTMLInputElement).value))}
            onKeyUp={(e) => handleSliderCommit(Number((e.target as HTMLInputElement).value))}
            className="w-full accent-blue-500"
          />
          {/* 目盛りライン */}
          <div className="flex justify-between mt-0.5 px-0.5">
            {snapMarkers.map((v) => (
              <div
                key={v}
                className="flex flex-col items-center"
                style={{ width: 0, position: 'relative' }}
              >
                <div className="w-px h-1.5 bg-gray-600" />
                <span className="text-[9px] text-gray-600 absolute top-2 -translate-x-1/2">{v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* ドラッグ中: 大きく現在値を表示 */}
        {dragging && (
          <div className="text-center text-sm font-mono font-bold text-blue-300 tabular-nums">
            {displayValue} frames
          </div>
        )}
        <p className="text-[10px] text-gray-600">
          1フレーム単位で設定可。ドラッグ後は5の倍数にスナップします。
        </p>
      </div>
    </div>
  )
}
