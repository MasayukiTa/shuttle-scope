/// <reference types="vite/client" />

export {}

declare global {
  /**
   * Vite が注入する環境変数。vite/client の ImportMetaEnv を拡張する。
   * ここに書いてあるキーだけが型として通るので、綴り違いはコンパイルで落ちる。
   * 値は必ず文字列 (未設定なら undefined)。真偽値は文字列比較で判定すること。
   */
  interface ImportMetaEnv {
    readonly VITE_SS_API_BASE_URL?: string
    readonly VITE_SS_APP_URL?: string
    readonly VITE_SS_BILLING_UI_ENABLED?: string
    readonly VITE_SS_HEALTH_CHECK_TIMEOUT_MS?: string
    readonly VITE_SS_PREFER_LAN_ENDPOINT?: string
    readonly VITE_SS_SENDER_AUTO_RECORD?: string
    readonly VITE_SS_SENDER_CHUNK_SECONDS?: string
    readonly VITE_SS_TURNSTILE_SITE_KEY?: string
  }

  interface Window {
    /**
     * Electron の preload が注入する API。
     * **ブラウザ (トンネル経由の iPad / スマホ / ViewerPage) では undefined。**
     * 必須プロパティとして宣言すると、未ガードの呼び出しが型で通ってしまい
     * ブラウザ側だけ実行時に落ちる。optional のままにしておくこと。
     */
    shuttlescope?: {
      version: string
      platform: string
      openVideoFile: () => Promise<string | null>
      getDisplays?: () => Promise<Array<{
        id: number; label: string; isPrimary: boolean
        bounds: { x: number; y: number; width: number; height: number }
      }>>
      openVideoWindow?: (src: string, displayId: number, startTime?: number, paused?: boolean, matchId?: string) => Promise<void>
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
      /** 別モニタミラー: 他ウィンドウへ任意ペイロードをブロードキャスト */
      sendMirror?: (payload: unknown) => void
      /** 別モニタミラー: 他ウィンドウからのペイロードを購読（返り値はアンサブスクライブ） */
      onMirror?: (cb: (payload: unknown) => void) => () => void
      /** YouTube Live DRM 録画開始 (electron/preload.ts:68) */
      youtubeLiveDrmStart?: (url: string, jobId: string, token: string) => Promise<{ sourceId: string; sourceName: string }>
      /** YouTube Live DRM 録画停止 (electron/preload.ts:70) */
      youtubeLiveDrmStop?: () => Promise<void>
      // 下のインデックスシグネチャがあるので、宣言し忘れたメソッドは
      // unknown になって呼べない。preload に足したらここにも足すこと。
      [key: string]: unknown
    }
  }
}

// ── Electron <webview> タグの JSX 型定義 ───────────────────────────────────
// Electron の webviewTag: true を有効にすると <webview> が使えるが、
// React の JSX 型定義には含まれないため独自に宣言する。

declare namespace _JSX {
  interface IntrinsicElements {
    webview: React.DetailedHTMLProps<WebviewHTMLAttributes, HTMLElement>
  }
}

interface WebviewHTMLAttributes extends React.HTMLAttributes<HTMLElement> {
  src?: string
  /** Cookie を永続化するパーティション（例: "persist:streaming"） */
  partition?: string
  /** 使用するユーザエージェント */
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
