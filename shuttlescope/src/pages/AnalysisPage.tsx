/**
 * 解析ページ (選手ロール向けの安全な分析サマリ)。
 *
 * CLAUDE.md の non-negotiable rule:
 *  - 選手画面に直接の "weakness" / EPV / 絶対勝率は表示しない
 *  - 必ず不確実性 (uncertainty / sample-size warning) を併記
 *  - 伸びしろ (growth oriented) 表現を使う
 *
 * このページは player 専用 (coach/analyst/admin は dashboard を使う) ですが、
 * ルール上 admin/coach/analyst が view しても問題が無いよう、表示内容を
 * "client-safe summary" に限定します。
 *
 * 初期実装はミニマル: 試合数 / 体調記録数 / 「準備中」セクション。
 * 今後 player-safe analytics モジュールを追加していく足場。
 */
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { apiGet } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'

interface MatchRow {
  id: number
  date?: string | null
  result?: string | null
  player_a_id?: number | null
  player_b_id?: number | null
}

export function AnalysisPage() {
  const { t } = useTranslation()
  const { theme } = useTheme()
  const { role, playerId, displayName } = useAuth()
  const isLight = theme === 'light'

  const matchesQuery = useQuery<{ data?: MatchRow[] }>({
    queryKey: ['analysis-matches', playerId],
    queryFn: () => apiGet(`/matches${playerId ? `?player_id=${playerId}` : ''}`),
    enabled: true,
  })

  const matches = matchesQuery.data?.data ?? []
  const matchCount = matches.length
  // 結果別カウント。「勝率」表記は player 画面では使わず、件数のみ。
  const winCount = matches.filter((m) => m.result === 'win').length
  const lossCount = matches.filter((m) => m.result === 'loss').length

  const cardBg = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'
  const text = isLight ? 'text-gray-900' : 'text-white'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const headingClass = isLight ? 'text-gray-900' : 'text-gray-100'

  return (
    <div className={`h-full overflow-y-auto p-4 md:p-6 ${text}`}>
      <div className="max-w-3xl mx-auto space-y-4">
        <header className="mb-2">
          <h1 className={`text-xl font-semibold ${headingClass}`}>{t('nav.analysis', { defaultValue: '解析' })}</h1>
          <p className={`text-xs ${textMuted} mt-1`}>
            {displayName ? `${displayName} さんの` : 'あなたの'}試合・体調記録から見た成長まとめ
          </p>
        </header>

        {/* サマリカード */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <div className={`rounded-lg border p-3 ${cardBg}`}>
            <div className={`text-xs ${textMuted} mb-1`}>記録された試合</div>
            <div className="text-2xl font-bold">
              {matchesQuery.isLoading ? '...' : matchCount}
            </div>
          </div>
          <div className={`rounded-lg border p-3 ${cardBg}`}>
            <div className={`text-xs ${textMuted} mb-1`}>勝利として記録</div>
            <div className="text-2xl font-bold text-emerald-500">{winCount}</div>
          </div>
          <div className={`rounded-lg border p-3 ${cardBg}`}>
            <div className={`text-xs ${textMuted} mb-1`}>学びを得た試合</div>
            <div className="text-2xl font-bold text-blue-500">{lossCount}</div>
          </div>
        </div>

        {/* サンプルサイズ警告 */}
        {matchCount < 10 && (
          <div
            className={`rounded-lg border-l-4 border-amber-500 p-3 text-sm ${
              isLight ? 'bg-amber-50 text-amber-900' : 'bg-amber-900/20 text-amber-200'
            }`}
          >
            ⚠️ サンプル数が少ない ({matchCount} 試合) ため、傾向の信頼性は限定的です。
            もう少し試合が記録されると傾向解析が利用可能になります。
          </div>
        )}

        {/* 準備中セクション */}
        <section className={`rounded-lg border p-4 ${cardBg}`}>
          <h2 className={`text-base font-medium mb-2 ${headingClass}`}>準備中の解析</h2>
          <p className={`text-xs ${textMuted} mb-3`}>
            以下の指標は近日中に追加予定です。すべて「不確実性つき」「伸びしろ表現」の player-safe 設計です。
          </p>
          <ul className={`text-sm ${textMuted} space-y-1 list-disc pl-5`}>
            <li>ショット種類ごとの成功傾向 (信頼区間つき)</li>
            <li>コート位置別の得意ゾーン (発展余地マップ)</li>
            <li>サーブ・レシーブの組み立て傾向</li>
            <li>コンディション (体調記録) と試合パフォーマンスの関連</li>
            <li>時系列での成長カーブ</li>
          </ul>
        </section>

        {/* デバッグ用: ロール確認 (admin が誤って見たとき) */}
        {role && role !== 'player' && (
          <div className={`rounded-lg border p-3 text-xs ${textMuted} ${cardBg}`}>
            ℹ️ あなたは <b>{role}</b> ロールです。詳細な解析は <a className="text-blue-500 underline" href="/dashboard">/dashboard</a> から利用できます。
          </div>
        )}
      </div>
    </div>
  )
}
