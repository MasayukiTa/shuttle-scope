import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiGetBlob } from '@/api/client'
import { saveBlobAs } from '@/utils/saveBlob'
import { clsx } from 'clsx'
import { Match } from '@/types'
import { useCardTheme } from '@/hooks/useCardTheme'
import { PipelineJobBadge } from '@/components/analysis/PipelineJobBadge'
import { statusColor, DownloadStatus } from './matchListUtils'
import { MIcon } from '@/components/common/MIcon'
import { useAuth } from '@/hooks/useAuth'
import { isPlayableVideoUrl } from '@/utils/videoSrc'

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
  // 製品ルール: player には勝敗・スコアを見せない (API も result / final_score を返さない)。
  // 値が無いまま描くと t('match.results.undefined') の生キーが出るため、行ごと描かない。
  const { role, hasPageAccess } = useAuth()
  // 予測ページは PageAccessRoute('prediction') で守られている。権限が無い利用者に
  // ボタンを出すと、押しても説明なしに一覧へ戻されるだけになる。
  const canOpenPrediction = hasPageAccess('prediction')
  const isPlayer = role === 'player'
  // 操作ボタンの accessible name に試合 (日付 / 大会 / 相手) を含める (MatchRow と同じ形式)
  const opponentName = m.player_b?.name ?? `#${m.player_b_id}`
  const rowLabel = [m.date, m.tournament, opponentName].filter(Boolean).join(' / ')
  const actionLabel = (action: string) => t('a11yLabels.match_action', { action, label: rowLabel })

  // .sspkg の取得は Bearer 付きの fetch で行う (生リンクは Authorization を付けられず 401 になる)。
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const handleExport = async () => {
    if (exporting) return
    setExporting(true)
    setExportError(null)
    try {
      const { blob, filename } = await apiGetBlob('/export/package', { match_id: m.id })
      saveBlobAs(blob, filename ?? `match_${m.id}.json`)
    } catch (e) {
      const status = (e as { status?: number } | null)?.status
      setExportError(
        status === 401 || status === 403
          ? t('match.list.export_denied')
          : t('match.list.export_failed'),
      )
    } finally {
      setExporting(false)
    }
  }

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
        {!isPlayer && (
          <span className={clsx(
            'text-xs font-bold shrink-0',
            m.result === 'win' ? 'text-green-400' : m.result === 'loss' ? 'text-red-400' : 'text-gray-400'
          )}>
            {t(`match.results.${m.result}`)}
          </span>
        )}
      </div>

      {/* 2行目: 対戦情報 */}
      <div className="flex items-center gap-1 mb-1 text-sm">
        <span className={`text-[10px] ${textMuted} shrink-0`}>{t(`match.formats.${m.format}`)}</span>
        <span
          className={`${textSecondary} truncate`}
          title={`${opponentName}${m.partner_b?.name ? ` / ${m.partner_b.name}` : ''}`}
        >
          {t('match.list.vs', 'vs')} {opponentName}
          {m.partner_b?.name && ` / ${m.partner_b.name}`}
        </span>
        {m.player_b?.needs_review && (
          <span className="text-[10px] text-yellow-400 bg-yellow-400/10 px-1 rounded shrink-0">{t('match.list.tentative')}</span>
        )}
        {!isPlayer && m.final_score && (
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
          aria-label={actionLabel(t('match.start_annotation'))}
          className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-medium shrink-0"
        >
          <MIcon name="play_arrow" size={12} />
          {t('match.list.open', 'Open')}
        </button>
        {m.player_a_id && canOpenPrediction && (
          <button
            onClick={() => navigate(`/prediction?playerId=${m.player_a_id}`)}
            className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-blue-600 hover:bg-blue-50' : 'text-gray-400 hover:text-blue-400 hover:bg-gray-700'}`}
            title={t('auto.MatchListPage.k5')}
            aria-label={actionLabel(t('auto.MatchListPage.k5'))}
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
        {isPlayableVideoUrl(m.video_url) && !m.has_video_local && !dl && (
          <button
            onClick={() => onDownload(m)}
            className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'}`}
            title={t('auto.MatchListPage.k6')}
            aria-label={actionLabel(t('auto.MatchListPage.k6'))}
          >
            <MIcon name="download" size={16} />
          </button>
        )}
        <button
          type="button"
          data-testid="match-export"
          onClick={handleExport}
          disabled={exporting}
          title={t('auto.MatchListPage.k7')}
          aria-label={actionLabel(t('auto.MatchListPage.k7'))}
          className={`p-1 rounded disabled:opacity-50 ${isLight ? 'text-gray-500 hover:text-green-600 hover:bg-green-50' : 'text-gray-400 hover:text-green-400 hover:bg-gray-700'}`}
        >
          <MIcon name="download" size={16} />
        </button>
        {exportError && (
          <span role="alert" className="text-[10px] text-red-400">{exportError}</span>
        )}
        <button
          onClick={() => onEdit(m)}
          className={`p-1 rounded ${isLight ? 'text-gray-500 hover:text-gray-700 hover:bg-gray-100' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'}`}
          title={t('auto.MatchListPage.k8')}
          aria-label={actionLabel(t('auto.MatchListPage.k8'))}
        >
          <MIcon name="edit" size={16} />
        </button>
        {deleteConfirmId === m.id ? (
          <div className={`flex items-center gap-1 px-1.5 py-0.5 rounded border border-white text-[10px] ${isLight ? 'bg-red-50 text-red-700' : 'bg-red-900/30 text-red-400'}`}>
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
            className="p-1 rounded text-red-400 hover:text-red-300 hover:bg-red-900/20"
            title={t('auto.MatchListPage.k9')}
            aria-label={actionLabel(t('auto.MatchListPage.k9'))}
          >
            <MIcon name="delete" size={16} />
          </button>
        )}
      </div>
    </div>
  )
}
