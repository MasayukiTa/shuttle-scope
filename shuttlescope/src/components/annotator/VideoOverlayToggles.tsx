/**
 * U5: 動画右上に浮く overlay 切替ボタン群。
 *
 * YouTube Studio 風: 動画要素の右上にアイコンだけ並べる。
 * 上バーの混雑を解消し、視覚的にも overlay が動画関連であることを示す。
 *
 * トグル種:
 *   - CV (player bbox)
 *   - shuttle track
 *   - court grid
 *   - pose keypoints (Track C2 RTMPose 統合口)
 *   - fullscreen
 *
 * 各トグルは props で個別に制御可能。data なし時は disabled。
 */
import { clsx } from 'clsx'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

interface ToggleSpec {
  key: string
  icon: string
  label: string
  on: boolean
  onClick: () => void
  disabled?: boolean
}

interface VideoOverlayTogglesProps {
  cv?: { on: boolean; toggle: () => void; available?: boolean }
  shuttle?: { on: boolean; toggle: () => void; available?: boolean }
  court?: { on: boolean; toggle: () => void; available?: boolean }
  pose?: { on: boolean; toggle: () => void; available?: boolean }
  fullscreen?: { on: boolean; toggle: () => void }
  className?: string
}

export function VideoOverlayToggles({
  cv, shuttle, court, pose, fullscreen, className,
}: VideoOverlayTogglesProps) {
  const { t } = useTranslation()
  const toggles: ToggleSpec[] = []
  if (cv) toggles.push({
    key: 'cv', icon: 'directions_run', label: t('annotator.ux.overlay_cv'),
    on: cv.on, onClick: cv.toggle, disabled: cv.available === false,
  })
  if (shuttle) toggles.push({
    key: 'shuttle', icon: 'sports_tennis', label: t('annotator.ux.overlay_shuttle'),
    on: shuttle.on, onClick: shuttle.toggle, disabled: shuttle.available === false,
  })
  if (court) toggles.push({
    key: 'court', icon: 'grid_on', label: t('annotator.ux.overlay_court'),
    on: court.on, onClick: court.toggle, disabled: court.available === false,
  })
  if (pose) toggles.push({
    key: 'pose', icon: 'accessibility_new', label: t('annotator.ux.overlay_pose'),
    on: pose.on, onClick: pose.toggle, disabled: pose.available === false,
  })
  if (fullscreen) toggles.push({
    key: 'fullscreen', icon: fullscreen.on ? 'fullscreen_exit' : 'fullscreen', label: t('annotator.ux.overlay_fullscreen'),
    on: fullscreen.on, onClick: fullscreen.toggle,
  })

  if (toggles.length === 0) return null

  return (
    <div
      className={clsx(
        'absolute top-2 right-2 z-20 flex flex-col gap-1.5 bg-black/60 rounded-md p-1 backdrop-blur',
        className,
      )}
    >
      {toggles.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={t.onClick}
          disabled={t.disabled}
          aria-pressed={t.on}
          aria-label={t.label}
          title={t.label}
          className={clsx(
            'flex items-center justify-center w-8 h-8 rounded transition-colors',
            t.disabled
              ? 'opacity-30 cursor-not-allowed text-gray-400'
              : t.on
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800/80 text-gray-300 hover:bg-gray-700/80',
          )}
        >
          <MIcon name={t.icon} size={18} fill={t.on ? 1 : 0} />
        </button>
      ))}
    </div>
  )
}
