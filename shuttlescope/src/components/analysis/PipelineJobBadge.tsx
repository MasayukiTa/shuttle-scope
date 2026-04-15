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
      return 'bg-blue-900/40 text-blue-300 border-blue-500'
    case 'done':
      return 'bg-emerald-900/40 text-emerald-300 border-emerald-500'
    case 'failed':
      return 'bg-red-900/40 text-red-300 border-red-500'
    default:
      return 'bg-gray-800 text-gray-400 border-gray-600'
  }
}

export function PipelineJobBadge({ matchId, className }: Props) {
  const { t } = useTranslation()
  const { data } = useQuery<AnalysisJobDTO[]>({
    queryKey: ['pipeline-jobs', matchId],
    queryFn: () => pipelineJobs({ match_id: matchId, limit: 1 }),
    staleTime: 15_000,
    // DB が空 / 未登録でも既存画面を壊さないため、エラーは握り潰す
    retry: false,
  })

  const job = data && data.length > 0 ? data[0] : undefined
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
