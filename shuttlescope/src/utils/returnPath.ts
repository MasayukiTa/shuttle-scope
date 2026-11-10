/**
 * G4 #715: セッション失効後のログインで、元のページに戻るための小さなユーティリティ。
 *
 * 方針 (option A):
 *   - セッション失効時に、その時点の in-app パスとユーザー識別子を保存する。
 *   - ログイン (通常 / MFA) の後、**同じユーザーで、同意が完了しており、
 *     パスが許可された in-app ルート**のときだけそこに戻る。
 *   - 別のユーザー / 不正なパス / 権限喪失 / 外部 URL / 同意未完了 のときは /matches。
 *
 * 保存するのは hash ルートの **in-app パス部分のみ** (例: '/dashboard/review')。
 * オリジンを含む URL や '//host' のような protocol-relative は保存も復元もしない。
 */

const RETURN_PATH_KEY = 'shuttlescope_return_path'
const RETURN_USER_KEY = 'shuttlescope_return_user'

/**
 * 戻りを許可する in-app ルートの先頭要素。App.tsx の MainLayout 内 Routes に
 * 実在するパスのみ。ここに無いもの (未知 / typo / 権限外) は /matches に戻す。
 * login / register 等の公開ページは含めない (ログイン後に戻る先として意味がない)。
 */
const ALLOWED_ROUTE_PREFIXES = [
  '/matches',
  '/getting-started',
  '/condition',
  '/dashboard',
  '/prediction',
  '/expert-labeler',
  '/llm',
  '/notifications',
  '/users',
  '/teams',
  '/settings',
  '/annotator',
  '/m/annotate',
  '/live',
  '/account',
  '/legal',
]

export interface ReturnContext {
  path: string
  userId: string
}

/**
 * パスが in-app の許可ルートかどうか。
 * - '/' で始まること (相対パス / 外部 URL を弾く)
 * - '//' で始まらないこと (protocol-relative URL を弾く)
 * - 許可プレフィックスのいずれかに完全一致または '<prefix>/' で始まること
 *   ('/users' が '/users-evil' にマッチしないよう境界を見る)
 */
export function isAllowedReturnPath(path: string | null | undefined): path is string {
  if (typeof path !== 'string') return false
  if (!path.startsWith('/')) return false
  if (path.startsWith('//')) return false
  // クエリ / hash を落としてパス本体で判定する。
  const pathOnly = path.split('?')[0].split('#')[0]
  return ALLOWED_ROUTE_PREFIXES.some(
    (pre) => pathOnly === pre || pathOnly.startsWith(pre + '/'),
  )
}

/**
 * セッション失効時に、戻り先の in-app パスとユーザー識別子を保存する。
 * 許可ルートでなければ何も保存しない (後で /matches になる)。
 * userId が空なら保存しない (誰のものか分からない戻り先は危険)。
 */
export function storeReturnContext(
  userId: string | null | undefined,
  path: string | null | undefined,
): void {
  try {
    if (!userId) return
    if (!isAllowedReturnPath(path)) return
    sessionStorage.setItem(RETURN_PATH_KEY, path)
    sessionStorage.setItem(RETURN_USER_KEY, userId)
  } catch {
    // sessionStorage が使えない環境はあきらめる (戻りは任意機能)。
  }
}

/**
 * 保存された戻り先を 1 回読んで消す (消費)。無ければ null。
 * 消費にするのは、一度戻った後に次の通常ログインで古いパスに飛ばないため。
 */
export function consumeReturnContext(): ReturnContext | null {
  try {
    const path = sessionStorage.getItem(RETURN_PATH_KEY)
    const userId = sessionStorage.getItem(RETURN_USER_KEY)
    sessionStorage.removeItem(RETURN_PATH_KEY)
    sessionStorage.removeItem(RETURN_USER_KEY)
    if (!path || !userId) return null
    return { path, userId }
  } catch {
    return null
  }
}

/**
 * ログイン後の戻り先を決める。条件を一つでも満たさなければ null
 * (呼び出し側は null のとき /matches に行く)。
 *   - ctx が保存されている
 *   - ログインしたユーザーが保存時と同一
 *   - 同意が完了している (consentComplete)
 *   - パスが許可 in-app ルート
 */
export function resolveReturnPath(
  ctx: ReturnContext | null,
  currentUserId: string | null | undefined,
  consentComplete: boolean,
): string | null {
  if (!ctx) return null
  if (!currentUserId) return null
  if (String(ctx.userId) !== String(currentUserId)) return null
  if (!consentComplete) return null
  if (!isAllowedReturnPath(ctx.path)) return null
  return ctx.path
}

export { ALLOWED_ROUTE_PREFIXES, RETURN_PATH_KEY, RETURN_USER_KEY }
