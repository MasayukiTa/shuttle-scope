/**
 * 公開サイト (https://shuttle-scope.com) への外部リンク URL を、
 * 現在の React アプリの言語設定に合わせて組み立てるヘルパー。
 *
 * 背景:
 * - 公開サイト (backend/routers/public_site.py) は URL prefix `/en/...` のみで
 *   英語ページを返す。`ss_lang` Cookie や `?lang=` クエリは無視する。
 * - React アプリは i18next で言語管理しているので、外部リンクを書くときに
 *   明示的に `/en` を付けないと、英語 UI を使っているユーザが公開サイトに
 *   遷移したときに日本語に戻ってしまう。
 *
 * 使い方:
 *   import i18n from '@/i18n'
 *   import { publicSiteUrl } from '@/utils/publicUrl'
 *   const url = publicSiteUrl('/contact', i18n.language)
 *   // ja: https://shuttle-scope.com/contact
 *   // en: https://shuttle-scope.com/en/contact
 *
 * 注意:
 * - `path` は必ず `/` で始まる。trailing `/` は剥がれる ('/' は '/' のまま)。
 * - 既に `/en/...` で始まっている場合は二重付与しない。
 * - 未対応言語が来た場合は ja として扱う (fallback)。
 */
const ORIGIN = 'https://shuttle-scope.com'

export function publicSiteUrl(path: string, lang: string | undefined | null): string {
  // path 正規化: 先頭 '/' を強制、末尾 '/' を剥がす (ただし '/' そのものは保持)
  let p = path || '/'
  if (!p.startsWith('/')) p = '/' + p
  if (p.length > 1 && p.endsWith('/')) p = p.slice(0, -1)

  const isEn = (lang || '').toLowerCase().startsWith('en')
  if (!isEn) return ORIGIN + p

  // 既に /en で始まっていれば二重付与しない
  if (p === '/en' || p.startsWith('/en/')) return ORIGIN + p
  if (p === '/') return ORIGIN + '/en'
  return ORIGIN + '/en' + p
}
