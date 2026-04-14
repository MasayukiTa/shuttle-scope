export {}

declare global {
  interface Window {
    shuttlescope: {
      version: string
      platform: string
      openVideoFile: () => Promise<string | null>
      getDisplays?: () => Promise<Array<{
        id: number; label: string; isPrimary: boolean
        bounds: { x: number; y: number; width: number; height: number }
      }>>
      openVideoWindow?: (src: string, displayId: number, startTime?: number, paused?: boolean) => Promise<void>
      closeVideoWindow?: () => Promise<void>
      onVideoWindowClosed?: (cb: () => void) => () => void
      captureWebviewFrame?: () => Promise<string | null>
      /** 録画した Uint8Array をファイル保存ダイアログで保存し、保存先パスを返す */
      saveRecordedVideo?: (data: Uint8Array, defaultFilename: string) => Promise<string | null>
      /** アプリを再起動する（app.relaunch + app.exit） */
      restartApp?: () => Promise<void>
      /** バックエンドログ（起動からの全行）を取得する */
      getBackendLog?: () => Promise<string[]>
      /** バックエンドログのリアルタイム購読（返り値はアンサブスクライブ関数） */
      onBackendLog?: (cb: (line: string) => void) => () => void
      [key: string]: unknown
    }
  }
}

// ── Electron <webview> タグの JSX 型定義 ───────────────────────────────────
// Electron の webviewTag: true を有効にすると <webview> が使えるが、
// React の JSX 型定義には含まれないため独自に宣言する。

declare namespace JSX {
  interface IntrinsicElements {
    webview: React.DetailedHTMLProps<WebviewHTMLAttributes, HTMLElement>
  }
}

interface WebviewHTMLAttributes extends React.HTMLAttributes<HTMLElement> {
  src?: string
  /** Cookie を永続化するパーティション（例: "persist:streaming"） */
  partition?: string
  /** 使用するユーザーエージェント */
  useragent?: string
  /** Node.js 統合を無効化（セキュリティのため常に false を推奨） */
  nodeintegration?: string
  /** コンテキストアイソレーション */
  contextIsolation?: string
  /** 開発者ツールを有効化 */
  devtools?: boolean
  /** HTTP プリフライトリクエストを許可 */
  allowpopups?: string
  /** ディスプレイスケール */
  disablewebsecurity?: string
  /** プレロードスクリプト */
  preload?: string
  /** HTTP ヘッダー */
  httpreferrer?: string
  /** フラッシュの許可 */
  plugins?: string
  ref?: React.Ref<HTMLElement>
}
