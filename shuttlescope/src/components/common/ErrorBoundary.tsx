import { Component, ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  message: string
}

/**
 * 解析タブなどのクラッシュを局所化するエラーバウンダリー
 * エラーが発生しても他のタブや画面全体には影響しない
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(error: unknown): State {
    const message = error instanceof Error ? error.message : String(error)
    return { hasError: true, message }
  }

  componentDidCatch(error: unknown, info: { componentStack: string }) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="py-8 text-center text-sm text-gray-500">
            <p className="text-red-400 mb-1">表示エラーが発生しました</p>
            <p className="text-xs text-gray-600 font-mono">{this.state.message}</p>
          </div>
        )
      )
    }
    return this.props.children
  }
}
