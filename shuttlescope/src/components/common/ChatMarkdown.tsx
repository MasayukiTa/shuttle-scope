import { Fragment, type ReactNode } from 'react'

/**
 * 軽量・XSS 構造安全な Markdown レンダラ (LLM チャット表示用)。
 *
 * - 外部ライブラリ依存ゼロ。
 * - すべての可変テキストは React のテキストノードとして描画する
 *   (dangerouslySetInnerHTML / innerHTML を一切使わない) ため、構造上 XSS が起きない。
 * - 対応記法: ```コードフェンス```、`インラインコード`、**太字**、箇条書き (-, *, 1.)、改行。
 *   ストリーミング中の未閉じフェンスはコードブロックとして描画する (ChatGPT と同様)。
 * - リンクの自動 <a> 化は安全性 (javascript: 等) を考慮し v1 では行わず素のテキストにする。
 */

function renderInline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = []
  // `code` または **bold** をトークンとして抽出。
  const re = /(`[^`]+`|\*\*[^*]+\*\*)/g
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
    } else {
      nodes.push(<strong key={`${keyBase}-b${i}`}>{tok.slice(2, -2)}</strong>)
    }
    last = m.index + tok.length
    i++
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

function renderTextBlock(text: string, keyBase: string): ReactNode[] {
  const lines = text.split('\n')
  const out: ReactNode[] = []
  let para: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null
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
      const items = list.items.map((it, j) => <li key={j}>{renderInline(it, `${keyBase}-li${k}-${j}`)}</li>)
      out.push(
        list.ordered
          ? <ol key={`${keyBase}-ol${k++}`} className="list-decimal pl-5 space-y-0.5">{items}</ol>
          : <ul key={`${keyBase}-ul${k++}`} className="list-disc pl-5 space-y-0.5">{items}</ul>,
      )
      list = null
    }
  }

  for (const ln of lines) {
    const ul = ln.match(/^\s*[-*]\s+(.*)$/)
    const ol = ln.match(/^\s*\d+\.\s+(.*)$/)
    if (ul) {
      flushPara()
      if (!list || list.ordered) { flushList(); list = { ordered: false, items: [] } }
      list.items.push(ul[1])
    } else if (ol) {
      flushPara()
      if (!list || !list.ordered) { flushList(); list = { ordered: true, items: [] } }
      list.items.push(ol[1])
    } else {
      flushList()
      para.push(ln)
    }
  }
  flushPara()
  flushList()
  return out
}

export function ChatMarkdown({ content }: { content: string }) {
  // ``` でトップレベル分割。奇数 index がコードブロック。
  const parts = content.split('```')
  const out: ReactNode[] = []
  parts.forEach((part, idx) => {
    if (idx % 2 === 1) {
      // コードブロック: 先頭行が言語名 (空白を含まない) なら除去。
      const nl = part.indexOf('\n')
      const firstLine = nl >= 0 ? part.slice(0, nl) : ''
      const code = nl >= 0 && !/\s/.test(firstLine) ? part.slice(nl + 1) : part
      out.push(
        <pre key={`code-${idx}`} className="my-2 overflow-x-auto rounded-md bg-slate-900 dark:bg-black/50 p-3 text-xs leading-relaxed">
          <code className="font-mono text-slate-100">{code.replace(/\n$/, '')}</code>
        </pre>,
      )
    } else if (part) {
      out.push(<Fragment key={`text-${idx}`}>{renderTextBlock(part, `t${idx}`)}</Fragment>)
    }
  })
  return <div className="space-y-1.5">{out}</div>
}
