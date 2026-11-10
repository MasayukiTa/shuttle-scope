/**
 * 記録画面ヘッダーの「承認待ちデバイス」バッジ。
 *
 * デバイス管理ボタンに重ねて件数を示す。クリックで DeviceManagerPanel を開く。
 * count が 0 のときは何も描画しない（純粋表示コンポーネント）。
 */
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

interface Props {
  count: number
  onClick: () => void
}

export function PendingDeviceBadge({ count, onClick }: Props) {
  const { t } = useTranslation()
  if (count <= 0) return null
  return (
    <button
      type="button"
      data-testid="pending-device-badge"
      onClick={onClick}
      className="relative flex items-center gap-1 px-2 py-1 rounded-ss-md text-xs font-medium transition-colors bg-[var(--ss-warn-tint)] text-[var(--ss-warn)] hover:opacity-90"
      title={t('device_approval.header_badge', { count })}
    >
      <MIcon name="warning" size={12} />
      <span>{t('device_approval.header_badge', { count })}</span>
      <span
        data-testid="pending-device-badge-count"
        className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-ss-pill bg-[var(--ss-bad)] text-white text-[10px] leading-4 text-center"
      >
        {count}
      </span>
    </button>
  )
}
