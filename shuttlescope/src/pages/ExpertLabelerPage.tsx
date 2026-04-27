import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ClipboardCheck } from 'lucide-react'
import { apiGet } from '@/api/client'
import { useTheme } from '@/hooks/useTheme'
import { useAuth } from '@/hooks/useAuth'
import { CoGDetectionPage } from '@/pages/CoGDetectionPage'

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

type ActiveTab = 'matches' | 'cog'

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
  const isAdmin = role === 'admin'

  const [activeTab, setActiveTab] = useState<ActiveTab>('matches')

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

  const tabs: { key: ActiveTab; label: string; adminOnly?: boolean }[] = [
    { key: 'matches', label: t('expert_labeler.tab_matches') },
    { key: 'cog',     label: t('expert_labeler.tab_labeling'), adminOnly: true },
  ]
  const visibleTabs = tabs.filter((tab) => !tab.adminOnly || isAdmin)

  return (
    <div className={`flex flex-col h-full ${pageBg} ${textPrimary}`}>
      {/* ヘッダー */}
      <div className={`px-6 pt-6 pb-0 border-b ${borderColor} shrink-0`}>
        <div className="flex items-center gap-3 mb-2">
          <ClipboardCheck className="text-blue-500" size={20} />
          <h1 className="text-xl font-semibold">{t('expert_labeler.title')}</h1>
        </div>
        <div className={`text-xs mb-3 ${textMuted}`}>{t('expert_labeler.subtitle')}</div>

        {/* サブタブ（admin のみ CoG タブが表示される） */}
        {visibleTabs.length > 1 && (
          <div className="flex gap-1">
            {visibleTabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={`px-4 py-2 text-sm font-medium rounded-t border-b-2 transition-colors ${
                  activeTab === tab.key
                    ? 'border-blue-500 text-blue-500'
                    : `border-transparent ${textMuted} hover:${textPrimary}`
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* コンテンツ */}
      {activeTab === 'cog' ? (
        <div className="flex-1 overflow-hidden">
          <CoGDetectionPage onBack={() => setActiveTab('matches')} />
        </div>
      ) : (
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
                  <li key={String(v.match_id)} className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => navigate(`/expert-labeler/${v.match_id}`)}
                      // iPad 向け最小タップ領域 48px 以上
                      className={`flex-1 text-left p-4 rounded-lg border transition-colors hover:shadow ${cardBg}`}
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
                    {/* エクスポートボタン（ラベルが 1 件以上のとき表示） */}
                    {v.labeled_count > 0 && (
                      <div className="flex flex-col gap-1 justify-center">
                        <a
                          href={`/api/v1/expert/export?match_id=${v.match_id}&fmt=json`}
                          target="_blank"
                          rel="noreferrer"
                          className={`text-[10px] px-2 py-1 rounded border text-center transition-colors ${
                            isLight
                              ? 'border-gray-300 text-gray-500 hover:bg-gray-100'
                              : 'border-gray-600 text-gray-400 hover:bg-gray-700'
                          }`}
                        >
                          JSON
                        </a>
                        <a
                          href={`/api/v1/expert/export?match_id=${v.match_id}&fmt=csv`}
                          target="_blank"
                          rel="noreferrer"
                          className={`text-[10px] px-2 py-1 rounded border text-center transition-colors ${
                            isLight
                              ? 'border-gray-300 text-gray-500 hover:bg-gray-100'
                              : 'border-gray-600 text-gray-400 hover:bg-gray-700'
                          }`}
                        >
                          CSV
                        </a>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        </div>
      )}
    </div>
  )
}

export function ExpertLabelerPage() {
  return <ExpertLabelerContent />
}

export default ExpertLabelerPage
