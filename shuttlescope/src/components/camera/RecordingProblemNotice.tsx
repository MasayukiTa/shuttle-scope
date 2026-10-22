import { useTranslation } from 'react-i18next'
import { MIcon } from '../common/MIcon'

interface RecordingProblemNoticeProps {
  /** State reported by useServerSideRecording. */
  state: string
  /** Latest message reported by useServerSideRecording (init, chunk or finalize failure). */
  errorMsg: string | null
}

/**
 * Shows the sender that the automatic server-side recording failed, lost chunks, or did
 * not finalize. The hook already tracks these; without this the operator keeps seeing the
 * "recording" screen while nothing is saved.
 */
export function RecordingProblemNotice({ state, errorMsg }: RecordingProblemNoticeProps) {
  const { t } = useTranslation()
  if (state !== 'error' && !errorMsg) return null
  return (
    <div
      role="alert"
      className="w-full max-w-sm mb-3 flex items-start gap-1.5 text-[var(--ss-bad)] text-xs bg-[rgba(194,51,74,0.08)] rounded-[5px] p-2 border border-[var(--ss-border)]"
    >
      <MIcon name="cancel" size={14} className="shrink-0 mt-0.5" />
      <div>
        <p className="font-medium">{t('camera_sender.recording_problem_title')}</p>
        <p>{t('camera_sender.recording_problem_hint')}</p>
        {errorMsg && <p className="mt-1 break-words">{errorMsg}</p>}
      </div>
    </div>
  )
}
