import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { Match } from '@/types'
import { useCardTheme } from '@/hooks/useCardTheme'
import { PipelineJobBadge } from '@/components/analysis/PipelineJobBadge'
import { statusColor, DownloadStatus } from './matchListUtils'
import { MIcon } from '@/components/common/MIcon'

// MatchListPage のモバイル用カード 1 件分。純粋抽出 (behavior 不変)。
// theme / navigate / t は内部で解決し、ページ固有の操作だけ callback で受ける。
export interface MatchCardProps {
  match: Match
  dl?: DownloadStatus
  onDownload: (m: Match) => void
  onEdit: (m: Match) => void
  deleteConfirmId: number | null
  onDeleteConfirm: (id: number | null) => void
  onDeleteExecute: (id: number) => void
}

export function MatchCard({
  match: m, dl, onDownload, onEdit,
  deleteConfirmId, onDeleteConfirm, onDeleteExecute,
}: MatchCardProps) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { isLight, textMuted, textSecondary } = useCardTheme()

  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        isLight ? 'bg-white border-gray-100 shadow-sm' : 'bg-gray-800 border-gray-700'
      }`}
    >
      {/* 1行目: 日付 + レベル + 大会名 + 結果 */}
      <div className="flex items-center gap-2 mb-0.5">
        <span className={`text-xs ${textMuted} shrink-0`}>{m.date}</span>
        <span className={`text-[10px] px-1.5 py-0 rounded-full shrink-0 ${isLight ? 'bg-gray-100 text-gray-600' : 'bg-gray-700 text-gray-300'}`}>
          {m.tournament_level}
        </span>
        <span className="font-medium text-sm truncate flex-1">{m.tournament}</span>
        <span className={clsx(
          'text-xs font-bold shrink-0',
          m.result === 'win' ? 'text-green-400' : m.result === 'loss' ? 'text-red-400' : 'text-gray-400'
        )}>
          {t(`match.results.${m.result}`)}
        </span>
      </div>

      {/* 2行目: 対戦情報 */}
      <div className="flex items-center gap-1 mb-1 text-sm">
        <span className={`text-[10px] ${textMuted} shrink-0`}>{t(`match.formats.${m.format}`)}</span>
        <span className={`${textSecondary} truncate`}>
          {t('match.list.vs', 'vs')} {m.player_b?.name ?? `#${m.player_b_id}`}
          {m.partner_b?.name && ` / ${m.partner_b.name}`}
        </span>
        {m.player_b?.needs_review && (
          <span className="text-[10px] text-yellow-400 bg-yellow-400/10 px-1 rounded shrink-0">{t('match.list.tentative')}</span>
        )}
        {m.final_score && (
          <span className={`text-xs ${textMuted} ml-auto shrink-0`}>{m.final_score}</span>
        )}
      </div>

      {/* 3行目: 進捗 + 操作ボタン */}
      <div className="flex items-center gap-2">
        {m.annotation_status !== 'complete' ? (
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <div className={`h-1 flex-1 ${isLight ? 'bg-gray-100' : 'bg-gray-700'} rounded-full overflow-hidden`}>
              <div
                className="h-full bg-blue-500 rounded-full transition-all"
                style={{ width: `${m.annotation_progress * 100}%` }}
              />
            </div>
            <span className={clsx('text-[10px] shrink-0', statusColor(m.annotation_status))}>
              {t(`match.statuses.${m.annotation_status}`)}
            </span>
            {/* INFRA Phase B: 解析ジョブ状態バッジ */}
            <PipelineJobBadge matchId={m.id} className="shrink-0" />
          </div>
        ) : (
          <span className={clsx('text-[10px] flex-1', statusColor(m.annotation_status))}>
            {t(`match.statuses.${m.annotation_status}`)}
          </span>
        )}
        <button
          onClick={() => navigate(`/annotator/${m.id}`)}
          className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-medium shrink-0"
        >
          <MIcon name="play_arrow" size={12} />
          {t('match.list.open', 'Open')}
        </button>
        {m.player_a_id && (
          <button
            onClick={() => navigate(`/prediction?playerId=${m.player_a_id}`)}
            className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-blue-600 hover:bg-blue-50' : 'text-gray-400 hover:text-blue-400 hover:bg-gray-700'}`}
            title={t('auto.MatchListPage.k5')}
          >
            <MIcon name="trending_up" size={16} />
          </button>
        )}
        {/* 動画 DL バッジ: 進行中なら percent + eta、error なら赤バッジ + 再試行 */}
        {dl && dl.status === 'error' && (
          <button
            type="button"
            onClick={() => onDownload(m)}
            className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded ${
              isLight ? 'bg-red-100 text-red-700 hover:bg-red-200' : 'bg-red-900/40 text-red-300 hover:bg-red-900/60'
            }`}
            title={`DL 失敗: ${dl.error ?? ''}\nクリックで再試行 (オプション選択あり)`}
          >
            <MIcon name="error" size={12} />
            {t('match.list.dl_failed_retry', 'Failed · Retry')}
          </button>
        )}
        {dl && dl.status !== 'error' && (
          <span
            className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded ${
              isLight ? 'bg-blue-100 text-blue-700' : 'bg-blue-900/40 text-blue-300'
            }`}
            title={`DL中 ${dl.percent ?? ''} (残り ${dl.eta ?? '?'})`}
          >
            <MIcon name="download" size={12} className="animate-pulse" />
            {dl.percent ?? 'DL中'}
          </span>
        )}
        {m.video_url && !m.has_video_local && !dl && (
          <button
            onClick={() => onDownload(m)}
            className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'}`}
            title={t('auto.MatchListPage.k6')}
          >
            <MIcon name="download" size={16} />
          </button>
        )}
        <a
          href={`/api/export/package?match_id=${m.id}`}
          download
          title={t('auto.MatchListPage.k7')}
          className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-green-600 hover:bg-green-50' : 'text-gray-400 hover:text-green-400 hover:bg-gray-700'}`}
        >
          <MIcon name="download" size={16} />
        </a>
        <button
          onClick={() => onEdit(m)}
          className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'}`}
          title={t('auto.MatchListPage.k8')}
        >
          <MIcon name="edit" size={16} />
        </button>
        {deleteConfirmId === m.id ? (
          <div className={`flex items-center gap-1 px-1.5 py-0.5 rounded border border-white text-[10px] ${isLight ? 'bg-red-50 text-red-700' : 'bg-red-900/30 text-red-400'}`}>
            <button
              onClick={() => { onDeleteExecute(m.id); onDeleteConfirm(null) }}
              className="font-medium hover:opacity-80"
            >
              {t('match.list.delete_confirm', 'Delete')}
            </button>
            <span className="opacity-50">|</span>
            <button onClick={() => onDeleteConfirm(null)} className="hover:opacity-80">
              {t('match.list.cancel_short', 'Cancel')}
            </button>
          </div>
        ) : (
          <button
            onClick={() => onDeleteConfirm(m.id)}
            className="p-1 rounded text-red-400 hover:text-red-300 hover:bg-red-900/20"
            title={t('auto.MatchListPage.k9')}
          >
            <MIcon name="delete" size={16} />
          </button>
        )}
      </div>
    </div>
  )
}
