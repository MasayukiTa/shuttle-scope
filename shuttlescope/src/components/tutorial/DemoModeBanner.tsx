/**
 * demo モード中に画面上部に出す「デモデータ（編集不可）」バナー。
 *
 * useDemoModeStore.active が true の間だけ表示する。実データではなく
 * ランダム生成のデモデータを read-only で見ていることを明示する。
 */
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { useDemoModeStore } from '@/store/demoModeStore'

export function DemoModeBanner() {
  const { t } = useTranslation()
  const active = useDemoModeStore((s) => s.active)
  const target = useDemoModeStore((s) => s.target)
  if (!active) return null
  return (
    <div
      role="status"
      className="fixed top-0 inset-x-0 z-[400] flex items-center justify-center gap-2 bg-amber-500 px-3 py-1.5 text-sm font-medium text-white shadow"
    >
      <MIcon name="visibility" size={16} fill={1} />
      <span>
        {t('demo.banner')}
        {target?.player_name ? t('demo.banner_player', { name: target.player_name }) : ''}
      </span>
    </div>
  )
}
