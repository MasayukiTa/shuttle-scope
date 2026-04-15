import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ClipboardCheck } from 'lucide-react'
import { apiGet } from '@/api/client'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useTheme } from '@/hooks/useTheme'
import { useAuth } from '@/hooks/useAuth'

// バックエンドから返る試合（動画）メタデータ
interface ExpertVideo {
  match_id: number | string
  title?: string
  date?: string
  opponent?: string
  miss_count: number
  labeled_count: number
}

type VideosResponse = ExpertVideo[]

interface ProgressEntry {
  match_id: number | string
  miss_count: number
  labeled_count: number
}

interface ProgressResponse {
  annotator_role: string
  total: number
  labeled: number
  per_match: ProgressEntry[]
}

// 完了率の計算（0除算ガード）
function calcRatio(labeled: number, total: number): number {
  if (!total || total <= 0) return 0
  return Math.min(1, labeled / total)
}

function ExpertLabelerContent() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { role } = useAuth()
  const annotatorRole = role === 'coach' ? 'coach' : 'analyst'

  // 試合一覧取得（バックエンドは配列を直接返す）
  const videosQuery = useQuery<VideosResponse>({
    queryKey: ['expert', 'videos'],
    queryFn: () => apiGet<VideosResponse>('/v1/expert/videos'),
  })

  // 進捗取得（annotator_role 必須）
  const progressQuery = useQuery<ProgressResponse>({
    queryKey: ['expert', 'progress', annotatorRole],
    queryFn: () => apiGet<ProgressResponse>(`/v1/expert/progress?annotator_role=${annotatorRole}`),
    retry: 0,
  })

  // 進捗を match_id でマージ
  const progressMap = new Map<string, ProgressEntry>()
  progressQuery.data?.per_match?.forEach((p) => {
    progressMap.set(String(p.match_id), p)
  })

  const videos = Array.isArray(videosQuery.data) ? videosQuery.data : []
  const merged = videos.map((v) => {
    const p = progressMap.get(String(v.match_id))
    return {
      ...v,
      miss_count: p?.miss_count ?? v.miss_count ?? 0,
      labeled_count: p?.labeled_count ?? v.labeled_count ?? 0,
    }
  })

  const pageBg = isLight ? 'bg-gray-50' : 'bg-gray-900'
  const textPrimary = isLight ? 'text-gray-900' : 'text-white'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const cardBg = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'

  return (
    <div className={`flex flex-col h-full ${pageBg} ${textPrimary}`}>
      <div className={`px-6 pt-6 pb-4 border-b ${borderColor} shrink-0`}>
        <div className="flex items-center gap-3 mb-2">
          <ClipboardCheck className="text-blue-500" size={20} />
          <h1 className="text-xl font-semibold">{t('expert_labeler.title')}</h1>
        </div>
        <div className={`text-xs ${textMuted}`}>{t('expert_labeler.subtitle')}</div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        <section className="max-w-4xl">
          <h2 className="text-sm font-semibold mb-3">{t('expert_labeler.video_list')}</h2>

          {videosQuery.isLoading && (
            <div className={`text-sm ${textMuted}`}>{t('expert_labeler.loading')}</div>
          )}

          {!videosQuery.isLoading && merged.length === 0 && (
            <div className={`p-4 rounded border text-sm space-y-2 ${cardBg}`}>
              <div className="font-semibold">{t('expert_labeler.empty_title')}</div>
              <div className={textMuted}>{t('expert_labeler.empty_desc')}</div>
              <ul className={`list-disc pl-5 space-y-1 ${textMuted}`}>
                <li>{t('expert_labeler.empty_cond_1')}</li>
                <li>{t('expert_labeler.empty_cond_2')}</li>
                <li>{t('expert_labeler.empty_cond_3')}</li>
                <li>{t('expert_labeler.empty_cond_4', { role: role ?? '-' })}</li>
              </ul>
              <div className={`text-xs pt-2 border-t ${borderColor} ${textMuted}`}>
                {t('expert_labeler.empty_hint')}
              </div>
            </div>
          )}

          <ul className="space-y-3">
            {merged.map((v) => {
              const ratio = calcRatio(v.labeled_count, v.miss_count)
              const pct = Math.round(ratio * 100)
              const done = v.miss_count > 0 && v.labeled_count >= v.miss_count
              const label = v.title || v.opponent || v.date || `Match ${v.match_id}`
              return (
                <li key={String(v.match_id)}>
                  <button
                    type="button"
                    onClick={() => navigate(`/expert-labeler/${v.match_id}`)}
                    // iPad 向け最小タップ領域 48px 以上
                    className={`w-full text-left p-4 rounded-lg border transition-colors hover:shadow ${cardBg}`}
                    style={{ minHeight: '72px' }}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium truncate">{label}</div>
                      {done && <span className="text-green-500 text-sm">✅</span>}
                    </div>
                    <div className={`mt-1 text-xs ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>
                      {t('expert_labeler.miss_count')}: {v.miss_count} /{' '}
                      {t('expert_labeler.labeled_count')}: {v.labeled_count} ({pct}%)
                    </div>
                    <div
                      className={`mt-2 h-2 rounded ${isLight ? 'bg-gray-200' : 'bg-gray-700'} overflow-hidden`}
                    >
                      <div
                        className="h-full bg-blue-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="mt-2 text-right text-sm font-medium text-blue-500">
                      {v.labeled_count > 0 && !done
                        ? t('expert_labeler.resume')
                        : t('expert_labeler.start')}{' '}
                      →
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      </div>
    </div>
  )
}



export function ExpertLabelerPage() {
  // コーチ・アナリストのみ閲覧可（player は拒否）
  return (
    <RoleGuard
      allowedRoles={['analyst', 'coach']}
      fallback={
        <div className="h-full flex items-center justify-center p-6 text-center text-sm opacity-70">
          コーチ・アナリスト専用ページです
        </div>
      }
    >
      <ExpertLabelerContent />
    </RoleGuard>
  )
}

export default ExpertLabelerPage
