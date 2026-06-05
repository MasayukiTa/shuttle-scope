import { Fragment, type ReactNode } from 'react'

/**
 * 軽量・XSS 構造安全な Markdown レンダラ (LLM チャット表示用)。
 *
 * - 外部ライブラリ依存ゼロ。
 * - すべての可変テキストは React のテキストノードとして描画する
 *   (dangerouslySetInnerHTML / innerHTML を一切使わない) ため、構造上 XSS が起きない。
 * - 対応記法:
 *   - ```コードフェンス``` (言語ラベル付きヘッダ)、`インラインコード`
 *   - **太字**、*斜体* / _斜体_
 *   - 見出し (# 〜 ######)、引用 (> )、表 (GitHub pipe table)
 *   - 箇条書き (-, *)、番号付き (1. / 開始番号を保持)、改行
 *   ストリーミング中の未閉じフェンスはコードブロックとして描画する (ChatGPT と同様)。
 * - リンクの自動 <a> 化は安全性 (javascript: 等) を考慮し v1 では行わず素のテキストにする。
 * - すべての解析は try/catch で防御し、未閉じ・壊れた・部分的な Markdown でも
 *   ベストエフォートで描画して決して throw しない。
 */

/**
 * インライン記法 (`code` / **bold** / *italic* / _italic_) を React ノードへ。
 * 優先順位: code > bold(**) > italic(* / _)。
 * 行頭の箇条書きマーカー (`* item`) は呼び出し前に除去済みなので、
 * ここで `*x*` を斜体として扱っても箇条書きを壊さない。
 */
function renderInline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = []
  // 優先順位順のトークン:
  //  - `code`
  //  - **bold**
  //  - *italic* / _italic_  (空でない・両端が空白でない最小一致)
  // bold を italic より前に並べることで `**x**` が `*` 斜体に誤マッチしないようにする。
  const re =
    /(`[^`]+`|\*\*[\s\S]+?\*\*|\*(?!\s)[^*\n]+?(?<!\s)\*|_(?!\s)[^_\n]+?(?<!\s)_)/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('`')) {
      nodes.push(
        <code key={`${keyBase}-c${i}`} className="rounded bg-slate-200 dark:bg-slate-700 px-1 py-0.5 text-[0.85em] font-mono">
          {tok.slice(1, -1)}
        </code>,
      )
    } else if (tok.startsWith('**')) {
      nodes.push(<strong key={`${keyBase}-b${i}`}>{renderInline(tok.slice(2, -2), `${keyBase}-b${i}`)}</strong>)
    } else {
      // *italic* または _italic_
      nodes.push(<em key={`${keyBase}-i${i}`}>{tok.slice(1, -1)}</em>)
    }
    last = m.index + tok.length
    i++
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

/** GitHub pipe table の 1 行を `|` でセル分割する (先頭/末尾の空セルは除去)。 */
function splitTableRow(line: string): string[] {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  // エスケープされていない `|` で分割。
  const cells: string[] = []
  let cur = ''
  for (let j = 0; j < s.length; j++) {
    const ch = s[j]
    if (ch === '\\' && j + 1 < s.length) {
      cur += s[j + 1]
      j++
    } else if (ch === '|') {
      cells.push(cur.trim())
      cur = ''
    } else {
      cur += ch
    }
  }
  cells.push(cur.trim())
  return cells
}

/** `|---|:--:|---|` のような区切り行か判定 (各セルが任意の `:` と `-` のみ)。 */
function isTableSeparator(line: string): boolean {
  if (!line.includes('-')) return false
  const cells = splitTableRow(line)
  if (cells.length === 0) return false
  return cells.every((c) => /^:?-+:?$/.test(c.trim()))
}

/** 区切り行のセルからカラム揃え (left/center/right) を導出。 */
function colAlign(cell: string): 'left' | 'center' | 'right' {
  const c = cell.trim()
  const l = c.startsWith(':')
  const r = c.endsWith(':')
  if (l && r) return 'center'
  if (r) return 'right'
  return 'left'
}

const ALIGN_CLASS: Record<'left' | 'center' | 'right', string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
}

/** ある行がパイプテーブルのデータ行になり得るか (`|` を含む)。 */
function looksLikeTableRow(line: string): boolean {
  return line.includes('|')
}

function renderTable(headerLine: string, sepLine: string, bodyLines: string[], key: string): ReactNode {
  const headers = splitTableRow(headerLine)
  const aligns = splitTableRow(sepLine).map(colAlign)
  const getAlign = (idx: number) => aligns[idx] ?? 'left'
  return (
    <div key={key} className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-[0.92em]">
        <thead>
          <tr className="border-b border-slate-300 dark:border-slate-600">
            {headers.map((h, c) => (
              <th
                key={c}
                className={`px-2 py-1 font-semibold ${ALIGN_CLASS[getAlign(c)]}`}
              >
                {renderInline(h, `${key}-h${c}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bodyLines.map((bl, r) => {
            const cells = splitTableRow(bl)
            return (
              <tr key={r} className="border-b border-slate-200 dark:border-slate-700/60 last:border-0">
                {headers.map((_, c) => (
                  <td key={c} className={`px-2 py-1 align-top ${ALIGN_CLASS[getAlign(c)]}`}>
                    {renderInline(cells[c] ?? '', `${key}-r${r}c${c}`)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const HEADING_CLASS: Record<number, string> = {
  1: 'text-base font-bold',
  2: 'text-base font-bold',
  3: 'text-base font-semibold',
  4: 'text-sm font-semibold',
  5: 'text-sm font-semibold',
  6: 'text-sm font-semibold text-slate-500 dark:text-slate-400',
}

function renderTextBlock(text: string, keyBase: string): ReactNode[] {
  const lines = text.split('\n')
  const out: ReactNode[] = []
  let para: string[] = []
  let list: { ordered: boolean; start: number; items: string[] } | null = null
  let quote: string[] | null = null
  let k = 0

  const flushPara = () => {
    if (para.length) {
      out.push(
        <p key={`${keyBase}-p${k++}`} className="whitespace-pre-wrap break-words">
          {renderInline(para.join('\n'), `${keyBase}-p${k}`)}
        </p>,
      )
      para = []
    }
  }
  const flushList = () => {
    if (list) {
      const cur = list
      const items = cur.items.map((it, j) => (
        <li key={j}>{renderInline(it, `${keyBase}-li${k}-${j}`)}</li>
      ))
      out.push(
        cur.ordered ? (
          <ol
            key={`${keyBase}-ol${k++}`}
            start={cur.start}
            className="list-decimal pl-5 space-y-0.5"
          >
            {items}
          </ol>
        ) : (
          <ul key={`${keyBase}-ul${k++}`} className="list-disc pl-5 space-y-0.5">
            {items}
          </ul>
        ),
      )
      list = null
    }
  }
  const flushQuote = () => {
    if (quote && quote.length) {
      out.push(
        <blockquote
          key={`${keyBase}-q${k++}`}
          className="my-1 border-l-2 border-slate-300 dark:border-slate-600 pl-3 text-slate-600 dark:text-slate-400"
        >
          {renderInline(quote.join('\n'), `${keyBase}-q${k}`)}
        </blockquote>,
      )
    }
    quote = null
  }
  const flushAll = () => {
    flushPara()
    flushList()
    flushQuote()
  }

  for (let idx = 0; idx < lines.length; idx++) {
    const ln = lines[idx]

    // --- 表 (header + separator + body) ---
    // 現在行と次行がともにパイプを含み、次行が区切り行ならテーブル開始。
    const next = idx + 1 < lines.length ? lines[idx + 1] : ''
    if (looksLikeTableRow(ln) && next && isTableSeparator(next) && looksLikeTableRow(next)) {
      flushAll()
      const headerLine = ln
      const sepLine = next
      const body: string[] = []
      let j = idx + 2
      for (; j < lines.length; j++) {
        const bl = lines[j]
        if (!looksLikeTableRow(bl) || bl.trim() === '') break
        body.push(bl)
      }
      out.push(renderTable(headerLine, sepLine, body, `${keyBase}-tbl${k++}`))
      idx = j - 1
      continue
    }

    // --- 見出し (# 〜 ######) ---
    const heading = ln.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      flushAll()
      const level = heading[1].length
      const cls = HEADING_CLASS[level] ?? HEADING_CLASS[6]
      out.push(
        <p key={`${keyBase}-h${k++}`} className={`${cls} break-words`}>
          {renderInline(heading[2], `${keyBase}-h${k}`)}
        </p>,
      )
      continue
    }

    // --- 引用 (> ) ---
    const bq = ln.match(/^\s*>\s?(.*)$/)
    if (bq) {
      flushPara()
      flushList()
      if (!quote) quote = []
      quote.push(bq[1])
      continue
    }

    // --- 箇条書き / 番号付き ---
    const ul = ln.match(/^\s*[-*]\s+(.*)$/)
    const ol = ln.match(/^\s*(\d+)\.\s+(.*)$/)
    if (ul) {
      flushPara()
      flushQuote()
      if (!list || list.ordered) {
        flushList()
        list = { ordered: false, start: 1, items: [] }
      }
      list.items.push(ul[1])
    } else if (ol) {
      flushPara()
      flushQuote()
      const num = parseInt(ol[1], 10)
      if (!list || !list.ordered) {
        flushList()
        list = { ordered: true, start: Number.isFinite(num) ? num : 1, items: [] }
      }
      list.items.push(ol[2])
    } else {
      flushList()
      flushQuote()
      para.push(ln)
    }
  }
  flushAll()
  return out
}

export function ChatMarkdown({ content }: { content: string }) {
  try {
    // ``` でトップレベル分割。奇数 index がコードブロック。
    const parts = content.split('```')
    const out: ReactNode[] = []
    parts.forEach((part, idx) => {
      if (idx % 2 === 1) {
        // コードブロック: 先頭行が言語名 (空白を含まない非空文字列) なら言語ラベルとして扱い本体から除去。
        const nl = part.indexOf('\n')
        const firstLine = nl >= 0 ? part.slice(0, nl).trim() : ''
        const hasLang = nl >= 0 && firstLine.length > 0 && !/\s/.test(firstLine)
        const lang = hasLang ? firstLine : ''
        const code = nl >= 0 && (hasLang || firstLine === '') ? part.slice(nl + 1) : part
        out.push(
          <div key={`code-${idx}`} className="my-2 overflow-hidden rounded-md bg-slate-900 dark:bg-black/50">
            {lang && (
              <div className="border-b border-white/10 px-3 py-1 font-mono text-[0.7rem] uppercase tracking-wide text-slate-400">
                {lang}
              </div>
            )}
            <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
              <code className="font-mono text-slate-100">{code.replace(/\n$/, '')}</code>
            </pre>
          </div>,
        )
      } else if (part) {
        out.push(<Fragment key={`text-${idx}`}>{renderTextBlock(part, `t${idx}`)}</Fragment>)
      }
    })
    return <div className="space-y-1.5">{out}</div>
  } catch {
    // 解析中に予期せぬ例外が起きても決してクラッシュさせない: 素のテキストとして描画。
    return <div className="space-y-1.5 whitespace-pre-wrap break-words">{content}</div>
  }
}
