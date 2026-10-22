import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { Match } from '@/types'
import { useCardTheme } from '@/hooks/useCardTheme'
import { PipelineJobBadge } from '@/components/analysis/PipelineJobBadge'
import { statusColor, DownloadStatus } from './matchListUtils'
import { MIcon } from '@/components/common/MIcon'
import { useAuth } from '@/hooks/useAuth'
import { isPlayableVideoUrl } from '@/utils/videoSrc'
import { canDeleteMatch, canWriteMatch } from '@/utils/roleAccess'

// MatchListPage のデスクトップ用テーブル行 1 件分。純粋抽出 (behavior 不変)。
export interface MatchRowProps {
  match: Match
  selected: boolean
  onToggleSelect: (id: number) => void
  dl?: DownloadStatus
  onDownload: (m: Match) => void
  onEdit: (m: Match) => void
  deleteConfirmId: number | null
  onDeleteConfirm: (id: number | null) => void
  onDeleteExecute: (id: number) => void
}

export function MatchRow({
  match: m, selected, onToggleSelect, dl, onDownload, onEdit,
  deleteConfirmId, onDeleteConfirm, onDeleteExecute,
}: MatchRowProps) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { isLight, textMuted, textSecondary } = useCardTheme()
  // 製品ルール: player には勝敗・スコア列を出さない (ヘッダ列は MatchListPage 側で同じ条件で非表示)。
  const { role, hasPageAccess } = useAuth()
  // 予測ページは PageAccessRoute('prediction') で守られている。権限が無い利用者に
  // ボタンを出すと、押しても説明なしに一覧へ戻されるだけになる。
  const canOpenPrediction = hasPageAccess('prediction')
  const isPlayer = role === 'player'
  // 行ごとの操作ボタンは、アイコンだけだと「どの試合の操作か」が支援技術に伝わらない。
  // 日付 / 大会 / 相手を操作名に付ける。
  const opponentName = m.player_b?.name ?? `#${m.player_b_id}`
  const rowLabel = [m.date, m.tournament, opponentName].filter(Boolean).join(' / ')
  const actionLabel = (action: string) => t('a11yLabels.match_action', { action, label: rowLabel })

  return (
    <tr className={`border-b ${isLight ? 'border-gray-100 hover:bg-gray-50' : 'border-gray-800 hover:bg-gray-800/50'}`}>
      <td className="py-2 pr-2">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(m.id)}
          aria-label={t('a11yLabels.select_match', { label: rowLabel })}
          className="accent-blue-500"
        />
      </td>
      <td className={`py-2 pr-4 ${textSecondary}`}>{m.date}</td>
      <td className="py-2 pr-4">{m.tournament}</td>
      <td className="py-2 pr-4">
        <span className={`px-1.5 py-0.5 rounded text-xs ${isLight ? 'bg-gray-200 text-gray-700' : 'bg-gray-700'}`}>{m.tournament_level}</span>
        {m.is_public_pool && (
          <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-400" title={t('match.list.public_pool_title', 'Public-pool match visible to all teams')}>
            {t('match.list.public_pool_badge', 'Shared')}
          </span>
        )}
        {m.owner_team_display_id && (
          <span className={`ml-1 text-[10px] ${textSecondary}`} title={`登録チーム: ${m.owner_team_display_name ?? ''}`}>
            [{m.owner_team_display_id}]
          </span>
        )}
      </td>
      <td className={`py-2 pr-4 ${textSecondary}`}>{t(`match.formats.${m.format}`)}</td>
      <td className="py-2 pr-4">
        {/* 極端に長い名前で列が広がらないよう省略表示にし、全文は title で読めるようにする */}
        <span
          className="text-sm inline-block max-w-[16rem] truncate align-bottom"
          title={`${opponentName}${m.partner_b?.name ? ` / ${m.partner_b.name}` : ''}`}
        >
          {opponentName}
          {m.partner_b?.name && ` / ${m.partner_b.name}`}
        </span>
        {m.player_b?.needs_review && (
          <span className="ml-1 text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded" title={t('player.profile_status_provisional')}>
            {t('match.list.tentative', 'Tentative')}
          </span>
        )}
      </td>
      {!isPlayer && (
        <td className="py-2 pr-4">
          <span className={clsx(
            'font-medium',
            m.result === 'win' ? 'text-green-400' : m.result === 'loss' ? 'text-red-400' : 'text-gray-400'
          )}>
            {t(`match.results.${m.result}`)}
          </span>
          {m.final_score && <span className={`${textMuted} ml-1 text-xs`}>{m.final_score}</span>}
        </td>
      )}
      <td className="py-2 pr-4">
        <div className="flex items-center gap-2">
          <div className={`w-20 h-1.5 ${isLight ? 'bg-gray-200' : 'bg-gray-700'} rounded-full overflow-hidden`}>
            <div
              className="h-full bg-blue-500"
              style={{ width: `${m.annotation_progress * 100}%` }}
            />
          </div>
          <span className={clsx('text-xs', statusColor(m.annotation_status))}>
            {t(`match.statuses.${m.annotation_status}`)}
          </span>
          {/* INFRA Phase B: 解析ジョブ状態バッジ */}
          <PipelineJobBadge matchId={m.id} />
        </div>
      </td>
      <td className="py-2">
        <div className="flex items-center gap-1">
          <button
            onClick={() => navigate(`/annotator/${m.id}`)}
            className="p-1.5 rounded bg-blue-700 hover:bg-blue-600 text-white"
            title={t('match.start_annotation')}
            aria-label={actionLabel(t('match.start_annotation'))}
          >
            <MIcon name="play_arrow" size={14} />
          </button>
          {m.player_a_id && canOpenPrediction && (
            <button
              onClick={() => navigate(`/prediction?playerId=${m.player_a_id}`)}
              className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
              title={t('auto.MatchListPage.k5')}
              aria-label={actionLabel(t('auto.MatchListPage.k5'))}
            >
              <MIcon name="trending_up" size={14} />
            </button>
          )}
          {/* 動画 DL バッジ: 進行中なら percent を表示 */}
          {dl && (
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
          {isPlayableVideoUrl(m.video_url) && !m.has_video_local && !dl && (
            <button
              onClick={() => onDownload(m)}
              className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
              title={t('auto.MatchListPage.k6')}
              aria-label={actionLabel(t('auto.MatchListPage.k6'))}
            >
              <MIcon name="download" size={14} />
            </button>
          )}
          {/* 編集 / 削除は backend の権限 (編集: admin/coach/analyst、削除: admin/analyst) と同じ条件でだけ出す。 */}
          {canWriteMatch(role) && (
          <button
            onClick={() => onEdit(m)}
            className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
            title={t('auto.MatchListPage.k11')}
            aria-label={actionLabel(t('auto.MatchListPage.k11'))}
          >
            <MIcon name="edit" size={14} />
          </button>
          )}
          {!canDeleteMatch(role) ? null : deleteConfirmId === m.id ? (
            <div className={`flex items-center gap-1 px-2 py-1 rounded border border-white text-xs ${isLight ? 'bg-red-50 text-red-700' : 'bg-red-900/30 text-red-400'}`}>
              <button
                onClick={() => { onDeleteExecute(m.id); onDeleteConfirm(null) }}
                className="font-medium hover:opacity-80"
                aria-label={actionLabel(t('match.list.delete_confirm', 'Delete'))}
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
              className="p-1.5 rounded bg-red-900/50 hover:bg-red-700 text-red-400"
              title={t('auto.MatchListPage.k9')}
              aria-label={actionLabel(t('auto.MatchListPage.k9'))}
            >
              <MIcon name="delete" size={14} />
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}
