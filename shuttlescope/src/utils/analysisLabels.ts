/**
 * 分析カードに出る内部コード (ショット種別・状態キー) を、利用者向けの日本語ラベルにする。
 *
 * API は `push_rush` や `early|second|medium|receiver` のような内部コードを返す。
 * それをそのまま描画すると開発メモが画面に出てしまうため、表示の直前にここを通す。
 * 辞書は i18n (shot_types / shot_categories / analysis_labels.state) に置き、
 * 引けなかったときだけ元のコードを返す (黙って空にしない)。
 */

type TFn = (key: string) => string

/** i18next は未登録キーに対してキー文字列そのものを返すので、それを「未登録」と判定する */
function lookup(t: TFn, key: string): string | null {
  const v = t(key)
  return !v || v === key ? null : v
}

/**
 * ショット種別コード → 日本語。
 * shot_types (18 種) → shot_categories (serve / net などのバケット名) の順に引く。
 */
export function shotLabel(t: TFn, code: string | null | undefined): string {
  if (!code) return '—'
  return (
    lookup(t, `shot_types.${code}`) ??
    lookup(t, `shot_categories.${code}`) ??
    code
  )
}

/**
 * 状態キー ("early|second|medium|receiver" のような '|' 区切り) → "序盤 / 第2セット / 中くらい / レシーバー"。
 * 知らないトークンはそのまま残す。
 */
export function stateKeyLabel(t: TFn, key: string | null | undefined): string {
  if (!key) return '—'
  return key
    .split('|')
    .map((token) => lookup(t, `analysis_labels.state.${token}`) ?? token)
    .join(' / ')
}
