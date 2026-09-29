/**
 * psl の型宣言。
 *
 * psl は types/index.d.ts を同梱しているが、package.json の exports に
 * "types" 条件が無い。moduleResolution: "bundler" は exports を優先するため
 * dist/psl.mjs に解決され、型が見つからず暗黙 any (TS7016) になる。
 *
 * この 1 件が tsc を止めていて、他の型エラーが 1 件も表示されていなかった。
 *
 * ambient 宣言なのでこのファイルに import / export を書かないこと。
 * 書いた瞬間モジュール扱いになり、`declare module` が「既存モジュールの
 * 拡張」に変わって宣言として効かなくなる (electron.d.ts に置いて失敗済み)。
 */
declare module 'psl' {
  /** 登録可能ドメイン (eTLD+1) を返す。判定できなければ null。 */
  export function get(domain: string): string | null
  /** 公開サフィックス表に照らして妥当なドメインかを返す。 */
  export function isValid(domain: string): boolean
  const psl: { get: typeof get; isValid: typeof isValid }
  export default psl
}
