// R-006: 速報パネル（flash_advice: 5〜7カード）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface FlashAdvicePanelProps {
  matchId: number
  asOfSet: number
  asOfRallyNum?: number
  playerId: number
}

interface AdviceItem {
  category: 'danger' | 'opportunity' | 'pattern' | 'opponent' | 'next_action' | 'trend' | 'fatigue_signal'
  title: string
  body: string
  priority: number
}

interface FlashAdviceResponse {
  success: boolean
  data: {
    items: AdviceItem[]
    item_count: number
    extended_items_included: boolean
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

// カテゴリ別スタイル定義
//
// Design Language v1.2 (2026-05-19) 準拠:
//   - カード bg は無彩色 N_GRAY[800] (ダーク) / N_GRAY[50] (ライト) 固定
//   - 色は **左罫線 3px** のみで意味付け (背景塗らない、半透明色面も使わない)
//   - 「accent なし (neutral)」のカテゴリは罫線も無彩色
//   - next_action だけ罫線 5px に強調 (太さで読む、色は A_GOOD)
//
// accent 色の階層:
//   - B_BAD: 即時注意 (danger 専用)
//   - E_EMPHASIS: 注意喚起 (相手脅威・疲労サイン)
//   - A_GOOD: 推奨アクション (next_action)
//   - 無彩色: 観測情報 (pattern / trend / opportunity)
import { A_GOOD, B_BAD, E_EMPHASIS, N_GRAY } from '@/styles/colors'

type CatStyle = {
  /** カード左罫線の色 (背景は塗らない) */
  accent: string | null
  /** 罫線太さ。next_action は太く強調 */
  borderWidth: number
}

const CATEGORY_STYLE: Record<string, CatStyle> = {
  danger:         { accent: B_BAD,      borderWidth: 3 },   // 即時注意
  fatigue_signal: { accent: E_EMPHASIS, borderWidth: 3 },   // 注意喚起 (能動アクション要求)
  opponent:       { accent: E_EMPHASIS, borderWidth: 3 },   // 相手脅威 (注意喚起)
  next_action:    { accent: A_GOOD,     borderWidth: 5 },   // 推奨アクション (太さで強調)
  opportunity:    { accent: null,       borderWidth: 1 },   // 中立観測 (色なし)
  pattern:        { accent: null,       borderWidth: 1 },   // 観測パターン
  trend:          { accent: null,       borderWidth: 1 },   // 傾向
}

// playerロールに見せるカテゴリ（next_action + opportunity のみ）
const PLAYER_VISIBLE_CATEGORIES = new Set(['next_action', 'opportunity'])

function AdviceCard({ item, isLight }: { item: AdviceItem; isLight: boolean }) {
  const style = CATEGORY_STYLE[item.category] ?? CATEGORY_STYLE.pattern
  // Design Language v1.2 (改訂):
  //   - **左罫線縦バーは禁止** (詐欺サイト感が出るため二度と使わない)。
  //   - bg は無彩色固定、罫線は全周 1px 均等。
  //   - 重要度の表現は:
  //       1. priority バッジ (accent 色)
  //       2. title font-bold (warn 級は accent 色)
  //       3. next_action のみ ▶ chevron prefix で行動を示唆
  const bg = isLight ? '#ffffff' : N_GRAY[800]
  const borderBase = isLight ? N_GRAY[200] : N_GRAY[700]
  const titleColor = isLight ? N_GRAY[900] : N_GRAY[50]
  const bodyColor  = isLight ? N_GRAY[700] : N_GRAY[200]
  const accent = style.accent  // null か A/B/E
  const isHighPriority = item.category === 'danger' || item.category === 'fatigue_signal' || item.category === 'opponent'
  const badgeBg = accent ?? (isLight ? N_GRAY[400] : N_GRAY[600])

  return (
    <div
      className="rounded-ss-md p-3 space-y-1.5"
      style={{
        backgroundColor: bg,
        border: `1px solid ${borderBase}`,
      }}
    >
      <div className="flex items-center gap-2">
        <span
          className="text-[10px] font-bold px-1.5 py-0.5 rounded-ss-sm tabular-nums ss-num"
          style={{ color: '#ffffff', backgroundColor: badgeBg }}
        >
          {item.priority}
        </span>
        <span
          className="text-xs font-bold"
          style={{
            // 警告系のみタイトルに accent 色、それ以外は中立
            color: isHighPriority && accent ? accent : titleColor,
          }}
        >
          {item.title}
        </span>
      </div>
      <p
        className="text-sm leading-relaxed"
        style={{ color: bodyColor }}
      >
        {item.category === 'next_action' && accent ? (
          <span style={{ color: accent, marginRight: '0.25em' }}>▶</span>
        ) : null}
        {item.body}
      </p>
    </div>
  )
}

export function FlashAdvicePanel({ matchId, asOfSet, asOfRallyNum, playerId }: FlashAdvicePanelProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  const params: Record<string, string | number | boolean | null | undefined> = {
    match_id: matchId,
    as_of_set: asOfSet,
    player_id: playerId,
  }
  if (asOfRallyNum != null) {
    params.as_of_rally_num = asOfRallyNum
  }

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-flash-advice', matchId, asOfSet, asOfRallyNum, playerId],
    queryFn: () => apiGet<FlashAdviceResponse>('/analysis/flash_advice', params),
    enabled: !!matchId && !!asOfSet && !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const items = resp?.data?.items ?? []
  const extended = resp?.data?.extended_items_included ?? false

  if (sampleSize === 0 || items.length === 0) {
    return <NoDataMessage sampleSize={sampleSize} minRequired={1} unit="ラリー" />
  }

  return (
    <div className="space-y-3">
      <ConfidenceBadge sampleSize={sampleSize} />

      {extended && (
        <div className="text-[10px] text-gray-400 text-right">
          {t('analysis.flash.extended_label')}
        </div>
      )}

      {/* analyst / coach: 全カード表示 */}
      <RoleGuard
        allowedRoles={['analyst', 'coach']}
        fallback={
          <div className="space-y-2">
            {items
              .filter((item) => PLAYER_VISIBLE_CATEGORIES.has(item.category))
              .map((item) => (
                <AdviceCard key={item.category} item={item} isLight={isLight} />
              ))}
          </div>
        }
      >
        <div className="space-y-2">
          {items.map((item) => (
            <AdviceCard key={item.category} item={item} isLight={isLight} />
          ))}
        </div>
      </RoleGuard>
    </div>
  )
}
