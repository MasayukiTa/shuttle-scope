// INFRA Phase B: 試合一覧などで利用する解析ジョブ状態バッジ。
// AnalysisJob が無ければ「未解析」を表示する。
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { pipelineJobs, type AnalysisJobDTO } from '@/api/client'

interface Props {
  matchId: number
  className?: string
}

function statusClass(status?: string): string {
  switch (status) {
    case 'queued':
      return 'bg-slate-700 text-slate-200 border-slate-500'
    case 'running':
      return 'bg-gray-800 text-blue-300 border-gray-700'
    case 'done':
      return 'bg-gray-800 text-blue-300 border-gray-700'
    case 'failed':
      return 'bg-gray-800 text-red-300 border-gray-700'
    default:
      return 'bg-gray-800 text-gray-400 border-gray-600'
  }
}

export function PipelineJobBadge({ matchId, className }: Props) {
  const { t } = useTranslation()
  // 旧実装は match ごとに `?match_id=N&limit=1` を発火していたため、試合一覧では
  // 行数ぶん (約80本) のリクエストが並列発火し rate-limit を枯渇させていた
  // (同時に走る /auth/me が 429 を受けて login へ弾かれる事故の引き金)。
  // 全バッジで queryKey を共有し、最新ジョブ一覧 1 リクエストに集約する。
  // 注意: enqueued_at 降順の先頭 500 件に乗らない古い match のジョブは
  // 「未解析」表示になる (limit 上限は backend 仕様)。
  const { data } = useQuery<AnalysisJobDTO[]>({
    queryKey: ['pipeline-jobs-all'],
    queryFn: () => pipelineJobs({ limit: 500 }),
    staleTime: 15_000,
    // DB が空 / 未登録でも既存画面を壊さないため、エラーは握り潰す
    retry: false,
  })

  // 降順リストなので最初のヒットが当該 match の最新ジョブ
  const job = data?.find((j) => j.match_id === matchId)
  const key = job ? `pipeline.status.${job.status}` : 'pipeline.status.none'

  return (
    <span
      title={t('pipeline.badge_title')}
      className={clsx(
        'inline-block rounded border px-1.5 py-0 text-[10px]',
        statusClass(job?.status),
        className,
      )}
    >
      {t(key)}
    </span>
  )
}

export default PipelineJobBadge
