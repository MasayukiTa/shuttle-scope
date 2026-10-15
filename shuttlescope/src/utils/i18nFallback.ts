/**
 * `t(key) || fallback` は、i18next が未登録キーに対してキー文字列そのものを
 * 返すため fallback が効かず、生キー (onboarding.consent.exit_hint 等) が画面に
 * 出る。結果が空またはキーと同一なら「未登録」とみなして fallback を返す。
 */
export function tOr(t: (key: string) => string, key: string, fallback: string): string {
  const v = t(key)
  return !v || v === key ? fallback : v
}
