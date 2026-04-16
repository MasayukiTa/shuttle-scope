import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet, apiPost } from '@/api/client'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'

// ─── 型定義 ───────────────────────────────────────────
type PostureCollapse = 'none' | 'minor' | 'major'
type WeightDistribution = 'left' | 'right' | 'center' | 'floating'
type ShotTiming = 'early' | 'optimal' | 'late'
type Confidence = 1 | 2 | 3

interface ExpertClip {
  stroke_id: number
  frame_index: number
  clip_start_frame: number
  clip_end_frame: number
  clip_url: string
  shot_type?: string
  miss_type?: string
}

interface ClipsResponse {
  clips: ExpertClip[]
}

interface ExpertLabel {
  stroke_id: number
  frame_index: number
  clip_start_frame: number
  clip_end_frame: number
  posture_collapse: PostureCollapse
  weight_distribution: WeightDistribution
  shot_timing: ShotTiming
  confidence: Confidence
  comment: string
  annotator_role: string
}

interface LabelsResponse {
  labels: ExpertLabel[]
}

// ラジオ選択肢の構成
const POSTURE_OPTIONS: { value: PostureCollapse; key: string }[] = [
  { value: 'none', key: 'expert_labeler.posture_none' },
  { value: 'minor', key: 'expert_labeler.posture_minor' },
  { value: 'major', key: 'expert_labeler.posture_major' },
]
const WEIGHT_OPTIONS: { value: WeightDistribution; key: string }[] = [
  { value: 'left', key: 'expert_labeler.weight_left' },
  { value: 'right', key: 'expert_labeler.weight_right' },
  { value: 'center', key: 'expert_labeler.weight_center' },
  { value: 'floating', key: 'expert_labeler.weight_floating' },
]
const TIMING_OPTIONS: { value: ShotTiming; key: string }[] = [
  { value: 'early', key: 'expert_labeler.timing_early' },
  { value: 'optimal', key: 'expert_labeler.timing_optimal' },
  { value: 'late', key: 'expert_labeler.timing_late' },
]

// 初期フォーム状態
interface FormState {
  posture_collapse: PostureCollapse | null
  weight_distribution: WeightDistribution | null
  shot_timing: ShotTiming | null
  confidence: Confidence
  comment: string
}

function emptyForm(): FormState {
  return {
    posture_collapse: null,
    weight_distribution: null,
    shot_timing: null,
    confidence: 2,
    comment: '',
  }
}

// ─── 本体 ─────────────────────────────────────────────
function AnnotateContent() {
  const { matchId } = useParams<{ matchId: string }>()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { role } = useAuth()
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const queryClient = useQueryClient()

  const annotatorRole = role === 'coach' ? 'coach' : 'analyst'

  // クリップ一覧取得
  const clipsQuery = useQuery<ClipsResponse>({
    queryKey: ['expert', 'clips', matchId],
    queryFn: () => apiGet<ClipsResponse>('/v1/expert/clips', { match_id: matchId! }),
    enabled: !!matchId,
  })

  // 既存ラベル取得
  const labelsQuery = useQuery<LabelsResponse>({
    queryKey: ['expert', 'labels', matchId, annotatorRole],
    queryFn: () =>
      apiGet<LabelsResponse>('/v1/expert/labels', {
        match_id: matchId!,
        annotator_role: annotatorRole,
      }),
    enabled: !!matchId,
  })

  const clips = clipsQuery.data?.clips ?? []
  const labels = labelsQuery.data?.labels ?? []

  // stroke_id → 既存ラベルの索引
  const labelByStroke = useMemo(() => {
    const m = new Map<number, ExpertLabel>()
    labels.forEach((l) => m.set(l.stroke_id, l))
    return m
  }, [labels])

  const [index, setIndex] = useState(0)
  const [form, setForm] = useState<FormState>(emptyForm())
  const [toast, setToast] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  const currentClip = clips[index]

  // 初回ロード時、未完了の最初のクリップへ（再開）
  const initialAppliedRef = useRef(false)
  useEffect(() => {
    if (initialAppliedRef.current) return
    if (clipsQuery.isLoading || labelsQuery.isLoading) return
    if (clips.length === 0) return
    const firstUnlabeled = clips.findIndex((c) => !labelByStroke.has(c.stroke_id))
    setIndex(firstUnlabeled >= 0 ? firstUnlabeled : 0)
    initialAppliedRef.current = true
  }, [clipsQuery.isLoading, labelsQuery.isLoading, clips, labelByStroke])

  // index 変更時、既存ラベルがあれば prefill、無ければ空
  useEffect(() => {
    if (!currentClip) return
    const existing = labelByStroke.get(currentClip.stroke_id)
    if (existing) {
      setForm({
        posture_collapse: existing.posture_collapse,
        weight_distribution: existing.weight_distribution,
        shot_timing: existing.shot_timing,
        confidence: (existing.confidence as Confidence) || 2,
        comment: existing.comment || '',
      })
    } else {
      setForm(emptyForm())
    }
  }, [currentClip?.stroke_id, labelByStroke])

  // 保存
  const saveMutation = useMutation({
    mutationFn: async (opts: { skip?: boolean }) => {
      if (!currentClip || !matchId) throw new Error('no clip')
      const payload = {
        match_id: matchId,
        stroke_id: currentClip.stroke_id,
        frame_index: currentClip.frame_index,
        clip_start_frame: currentClip.clip_start_frame,
        clip_end_frame: currentClip.clip_end_frame,
        posture_collapse: opts.skip ? 'skipped' : form.posture_collapse,
        weight_distribution: opts.skip ? 'skipped' : form.weight_distribution,
        shot_timing: opts.skip ? 'skipped' : form.shot_timing,
        confidence: form.confidence,
        comment: form.comment,
        annotator_role: annotatorRole,
      }
      return apiPost('/v1/expert/labels', payload)
    },
    onSuccess: () => {
      setToast(t('expert_labeler.saved'))
      queryClient.invalidateQueries({ queryKey: ['expert', 'labels', matchId, annotatorRole] })
      queryClient.invalidateQueries({ queryKey: ['expert', 'progress'] })
      // 次のクリップへ
      setIndex((i) => Math.min(i + 1, clips.length - 1))
      window.setTimeout(() => setToast(null), 1500)
    },
    onError: () => {
      setToast(t('expert_labeler.save_error'))
      window.setTimeout(() => setToast(null), 2000)
    },
  })

  const handleSave = useCallback(() => {
    // 必須項目未選択時は保存不可
    if (!form.posture_collapse || !form.weight_distribution || !form.shot_timing) {
      setToast(t('expert_labeler.required_fields'))
      window.setTimeout(() => setToast(null), 1500)
      return
    }
    saveMutation.mutate({ skip: false })
  }, [form, saveMutation, t])

  const handleSkip = useCallback(() => {
    saveMutation.mutate({ skip: true })
  }, [saveMutation])

  const goPrev = useCallback(() => setIndex((i) => Math.max(0, i - 1)), [])
  const goNext = useCallback(
    () => setIndex((i) => Math.min(clips.length - 1, i + 1)),
    [clips.length]
  )

  const togglePlay = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) void v.play()
    else v.pause()
  }, [])

  // キーボードショートカット
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // textarea フォーカス中は Enter と数字以外処理しない（コメント入力を妨げない）
      const target = e.target as HTMLElement | null
      const isEditable =
        target &&
        (target.tagName === 'TEXTAREA' ||
          target.tagName === 'INPUT' ||
          target.isContentEditable)
      if (isEditable) return

      switch (e.key) {
        case 'ArrowLeft':
        case 'j':
        case 'J':
          e.preventDefault()
          goPrev()
          break
        case 'ArrowRight':
        case 'l':
        case 'L':
          e.preventDefault()
          goNext()
          break
        case 'k':
        case 'K':
          e.preventDefault()
          togglePlay()
          break
        case '1':
          setForm((f) => ({ ...f, confidence: 1 }))
          break
        case '2':
          setForm((f) => ({ ...f, confidence: 2 }))
          break
        case '3':
          setForm((f) => ({ ...f, confidence: 3 }))
          break
        case 'Enter':
          e.preventDefault()
          handleSave()
          break
        case 's':
        case 'S':
          e.preventDefault()
          handleSkip()
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [goPrev, goNext, togglePlay, handleSave, handleSkip])

  const bgBase = isLight ? 'bg-gray-50 text-gray-900' : 'bg-gray-900 text-gray-100'
  const panelBg = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'
  const btnLarge =
    'px-4 py-3 rounded-lg font-medium text-base select-none'
  const btnPrimary = 'bg-blue-500 hover:bg-blue-600 text-white'
  const btnSecondary = isLight
    ? 'bg-gray-200 hover:bg-gray-300 text-gray-900'
    : 'bg-gray-700 hover:bg-gray-600 text-gray-100'

  // ラジオボタン（iPad 向けに十分な大きさ）
  const renderRadioGroup = <T extends string>(
    labelKey: string,
    options: { value: T; key: string }[],
    value: T | null,
    onChange: (v: T) => void
  ) => (
    <div className="mb-4">
      <div className="text-sm font-semibold mb-2">{t(labelKey)}</div>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const selected = value === opt.value
          return (
            <button
              type="button"
              key={opt.value}
              onClick={() => onChange(opt.value)}
              className={`${btnLarge} border ${
                selected
                  ? 'bg-blue-500 border-blue-500 text-white'
                  : isLight
                  ? 'bg-white border-gray-300 text-gray-800'
                  : 'bg-gray-800 border-gray-600 text-gray-100'
              }`}
              style={{ minHeight: '48px', minWidth: '64px' }}
            >
              {t(opt.key)}
            </button>
          )
        })}
      </div>
    </div>
  )

  if (clipsQuery.isLoading) {
    return (
      <div className={`h-full flex items-center justify-center ${bgBase}`}>
        {t('expert_labeler.loading')}
      </div>
    )
  }

  if (clips.length === 0) {
    return (
      <div className={`h-full flex flex-col items-center justify-center gap-3 ${bgBase}`}>
        <div>{t('expert_labeler.no_clips')}</div>
        <button
          className={`${btnLarge} ${btnSecondary}`}
          onClick={() => navigate('/expert-labeler')}
        >
          {t('expert_labeler.back_to_list')}
        </button>
      </div>
    )
  }

  return (
    <div className={`h-full w-full overflow-y-auto ${bgBase}`}>
      <div className="max-w-6xl mx-auto p-3 md:p-5">
        {/* ヘッダ: 進捗 */}
        <header className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <button
            className={`${btnLarge} ${btnSecondary}`}
            onClick={() => navigate('/expert-labeler')}
            style={{ minHeight: '48px' }}
          >
            ← {t('expert_labeler.back_to_list')}
          </button>
          <div className="text-sm md:text-base font-semibold">
            {t('expert_labeler.clip_progress', { current: index + 1, total: clips.length })}
          </div>
          {/* エクスポート */}
          <div className="flex gap-2 ml-auto">
            <a
              href={`/api/v1/expert/export?match_id=${matchId}&fmt=json`}
              target="_blank"
              rel="noreferrer"
              className={`text-xs px-3 py-2 rounded border transition-colors ${
                isLight
                  ? 'border-gray-300 text-gray-600 hover:bg-gray-100'
                  : 'border-gray-600 text-gray-300 hover:bg-gray-700'
              }`}
            >
              JSON
            </a>
            <a
              href={`/api/v1/expert/export?match_id=${matchId}&fmt=csv`}
              target="_blank"
              rel="noreferrer"
              className={`text-xs px-3 py-2 rounded border transition-colors ${
                isLight
                  ? 'border-gray-300 text-gray-600 hover:bg-gray-100'
                  : 'border-gray-600 text-gray-300 hover:bg-gray-700'
              }`}
            >
              CSV
            </a>
          </div>
        </header>

        <div className={`h-2 rounded ${isLight ? 'bg-gray-200' : 'bg-gray-700'} overflow-hidden mb-4`}>
          <div
            className="h-full bg-blue-500"
            style={{ width: `${((index + 1) / clips.length) * 100}%` }}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* 動画領域 */}
          <div className={`rounded-lg border p-3 ${panelBg}`}>
            {currentClip && (
              <>
                <video
                  ref={videoRef}
                  key={currentClip.stroke_id}
                  src={currentClip.clip_url}
                  controls
                  autoPlay
                  playsInline
                  className="w-full rounded bg-black"
                  style={{ aspectRatio: '16 / 9', maxHeight: '60vh' }}
                />
                <div className={`mt-2 text-xs ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>
                  stroke_id: {currentClip.stroke_id}
                  {currentClip.shot_type ? ` / ${currentClip.shot_type}` : ''}
                  {currentClip.miss_type ? ` / ${currentClip.miss_type}` : ''}
                </div>
              </>
            )}
            <div className={`mt-2 text-[11px] ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>
              {t('expert_labeler.shortcut_hint')}
            </div>
          </div>

          {/* ラベル入力パネル */}
          <div className={`rounded-lg border p-4 ${panelBg}`}>
            {renderRadioGroup(
              'expert_labeler.posture_collapse',
              POSTURE_OPTIONS,
              form.posture_collapse,
              (v) => setForm((f) => ({ ...f, posture_collapse: v }))
            )}
            {renderRadioGroup(
              'expert_labeler.weight_dist',
              WEIGHT_OPTIONS,
              form.weight_distribution,
              (v) => setForm((f) => ({ ...f, weight_distribution: v }))
            )}
            {renderRadioGroup(
              'expert_labeler.shot_timing',
              TIMING_OPTIONS,
              form.shot_timing,
              (v) => setForm((f) => ({ ...f, shot_timing: v }))
            )}

            {/* 確信度 1/2/3 */}
            <div className="mb-4">
              <div className="text-sm font-semibold mb-2">
                {t('expert_labeler.confidence')}
              </div>
              <div className="flex gap-2">
                {[1, 2, 3].map((c) => {
                  const selected = form.confidence === c
                  const keyMap: Record<number, string> = {
                    1: 'expert_labeler.confidence_low',
                    2: 'expert_labeler.confidence_mid',
                    3: 'expert_labeler.confidence_high',
                  }
                  return (
                    <button
                      type="button"
                      key={c}
                      onClick={() => setForm((f) => ({ ...f, confidence: c as Confidence }))}
                      className={`${btnLarge} border ${
                        selected
                          ? 'bg-yellow-500 border-yellow-500 text-white'
                          : isLight
                          ? 'bg-white border-gray-300 text-gray-800'
                          : 'bg-gray-800 border-gray-600 text-gray-100'
                      }`}
                      style={{ minHeight: '48px', minWidth: '72px' }}
                    >
                      {c} ({t(keyMap[c])})
                    </button>
                  )
                })}
              </div>
            </div>

            {/* コメント */}
            <div className="mb-4">
              <label className="text-sm font-semibold mb-2 block">
                {t('expert_labeler.comment')}
              </label>
              <textarea
                value={form.comment}
                onChange={(e) => setForm((f) => ({ ...f, comment: e.target.value }))}
                placeholder={t('expert_labeler.comment_placeholder') as string}
                rows={2}
                className={`w-full rounded border px-3 py-2 ${
                  isLight
                    ? 'bg-white border-gray-300 text-gray-900'
                    : 'bg-gray-900 border-gray-600 text-gray-100'
                }`}
              />
            </div>

            {/* 操作ボタン */}
            <div className="grid grid-cols-2 gap-2 mb-2">
              <button
                className={`${btnLarge} ${btnSecondary}`}
                onClick={goPrev}
                disabled={index <= 0}
                style={{ minHeight: '56px' }}
              >
                ← {t('expert_labeler.prev')}
              </button>
              <button
                className={`${btnLarge} ${btnSecondary}`}
                onClick={goNext}
                disabled={index >= clips.length - 1}
                style={{ minHeight: '56px' }}
              >
                {t('expert_labeler.next')} →
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                className={`${btnLarge} ${btnSecondary}`}
                onClick={handleSkip}
                style={{ minHeight: '56px' }}
              >
                {t('expert_labeler.skip')}
              </button>
              <button
                className={`${btnLarge} ${btnPrimary}`}
                onClick={handleSave}
                style={{ minHeight: '56px' }}
              >
                {t('expert_labeler.save')}
              </button>
            </div>
          </div>
        </div>

        {/* トースト通知 */}
        {toast && (
          <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-black/80 text-white px-4 py-2 rounded shadow">
            {toast}
          </div>
        )}
      </div>
    </div>
  )
}

export function ExpertLabelerAnnotatePage() {
  return (
    <RoleGuard
      allowedRoles={['analyst', 'coach']}
      fallback={
        <div className="h-full flex items-center justify-center p-6 text-center text-sm opacity-70">
          コーチ・アナリスト専用ページです
        </div>
      }
    >
      <AnnotateContent />
    </RoleGuard>
  )
}

export default ExpertLabelerAnnotatePage
