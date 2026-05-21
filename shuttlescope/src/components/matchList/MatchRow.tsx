import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { Play, Download, Trash2, Pencil, TrendingUp } from 'lucide-react'
import { Match } from '@/types'
import { useCardTheme } from '@/hooks/useCardTheme'
import { PipelineJobBadge } from '@/components/analysis/PipelineJobBadge'
import { statusColor, DownloadStatus } from './matchListUtils'

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

  return (
    <tr className={`border-b ${isLight ? 'border-gray-100 hover:bg-gray-50' : 'border-gray-800 hover:bg-gray-800/50'}`}>
      <td className="py-2 pr-2">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(m.id)}
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
        <span className="text-sm">
          {m.player_b?.name ?? `#${m.player_b_id}`}
          {m.partner_b?.name && ` / ${m.partner_b.name}`}
        </span>
        {m.player_b?.needs_review && (
          <span className="ml-1 text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded" title={t('player.profile_status_provisional')}>
            {t('match.list.tentative', 'Tentative')}
          </span>
        )}
      </td>
      <td className="py-2 pr-4">
        <span className={clsx(
          'font-medium',
          m.result === 'win' ? 'text-green-400' : m.result === 'loss' ? 'text-red-400' : 'text-gray-400'
        )}>
          {t(`match.results.${m.result}`)}
        </span>
        {m.final_score && <span className={`${textMuted} ml-1 text-xs`}>{m.final_score}</span>}
      </td>
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
          >
            <Play size={14} />
          </button>
          {m.player_a_id && (
            <button
              onClick={() => navigate(`/prediction?playerId=${m.player_a_id}`)}
              className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
              title={t('auto.MatchListPage.k5')}
            >
              <TrendingUp size={14} />
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
              <Download size={12} className="animate-pulse" />
              {dl.percent ?? 'DL中'}
            </span>
          )}
          {m.video_url && !m.has_video_local && !dl && (
            <button
              onClick={() => onDownload(m)}
              className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
              title="動画ダウンロード (オプション選択)"
            >
              <Download size={14} />
            </button>
          )}
          <button
            onClick={() => onEdit(m)}
            className={`p-1.5 rounded ${isLight ? 'bg-gray-200 hover:bg-gray-300 text-gray-600' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
            title={t('auto.MatchListPage.k11')}
          >
            <Pencil size={14} />
          </button>
          {deleteConfirmId === m.id ? (
            <div className={`flex items-center gap-1 px-2 py-1 rounded border border-white text-xs ${isLight ? 'bg-red-50 text-red-700' : 'bg-red-900/30 text-red-400'}`}>
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
              className="p-1.5 rounded bg-red-900/50 hover:bg-red-700 text-red-400"
              title={t('auto.MatchListPage.k9')}
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}
