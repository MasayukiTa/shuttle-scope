export interface PlayerSearchField {
  /** 選択済みの選手 ID。未選択は空文字または未設定。 */
  id: string | number | null | undefined
  /** 入力中の検索文字列 */
  query: string
  /** その欄の検索 API が失敗しているか */
  failed: boolean
}

/** 検索 API が失敗している欄が 1 つでもあり、その欄が未選択で文字列が入力されているか。
 *  この状態で保存すると、既存選手がいても入力文字列から暫定選手を新規作成してしまう。 */
export function isPlayerSearchBlocked(fields: readonly PlayerSearchField[]): boolean {
  return fields.some((f) => f.failed && (f.id === '' || f.id == null) && f.query.trim().length >= 1)
}
