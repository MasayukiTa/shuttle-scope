// ベンチマーク結果マトリクスコンポーネント
// device × target のテーブル。最速デバイスを青背景でハイライト。
// エラーセルは赤背景、未計測は「-」。

import { useTranslation } from 'react-i18next'
import { BenchmarkJob, BenchmarkTarget, ComputeDevice } from '@/api/benchmark'

interface Props {
  job: BenchmarkJob
  devices: ComputeDevice[]
  targets: BenchmarkTarget[]
}

/** 指定 target で最小 avg_ms（最速）のデバイス ID を返す */
function fastestDevice(
  results: BenchmarkJob['results'],
  target: BenchmarkTarget,
): string | null {
  let bestId: string | null = null
  let bestMs = Infinity
  for (const [deviceId, targetMap] of Object.entries(results)) {
    const cell = targetMap[target]
    if (!cell || 'error' in cell) continue
    if (cell.avg_ms < bestMs) {
      bestMs = cell.avg_ms
      bestId = deviceId
    }
  }
  return bestId
}

export function ResultMatrix({ job, devices, targets }: Props) {
  const { t } = useTranslation()

  // 結果が空の場合は何も表示しない
  if (Object.keys(job.results).length === 0) {
    return <p className="text-xs text-gray-500">{t('benchmark.no_result')}</p>
  }

  // target ごとの最速デバイス ID をキャッシュ
  const fastestMap: Record<string, string | null> = {}
  for (const target of targets) {
    fastestMap[target] = fastestDevice(job.results, target)
  }

  return (
    <div className="overflow-x-auto">
      <table className="text-xs w-full border-collapse">
        <thead>
          <tr>
            {/* 左上の空セル */}
            <th className="text-left px-2 py-1.5 text-gray-500 font-medium border-b border-gray-700">
              {t('benchmark.result')}
            </th>
            {targets.map((target) => (
              <th
                key={target}
                className="px-2 py-1.5 text-gray-400 font-medium border-b border-gray-700 whitespace-nowrap"
              >
                {t(`benchmark.targets.${target}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {devices.map((dev) => (
            <tr key={dev.device_id} className="border-b border-gray-800">
              {/* デバイスラベル */}
              <td className="px-2 py-2 text-gray-300 font-medium whitespace-nowrap">
                {dev.label}
              </td>
              {/* ターゲットごとのセル */}
              {targets.map((target) => {
                const cell = job.results[dev.device_id]?.[target]
                const isFastest = fastestMap[target] === dev.device_id

                if (!cell) {
                  // 未計測
                  return (
                    <td key={target} className="px-2 py-2 text-center text-gray-600">
                      —
                    </td>
                  )
                }

                if ('error' in cell) {
                  // エラーセル：赤背景
                  return (
                    <td
                      key={target}
                      className="px-2 py-2 text-center bg-red-900/40 text-red-400 rounded"
                      title={cell.error}
                    >
                      ERR
                    </td>
                  )
                }

                // 通常セル。最速デバイスは青背景
                return (
                  <td
                    key={target}
                    className={`px-2 py-2 text-center rounded ${
                      isFastest ? 'bg-blue-900/40' : ''
                    }`}
                  >
                    {/* fps は大字 */}
                    <p className={`font-bold font-mono ${isFastest ? 'text-blue-300' : 'text-green-300'}`}>
                      {cell.fps.toFixed(1)} fps
                    </p>
                    {/* avg_ms / p95_ms は小字 */}
                    <p className="text-[10px] text-gray-500 mt-0.5">
                      {cell.avg_ms.toFixed(1)}ms / p95={cell.p95_ms.toFixed(1)}ms
                    </p>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
