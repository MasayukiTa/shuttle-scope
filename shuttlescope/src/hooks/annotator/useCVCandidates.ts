/**
 * useCVCandidates — CV補助アノテーション候補の取得・ビルド・適用を管理するフック
 *
 * 提供する機能:
 *   - 生成済み候補の取得（GET /api/cv-candidates/{matchId}）
 *   - 候補ビルドのトリガー（POST /api/cv-candidates/build/{matchId}）
 *   - 高確信度候補のストロークへの適用（POST /api/cv-candidates/apply/{matchId}）
 *   - レビューキュー取得（GET /api/cv-candidates/review-queue/{matchId}）
 *   - ラリーIDによる候補ルックアップ
 */
import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiPut } from '@/api/client'
import type { CVCandidatesData, RallyCVCandidate, ReviewQueueItem } from '@/types/cv'

interface Options {
  matchId: string | undefined
}

export interface CVCandidatesResult {
  // データ
  candidatesData: CVCandidatesData | null
  candidatesLoading: boolean
  builtAt: string | null

  // ビルド
  buildLoading: boolean
  buildError: string | null
  buildCandidates: () => Promise<void>

  // 適用
  applyLoading: boolean
  applyError: string | null
  applyResult: {
    updated_strokes: number
    land_zone_count: number
    hit_zone_count: number
    hitter_count: number
    preserved_count?: number
    applied_by_mode: string
    applied_fields: string[]
  } | null
  applyCandidates: (
    mode?: 'auto_filled' | 'suggested' | 'all',
    fields?: ('land_zone' | 'hit_zone' | 'hitter')[]
  ) => Promise<void>

  // レビューキュー
  reviewQueue: ReviewQueueItem[]
  reviewQueueLoading: boolean
  reviewError: string | null
  markReviewCompleted: (rallyId: number) => Promise<void>

  // ラリー候補ルックアップ
  getCandidateForRally: (rallyId: number) => RallyCVCandidate | null

  // 状態リセット
  clearBuildError: () => void
  clearApplyError: () => void
  clearReviewError: () => void
}

export function useCVCandidates({ matchId }: Options): CVCandidatesResult {
  const queryClient = useQueryClient()

  const [buildError, setBuildError] = useState<string | null>(null)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [applyResult, setApplyResult] = useState<{
    updated_strokes: number
    land_zone_count: number
    hit_zone_count: number
    hitter_count: number
    preserved_count?: number
    applied_by_mode: string
    applied_fields: string[]
  } | null>(null)

  // ── 候補データ取得 ─────────────────────────────────────────────────────────
  const {
    data: candidatesResponse,
    isLoading: candidatesLoading,
  } = useQuery({
    queryKey: ['cv-candidates', matchId],
    queryFn: () =>
      apiGet<{ success: boolean; data: CVCandidatesData | null }>(
        `/cv-candidates/${matchId}`
      ),
    enabled: !!matchId,
    refetchInterval: false,
    staleTime: 60_000,
  })

  const candidatesData = candidatesResponse?.data ?? null
  const builtAt = candidatesData?.built_at ?? null

  // ── レビューキュー取得 ────────────────────────────────────────────────────
  const { data: reviewQueueResponse, isLoading: reviewQueueLoading } = useQuery({
    queryKey: ['cv-review-queue', matchId],
    queryFn: () =>
      apiGet<{ success: boolean; data: ReviewQueueItem[] }>(
        `/cv-candidates/review-queue/${matchId}`
      ),
    enabled: !!matchId,
    // build/apply/review の各 mutation が invalidate するため自動更新は補助的。
    // タブ非表示中はポーリングしない (無駄な背景トラフィックを抑制)。
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })
  const reviewQueue = reviewQueueResponse?.data ?? []

  // ── ビルドミューテーション ────────────────────────────────────────────────
  const buildMutation = useMutation({
    mutationFn: () =>
      apiPost<{ success: boolean; data: { match_id: number; rally_count: number; built_at: string } }>(
        `/cv-candidates/build/${matchId}`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cv-candidates', matchId] })
      queryClient.invalidateQueries({ queryKey: ['cv-review-queue', matchId] })
      setBuildError(null)
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '候補生成に失敗しました'
      setBuildError(msg)
    },
  })

  const buildCandidates = useCallback(async () => {
    if (!matchId) return
    setBuildError(null)
    await buildMutation.mutateAsync()
  }, [matchId, buildMutation])

  // ── 適用ミューテーション ──────────────────────────────────────────────────
  const applyMutation = useMutation({
    mutationFn: ({ mode, fields }: { mode: 'auto_filled' | 'suggested' | 'all'; fields: string[] }) =>
      apiPost<{
        success: boolean
        data: {
          updated_strokes: number
          land_zone_count: number
          hit_zone_count: number
          hitter_count: number
          preserved_count?: number
          applied_by_mode: string
          applied_fields: string[]
        }
      }>(
        `/cv-candidates/apply/${matchId}`,
        { mode, fields }
      ),
    onSuccess: (res) => {
      if (res.success) {
        setApplyResult(res.data)
        setApplyError(null)
        queryClient.invalidateQueries({ queryKey: ['strokes'] })
      } else {
        // success=false は適用が確定していないので、前回の成功件数を残さない。
        setApplyResult(null)
        setApplyError('候補の適用に失敗しました')
      }
    },
    onError: (err: unknown) => {
      setApplyResult(null)
      setApplyError(err instanceof Error ? err.message : '候補の適用に失敗しました')
    },
  })

  const applyCandidates = useCallback(async (
    mode: 'auto_filled' | 'suggested' | 'all' = 'auto_filled',
    fields: ('land_zone' | 'hit_zone' | 'hitter')[] = ['land_zone', 'hitter']
  ) => {
    if (!matchId) return
    // 新しい適用を開始する時点で前回の success / error 表示を消す。
    // これをしないと、2 回目が失敗しても 1 回目の「○件適用」が残り続ける。
    setApplyResult(null)
    setApplyError(null)
    await applyMutation.mutateAsync({ mode, fields })
  }, [matchId, applyMutation])

  // ── レビュー完了マーク ────────────────────────────────────────────────────
  const reviewMutation = useMutation({
    mutationFn: (rallyId: number) =>
      apiPut(`/cv-candidates/review/${rallyId}`, { review_status: 'completed' }),
    onSuccess: () => {
      setReviewError(null)
      queryClient.invalidateQueries({ queryKey: ['cv-review-queue', matchId] })
    },
    onError: (err: unknown) => {
      setReviewError(err instanceof Error ? err.message : 'レビュー完了を保存できませんでした')
    },
  })

  const markReviewCompleted = useCallback(async (rallyId: number) => {
    setReviewError(null)
    await reviewMutation.mutateAsync(rallyId)
  }, [reviewMutation])

  // ── ラリー候補ルックアップ ────────────────────────────────────────────────
  const getCandidateForRally = useCallback(
    (rallyId: number): RallyCVCandidate | null => {
      return candidatesData?.rallies?.[String(rallyId)] ?? null
    },
    [candidatesData]
  )

  return {
    candidatesData,
    candidatesLoading,
    builtAt,
    buildLoading: buildMutation.isPending,
    buildError,
    buildCandidates,
    applyLoading: applyMutation.isPending,
    applyError,
    applyResult,
    applyCandidates,
    reviewQueue,
    reviewQueueLoading,
    reviewError,
    markReviewCompleted,
    getCandidateForRally,
    clearBuildError: () => setBuildError(null),
    clearApplyError: () => setApplyError(null),
    clearReviewError: () => setReviewError(null),
  }
}
