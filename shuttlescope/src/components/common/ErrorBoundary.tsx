import { Component, ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  message: string
  stack: string
  copied: boolean
}

/**
 * 解析タブなどのクラッシュを局所化するエラーバウンダリー
 * エラーが発生しても他のタブや画面全体には影響しない
 * ルートレベルで使用した場合はエラー詳細を画面に表示してデバッグを支援する
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, message: '', stack: '', copied: false }
  }

  static getDerivedStateFromError(error: unknown): Omit<State, 'copied'> {
    const message = error instanceof Error ? error.message : String(error)
    const stack = error instanceof Error ? (error.stack ?? '') : ''
    return { hasError: true, message, stack }
  }

  componentDidCatch(error: unknown, info: { componentStack: string }) {
    console.error('[ErrorBoundary]', error, info.componentStack)
    this.setState((prev) => ({
      stack: prev.stack + '\n\nComponent stack:' + info.componentStack,
    }))
  }

  private copyReport = () => {
    const text = [
      `Error: ${this.state.message}`,
      '',
      this.state.stack,
    ].join('\n')
    navigator.clipboard?.writeText(text).then(() => {
      this.setState({ copied: true })
      setTimeout(() => this.setState({ copied: false }), 2000)
    })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }
      return (
        <div className="p-6 bg-gray-900 min-h-full flex flex-col gap-3">
          <p className="text-red-400 font-semibold text-base">⚠ 表示エラーが発生しました</p>
          <div className="bg-gray-800 rounded p-3 flex flex-col gap-2">
            <p className="text-xs text-gray-400 font-semibold">エラーメッセージ</p>
            <pre className="text-sm text-yellow-300 whitespace-pre-wrap break-all">
              {this.state.message || '(詳細なし)'}
            </pre>
          </div>
          {this.state.stack && (
            <div className="bg-gray-800 rounded p-3 flex flex-col gap-2">
              <p className="text-xs text-gray-400 font-semibold">スタックトレース</p>
              <pre className="text-xs text-gray-300 overflow-auto max-h-48 whitespace-pre-wrap break-all">
                {this.state.stack}
              </pre>
            </div>
          )}
          <div className="flex gap-2">
            <button
              onClick={this.copyReport}
              className="text-xs px-3 py-1.5 bg-blue-700 hover:bg-blue-600 text-white rounded transition-colors"
            >
              {this.state.copied ? 'コピーしました ✓' : 'エラー内容をコピー'}
            </button>
            <button
              onClick={() => window.location.reload()}
              className="text-xs px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
            >
              ページを再読み込み
            </button>
          </div>
          <p className="text-xs text-gray-600">
            「エラー内容をコピー」して開発者に送付してください。
          </p>
        </div>
      )
    }
    return this.props.children
  }
}
