#!/usr/bin/env node
/**
 * B7 i18n codemod — 残存TSXファイルのJSXテキスト/属性中の日本語を抽出し、
 * ja.json の "auto.<basename>.<idx>" に登録、t() 呼出しに置換する。
 *
 * 扱うパターン（保守的・低リスクのみ）:
 *   1. JSX text:   `>日本語<`                → `>{t('key')}<`
 *   2. 属性:       `title="日本語"` 等        → `title={t('key')}`
 *      対象: title | placeholder | aria-label | alt
 *   3. object literal の `label: '日本語'`   → `label: t('key')`
 *
 * 扱わないもの:
 *   - テンプレートリテラル中の JP
 *   - 関数本体内のエラーメッセージ文字列
 *   - コメント中の JP
 *   - クラスコンポーネント（useTranslation追加せず、手動調整要）
 *
 * 追加処理:
 *   - 関数コンポーネント検出（`export function X(...)` or `function X(`）の直後に
 *     `const { t } = useTranslation()` を挿入（まだ無ければ）
 *   - `import { useTranslation } from 'react-i18next'` を追加（まだ無ければ）
 */
import fs from 'node:fs'
import path from 'node:path'

const ROOT = process.cwd()
const FILES_LIST = process.argv[2] || '/tmp/b7_files.txt'
const I18N_PATH = path.join(ROOT, 'src/i18n/ja.json')

const files = fs.readFileSync(FILES_LIST, 'utf8').split('\n').filter(Boolean)

const ja = JSON.parse(fs.readFileSync(I18N_PATH, 'utf8'))
if (!ja.auto) ja.auto = {}

const JP_RE = /[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF々〆〇ー]/

function hasJP(s) { return JP_RE.test(s) }

function sanitizeKeyFragment(s) {
  return s.replace(/[^a-zA-Z0-9]/g, '_').slice(0, 40)
}

function addKey(bucket, text, basename) {
  // 既に登録済みならそのキーを返す
  for (const [k, v] of Object.entries(bucket)) {
    if (v === text) return k
  }
  let idx = 1
  while (bucket[`k${idx}`]) idx++
  const key = `k${idx}`
  bucket[key] = text
  return key
}

let totalReplacements = 0
const perFileStats = []

for (const rel of files) {
  const abs = path.join(ROOT, rel)
  let src = fs.readFileSync(abs, 'utf8')
  const basename = path.basename(rel, '.tsx')
  const bucketName = sanitizeKeyFragment(basename)
  if (!ja.auto[bucketName]) ja.auto[bucketName] = {}
  const bucket = ja.auto[bucketName]

  let fileReps = 0
  const isClassComp = /class\s+\w+\s+extends\s+(React\.)?Component/.test(src)

  // Pattern 1: JSX text between `>` and `<`, only if content is entirely JP + ascii punctuation/space
  // We match `>TEXT<` where TEXT contains at least 1 JP char and no `{`, `}`, `<`, `>`
  src = src.replace(/>([^<>{}\n]*?[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF々〆〇ー][^<>{}\n]*?)</g, (m, text) => {
    const trimmed = text.trim()
    if (!trimmed || !hasJP(trimmed)) return m
    // Skip if already wrapped in {}
    // Preserve leading/trailing whitespace
    const leading = text.match(/^\s*/)[0]
    const trailing = text.match(/\s*$/)[0]
    const key = addKey(bucket, trimmed, basename)
    fileReps++
    return `>${leading}{t('auto.${bucketName}.${key}')}${trailing}<`
  })

  // Pattern 2: attributes with JP strings
  const attrNames = ['title', 'placeholder', 'aria-label', 'alt']
  for (const attr of attrNames) {
    const re = new RegExp(`(${attr})=(["'])([^"'\\n]*?[\\u3040-\\u309F\\u30A0-\\u30FF\\u4E00-\\u9FFF々〆〇ー][^"'\\n]*?)\\2`, 'g')
    src = src.replace(re, (m, a, q, val) => {
      if (!hasJP(val)) return m
      const key = addKey(bucket, val, basename)
      fileReps++
      return `${a}={t('auto.${bucketName}.${key}')}`
    })
  }

  // Pattern 3: object literal `label: '日本語'` or `"日本語"` (single-line values)
  src = src.replace(/(\blabel:\s*)(["'])([^"'\n]*?[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF々〆〇ー][^"'\n]*?)\2/g, (m, pre, q, val) => {
    const key = addKey(bucket, val, basename)
    fileReps++
    return `${pre}t('auto.${bucketName}.${key}')`
  })

  if (fileReps === 0) { perFileStats.push({ rel, reps: 0 }); continue }

  // Ensure useTranslation import
  if (!/from ['"]react-i18next['"]/.test(src)) {
    // Add after first import line
    const lines = src.split('\n')
    let insertAt = 0
    for (let i = 0; i < lines.length; i++) {
      if (/^import\s/.test(lines[i])) insertAt = i + 1
      else if (insertAt > 0) break
    }
    lines.splice(insertAt, 0, `import { useTranslation } from 'react-i18next'`)
    src = lines.join('\n')
  } else if (!/useTranslation/.test(src)) {
    src = src.replace(/from ['"]react-i18next['"]/, (m) => {
      return m
    })
    // add useTranslation to existing import
    src = src.replace(/import\s*\{([^}]*)\}\s*from\s*(['"])react-i18next\2/, (m, inner, q) => {
      if (/\buseTranslation\b/.test(inner)) return m
      return `import { useTranslation,${inner}} from ${q}react-i18next${q}`
    })
  }

  // Ensure `const { t } = useTranslation()` is inside each exported function component
  // Heuristic: find `export function NAME(...)` or `export default function NAME(...)` bodies
  // and inject right after the opening `{`. Only inject if function body doesn't already have it.
  if (!isClassComp) {
    // Find function component signatures
    src = src.replace(
      /((?:export\s+(?:default\s+)?)?function\s+([A-Z]\w*)\s*\([^)]*\)(?:\s*:\s*[^\{]+)?\s*\{)/g,
      (m, sig) => {
        // Insert after the opening brace; only if next 200 chars don't contain useTranslation
        return sig  // handled in next step
      }
    )
    // More robust: for each function-component opening `{`, check if body already has useTranslation
    // Implement by iterating matches with indices.
    const fnRe = /((?:export\s+(?:default\s+)?)?function\s+([A-Z]\w*)\s*\([^)]*\)(?:\s*:\s*[^\{]+)?\s*\{)/g
    const insertions = []
    let m
    while ((m = fnRe.exec(src)) !== null) {
      const bodyStart = m.index + m[0].length
      // Look ahead up to 500 chars for useTranslation
      const slice = src.slice(bodyStart, bodyStart + 500)
      if (/useTranslation\s*\(/.test(slice)) continue
      // Also check if function body uses t(
      const fnBodyEnd = Math.min(bodyStart + 5000, src.length)
      const bigSlice = src.slice(bodyStart, fnBodyEnd)
      if (!/\bt\(/.test(bigSlice)) continue
      insertions.push(bodyStart)
    }
    // Apply insertions in reverse
    insertions.reverse()
    for (const pos of insertions) {
      src = src.slice(0, pos) + `\n  const { t } = useTranslation()\n` + src.slice(pos)
    }
  }

  fs.writeFileSync(abs, src, 'utf8')
  totalReplacements += fileReps
  perFileStats.push({ rel, reps: fileReps, isClass: isClassComp })
}

fs.writeFileSync(I18N_PATH, JSON.stringify(ja, null, 2) + '\n', 'utf8')

console.log(`Total replacements: ${totalReplacements}`)
console.log(`Files changed: ${perFileStats.filter(s => s.reps > 0).length}`)
for (const s of perFileStats.filter(s => s.reps > 0).sort((a,b) => b.reps - a.reps).slice(0, 20)) {
  console.log(`  ${s.reps.toString().padStart(4)} ${s.isClass ? '[CLASS]' : '       '} ${s.rel}`)
}
