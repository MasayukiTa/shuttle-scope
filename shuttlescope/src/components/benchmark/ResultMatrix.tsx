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
    return <p className="text-xs text-[var(--ss-t3)]">{t('benchmark.no_result')}</p>
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
          <tr className="bg-[var(--ss-surface-2)]">
            {/* 左上の空セル */}
            <th className="text-left px-2 py-1.5 text-[var(--ss-t2)] font-medium border-b border-[var(--ss-border)]">
              {t('benchmark.result')}
            </th>
            {targets.map((target) => (
              <th
                key={target}
                className="px-2 py-1.5 text-[var(--ss-t2)] font-medium border-b border-[var(--ss-border)] whitespace-nowrap"
              >
                {t(`benchmark.targets.${target}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {devices.map((dev) => (
            <tr key={dev.device_id} className="border-b border-[var(--ss-border)] hover:bg-[var(--ss-surface-3)]">
              {/* デバイスラベル */}
              <td className="px-2 py-2 text-[var(--ss-t1)] font-medium whitespace-nowrap">
                {dev.label}
              </td>
              {/* ターゲットごとのセル */}
              {targets.map((target) => {
                const cell = job.results[dev.device_id]?.[target]
                const isFastest = fastestMap[target] === dev.device_id

                if (!cell) {
                  // 未計測
                  return (
                    <td key={target} className="px-2 py-2 text-center text-[var(--ss-t3)]">
                      —
                    </td>
                  )
                }

                if ('error' in cell) {
                  // "device unavailable" = このデバイスでは対応外（CPU専用タスク等）→ 未計測扱い
                  if (cell.error === 'device unavailable') {
                    return (
                      <td key={target} className="px-2 py-2 text-center text-[var(--ss-t3)]">
                        —
                      </td>
                    )
                  }
                  // モデルファイル未配置
                  if (cell.error.startsWith('モデル未配置')) {
                    return (
                      <td
                        key={target}
                        className="px-2 py-2 text-center bg-[var(--ss-warn-tint)] text-[var(--ss-warn)] rounded-ss-md text-[10px]"
                        title={cell.error}
                      >
                        {t('auto.ResultMatrix.no_model')}
                      </td>
                    )
                  }
                  // その他エラー：赤背景
                  return (
                    <td
                      key={target}
                      className="px-2 py-2 text-center bg-[var(--ss-danger-tint)] text-[var(--ss-danger)] rounded-ss-md"
                      title={cell.error}
                    >
                      {t('auto.ResultMatrix.err')}
                    </td>
                  )
                }

                // 通常セル。最速デバイスは青背景
                return (
                  <td
                    key={target}
                    className={`px-2 py-2 text-center rounded-ss-md ${
                      isFastest ? 'bg-[var(--ss-brand-tint)]' : ''
                    }`}
                  >
                    {/* fps は大字 */}
                    <p className={`font-bold font-mono ss-num ${isFastest ? 'text-[var(--ss-brand)]' : 'text-[var(--ss-good)]'}`}>
                      {cell.fps.toFixed(1)} fps
                    </p>
                    {/* avg_ms / p95_ms は小字 */}
                    <p className="text-[10px] text-[var(--ss-t3)] mt-0.5 ss-num">
                      {t('auto.ResultMatrix.ms_p95', { avg: cell.avg_ms.toFixed(1), p95: cell.p95_ms.toFixed(1) })}
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
