/**
 * 「研究」ダッシュボード (/dashboard/research) を表示してよいロールか。
 *
 * backend の研究 API (backend/routers/analysis_research.py) は router 全体に
 * require_admin_or_analyst を掛けており、admin / analyst 以外 (coach / demo / llm / player)
 * は 403 になる。画面側の表示条件を backend と一致させ、「タブは出るのに
 * API が全て 403」という状態を作らない。backend の許可ロールを変えるときは、
 * ここも同時に変えること。
 */
export function canViewResearch(role: string | null | undefined): boolean {
  return role === 'admin' || role === 'analyst'
}
