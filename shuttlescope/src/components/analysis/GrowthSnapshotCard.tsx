// Growth Snapshot: テンプレ生成（将来 LLM プラガブル）。
// プレイヤー安全な「伸びしろ」文面。
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet, API_BASE_URL } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { useCardTheme } from '@/hooks/useCardTheme'

interface Props {
  playerId: number
  periodDays?: number
  /**
   * サーバーが返す例示データ (meta.example) を画面に出すか。既定は開発ビルドだけ。
   * 本番では作り物の数値を「今週の伸びしろ」として見せない。
   */
  allowSample?: boolean
}

interface InsightItemDTO {
  id: string
  prose: string
  evidence_path: string
  confidence: number
  metric: Record<string, unknown> & { sample_n?: number }
}

interface InsightResultDTO {
  items: InsightItemDTO[]
  generator: string
  generated_at: string
  meta?: { example?: boolean; disclaimer?: string }
}

export function GrowthSnapshotCard({ playerId, periodDays = 30, allowSample = import.meta.env.DEV }: Props) {
  const { t, i18n } = useTranslation()
  const { card, textHeading, textMuted, isLight } = useCardTheme()
  const lang = i18n.language?.startsWith('en') ? 'en' : 'ja'

  const { data, isLoading } = useQuery({
    queryKey: ['insights-growth-snapshot', playerId, periodDays, lang],
    queryFn: () =>
      apiGet<InsightResultDTO>('/insights/growth_snapshot', {
        player_id: playerId,
        period_days: periodDays,
        lang,
      }),
    enabled: !!playerId,
  })

  const headerTitle = t('auto.GrowthSnapshotCard.title')
  // `/insights/growth_snapshot` はまだ DB を引かず固定の例示値を返す。その回の
  // 返り値は meta.example で自己申告しているが、画面はこれを読んでいなかったため、
  // 例示値が「テンプレ生成 (ベータ)」= 実データの初期版として表示されていた。
  // さらに下の ConfidenceBadge は例示値の sample_n をそのまま星に変換するので、
  // 作り物に信頼度を付けて見せていた。example のときは出所を明示し、星は出さない。
  const isExample = data?.meta?.example === true
  // 例示データは allowSample のときだけ表示する。それ以外は「データなし」と同じ扱いにする。
  const items = isExample && !allowSample ? [] : (data?.items ?? [])
  const showSampleNotice = isExample && allowSample
  // 例示データを隠しているときは、出所の札も出さない (出すと「サンプル」なのに中身が無いことになる)。
  const chipLabel = showSampleNotice
    ? t('auto.GrowthSnapshotCard.sample_chip')
    : isExample
      ? null
      : t('auto.GrowthSnapshotCard.beta_chip')

  return (
    <div
      data-tutorial="dashboard.growthSnapshot"
      className={`${card} rounded-ss-lg shadow-card p-4 ${isExample ? 'border-2 border-dashed border-amber-400' : ''}`}
    >
      <div className="flex items-center justify-between mb-3">
        <p className={`text-sm font-semibold ${textHeading}`}>{headerTitle}</p>
        {chipLabel && (
          <span
            className={`text-[10px] px-2 py-0.5 rounded-ss-pill border ${
              isLight
                ? 'border-amber-400 text-amber-700 bg-amber-50'
                : 'border-amber-500 text-amber-300 bg-amber-900/20'
            }`}
          >
            {chipLabel}
          </span>
        )}
      </div>

      {showSampleNotice && (
        <p className={`text-xs mb-3 ${textMuted}`}>
          {t('auto.GrowthSnapshotCard.sample_note')} {t('auto.GrowthSnapshotCard.sample_boundary')}
        </p>
      )}

      {isLoading && (
        <div className="space-y-2 animate-pulse">
          <div className={`h-3 rounded-ss-sm ${isLight ? 'bg-gray-200' : 'bg-gray-700'} w-5/6`} />
          <div className={`h-3 rounded-ss-sm ${isLight ? 'bg-gray-200' : 'bg-gray-700'} w-4/6`} />
          <div className={`h-3 rounded-ss-sm ${isLight ? 'bg-gray-200' : 'bg-gray-700'} w-3/6`} />
        </div>
      )}

      {!isLoading && items.length === 0 && (
        <p className={`text-xs ${textMuted}`}>{t('auto.GrowthSnapshotCard.empty')}</p>
      )}

      {!isLoading && items.length > 0 && (
        <ul className="space-y-3">
          {items.map((it) => {
            const sampleN = typeof it.metric?.sample_n === 'number' ? (it.metric.sample_n as number) : 0
            const href = `${API_BASE_URL}${it.evidence_path}`
            return (
              <li
                key={it.id}
                className={`flex flex-col gap-2 rounded-ss-md border p-3 ${
                  isLight ? 'border-gray-200 bg-white' : 'border-gray-700 bg-gray-800/40'
                }`}
              >
                <p className={`text-sm leading-relaxed ${textHeading}`}>{it.prose}</p>
                <div className="flex items-center justify-between gap-2">
                  {isExample ? <span /> : <ConfidenceBadge sampleSize={sampleN} compact />}
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`text-xs underline transition-colors duration-fast ${
                      isLight ? 'text-blue-700 hover:text-blue-900' : 'text-blue-300 hover:text-blue-200'
                    }`}
                  >
                    {t('auto.GrowthSnapshotCard.details')}
                  </a>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
