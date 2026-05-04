// PredictionDriversBlock — 予測根拠・データソース内訳 (Spec §3.5 / §3.6)
import { useTranslation } from 'react-i18next'
import { WIN } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface Driver {
  label: string
  type: string
  count: number
  weight: 'primary' | 'secondary' | 'background' | 'contextual'
}

interface PredictionDriversBlockProps {
  primaryType: string
  primaryCount: number
  h2hCount: number
  sameLevelCount: number
  allCount: number
  hasObservations: boolean
  drivers: Driver[]
}

const WEIGHT_LABEL: Record<string, string> = {
  primary: '主',
  secondary: '副',
  background: '参照',
  contextual: '文脈',
}

const PRIMARY_TYPE_LABEL: Record<string, string> = {
  h2h: '直接対戦データ',
  level: '同大会レベルデータ',
  all: '全試合データ',
}

export function PredictionDriversBlock({
  primaryType,
  primaryCount,
  h2hCount,
  sameLevelCount,
  allCount,
  hasObservations,
  drivers,
}: PredictionDriversBlockProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'

  const primaryLabel = PRIMARY_TYPE_LABEL[primaryType] ?? '全試合データ'

  return (
    <div className="space-y-2">
      {/* 主要データソースサマリー */}
      <p className="text-xs" style={{ color: neutral }}>
        主に <span style={{ color: WIN }} className="font-medium">{primaryLabel}（{primaryCount}試合）</span> を使用して算出
      </p>

      {/* ドライバーリスト */}
      <div className="space-y-1">
        {drivers.map((d, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span
              className="text-[10px] px-1 py-0.5 rounded shrink-0"
              style={{
                color: d.weight === 'primary' ? WIN : subText,
                border: `1px solid ${d.weight === 'primary' ? WIN + '66' : '#374151'}`,
                backgroundColor: d.weight === 'primary' ? WIN + '18' : 'transparent',
              }}
            >
              {WEIGHT_LABEL[d.weight] ?? d.weight}
            </span>
            <span style={{ color: d.weight === 'primary' ? neutral : subText }}>{d.label}</span>
            <span className="font-mono" style={{ color: subText }}>
              {d.type === 'observation' ? `${d.count}項目` : `${d.count}試合`}
            </span>
          </div>
        ))}
      </div>

      {/* 観察データバッジ */}
      {hasObservations && (
        <p className="text-[10px]" style={{ color: subText }}>
          ✓ {t('prediction.observation_augmented')}
        </p>
      )}
    </div>
  )
}
