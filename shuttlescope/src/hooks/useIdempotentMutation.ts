import { useMutation, type UseMutationOptions } from '@tanstack/react-query'
import { newIdempotencyKey } from '@/api/client'

/**
 * X-Idempotency-Key を自動付与する useMutation ラッパー。
 *
 * 通常の useMutation は二度押しで二重実行されるリスクがあるが、
 * このフックは初回 mutate 時に生成した idempotency_key を保持し、
 * 同じ操作インスタンスでの再 mutate に同じキーを使う。
 *
 * 使い方:
 * ```tsx
 * const reissue = useIdempotentMutation({
 *   mutationFn: (matchId: number, idemKey: string) =>
 *     apiPost(`/matches/${matchId}/reissue_video_token`, {},
 *             { 'X-Idempotency-Key': idemKey }),
 * })
 * reissue.mutate(123)  // 内部で idemKey 生成・注入
 * ```
 *
 * 注: バックエンドの idempotency 保持期間は 24 時間。それを超えると
 * 同じキーでも新規実行扱いになる。
 */
export function useIdempotentMutation<TData, TVariables>(
  options: Omit<UseMutationOptions<TData, Error, TVariables>, 'mutationFn'> & {
    mutationFn: (vars: TVariables, idempotencyKey: string) => Promise<TData>
  },
) {
  const { mutationFn, ...rest } = options
  return useMutation<TData, Error, TVariables>({
    ...rest,
    mutationFn: async (vars: TVariables) => {
      const idemKey = newIdempotencyKey()
      return mutationFn(vars, idemKey)
    },
  })
}
