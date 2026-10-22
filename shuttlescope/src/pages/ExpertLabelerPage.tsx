import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { useTheme } from '@/hooks/useTheme'
import { useAuth } from '@/hooks/useAuth'
import { CoGDetectionPage } from '@/pages/CoGDetectionPage'
import { MIcon } from '@/components/common/MIcon'

// 一覧で「開始」を出してよいか。バックエンドの _review_status と同じ値。
type ReviewStatus = 'no_targets' | 'no_video' | 'clips_pending' | 'ready'

// バックエンドから返る試合（動画）メタデータ
interface ExpertVideo {
  match_id: number | string
  title?: string
  date?: string
  opponent?: string
  miss_count: number
  labeled_count: number
  // 古いバックエンドでは返らないので省略可。省略時は「開始できる」として扱う。
  review_status?: ReviewStatus
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

const BLOCKED_STATUSES: ReviewStatus[] = ['no_targets', 'no_video']

type ActiveTab = 'matches' | 'cog'

// 完了率の計算（0除算ガード）
function calcRatio(labeled: number, total: number): number {
  if (!total || total <= 0) return 0
  return Math.min(1, labeled / total)
}

function ExpertLabelerContent() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  useTheme()
  const { role } = useAuth()
  const annotatorRole = role === 'coach' ? 'coach' : 'analyst'
  const isAdmin = role === 'admin'

  const [activeTab, setActiveTab] = useState<ActiveTab>('matches')
  const [search, setSearch] = useState('')
  const [incompleteOnly, setIncompleteOnly] = useState(false)

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

  // 絞り込み（並びはバックエンドが日付の新しい順で返す）
  const needle = search.trim().toLowerCase()
  const filtered = merged.filter((v) => {
    const name = (v.title || v.opponent || v.date || `Match ${v.match_id}`).toLowerCase()
    if (needle && !name.includes(needle)) return false
    if (incompleteOnly && !(v.miss_count > 0 && v.labeled_count < v.miss_count)) return false
    return true
  })

  const pageBg = 'bg-[var(--ss-bg-app)]'
  const textPrimary = 'text-[var(--ss-t1)]'
  const textMuted = 'text-[var(--ss-t3)]'
  const borderColor = 'border-[var(--ss-border)]'
  const cardBg = 'bg-[var(--ss-surface-1)] border-[var(--ss-border)]'

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
          <MIcon name="assignment_turned_in" className="text-[var(--ss-brand)]" size={20} />
          <h1 className="text-xl font-semibold tracking-[-0.014em]">{t('expert_labeler.title')}</h1>
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
                className={`px-4 py-2 text-sm font-medium rounded-t-ss-md border-b-2 transition-colors duration-base ease-out ${
                  activeTab === tab.key
                    ? 'border-[var(--ss-brand)] text-[var(--ss-brand)]'
                    : `border-transparent ${textMuted} hover:text-[var(--ss-t1)]`
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
              <div className={`p-4 rounded-ss-lg border text-sm space-y-2 ${cardBg}`}>
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

            {merged.length > 0 && (
              <div className="flex flex-wrap items-center gap-3 mb-3">
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('expert_labeler.search_placeholder')}
                  aria-label={t('expert_labeler.search_placeholder')}
                  className={`flex-1 min-w-[12rem] px-3 py-2 text-sm rounded-ss-md border bg-[var(--ss-surface-1)] ${borderColor}`}
                />
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={incompleteOnly}
                    onChange={(e) => setIncompleteOnly(e.target.checked)}
                  />
                  {t('expert_labeler.filter_incomplete')}
                </label>
                <span className={`text-xs ss-num ${textMuted}`}>
                  {t('expert_labeler.result_count', { shown: filtered.length, total: merged.length })}
                </span>
              </div>
            )}

            {merged.length > 0 && filtered.length === 0 && (
              <div className={`p-4 rounded-ss-lg border text-sm ${cardBg} ${textMuted}`}>
                {t('expert_labeler.no_match_filter')}
              </div>
            )}

            <ul className="space-y-3">
              {filtered.map((v) => {
                const status: ReviewStatus = v.review_status ?? 'ready'
                const blocked = BLOCKED_STATUSES.includes(status)
                // ミス件数 0 のときは完了率を出さない（0% と書くと未着手に見える）
                const hasTargets = v.miss_count > 0
                const ratio = calcRatio(v.labeled_count, v.miss_count)
                const pct = Math.round(ratio * 100)
                const done = v.miss_count > 0 && v.labeled_count >= v.miss_count
                const label = v.title || v.opponent || v.date || `Match ${v.match_id}`
                return (
                  <li key={String(v.match_id)} className="flex gap-2">
                    <button
                      type="button"
                      disabled={blocked}
                      onClick={() => navigate(`/expert-labeler/${v.match_id}`)}
                      // iPad 向け最小タップ領域 48px 以上
                      className={`flex-1 text-left p-4 rounded-ss-lg border transition-colors duration-base ease-out ${cardBg} ${
                        blocked ? 'opacity-60 cursor-not-allowed' : 'hover:shadow-card-hover'
                      }`}
                      style={{ minHeight: '72px' }}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-medium truncate">{label}</div>
                        {done && <span className="text-[var(--ss-success)] text-sm">{t('auto.ExpertLabelerPage.check_mark')}</span>}
                      </div>
                      <div className="mt-1 text-xs ss-num text-[var(--ss-t3)]">
                        {t('expert_labeler.miss_count')}: {v.miss_count} /{' '}
                        {t('expert_labeler.labeled_count')}: {v.labeled_count} ({hasTargets ? `${pct}%` : '—'})
                      </div>
                      {status !== 'ready' && (
                        <div className="mt-1 text-xs text-[var(--ss-t2)]">
                          {t(`expert_labeler.status_${status}`)}
                        </div>
                      )}
                      <div
                        className="mt-2 h-2 rounded-ss-pill bg-[var(--ss-surface-2)] overflow-hidden"
                      >
                        <div
                          className="h-full bg-[var(--ss-brand)]"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      {!blocked && (
                        <div className="mt-2 text-right text-sm font-medium text-[var(--ss-brand)]">
                          {v.labeled_count > 0 && !done
                            ? t('expert_labeler.resume')
                            : t('expert_labeler.start')}{' '}
                          →
                        </div>
                      )}
                    </button>
                    {/* エクスポートボタン（ラベルが 1 件以上のとき表示） */}
                    {v.labeled_count > 0 && (
                      <div className="flex flex-col gap-1 justify-center">
                        <a
                          href={`/api/v1/expert/export?match_id=${v.match_id}&fmt=json`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] px-2 py-1 rounded-ss-sm border text-center transition-colors duration-base ease-out border-[var(--ss-border-strong)] text-[var(--ss-t3)] hover:bg-[var(--ss-surface-2)]"
                        >
                          {t('auto.ExpertLabelerPage.json')}
                        </a>
                        <a
                          href={`/api/v1/expert/export?match_id=${v.match_id}&fmt=csv`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] px-2 py-1 rounded-ss-sm border text-center transition-colors duration-base ease-out border-[var(--ss-border-strong)] text-[var(--ss-t3)] hover:bg-[var(--ss-surface-2)]"
                        >
                          {t('auto.ExpertLabelerPage.csv')}
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
