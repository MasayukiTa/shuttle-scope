import electron from 'electron'
import type { BrowserWindow as BrowserWindowInstance } from 'electron'
import { spawn, execSync, ChildProcess } from 'child_process'
import * as path from 'path'
import * as http from 'http'
import { existsSync, statSync, createReadStream, realpathSync } from 'fs'
import { Readable } from 'stream'

const { app, BrowserWindow, Menu, dialog, ipcMain, protocol, screen, shell, desktopCapturer, session } = electron

// YouTube が Electron UA を検知してブロックするのを回避するための汎用ブラウザ UA
const BROWSER_UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

// カスタムスキームはアプリ起動前に登録する必要がある（Electron の要件）
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'localfile',
    privileges: {
      secure: true,
      standard: true,
      stream: true,
      bypassCSP: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
  // app://video/{token} 経由でバックエンドの /api/videos/{token}/stream へプロキシする。
  // これによりレンダラーは生のファイルパスを一切知ることなく動画を再生できる。
  {
    scheme: 'app',
    privileges: {
      secure: true,
      standard: true,
      stream: true,
      bypassCSP: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
])

let pythonProcess: ChildProcess | null = null
let mainWindow: BrowserWindowInstance | null = null
let splashWindow: BrowserWindowInstance | null = null
let videoWindow: BrowserWindowInstance | null = null

// ─── localfile:// パスジェイル ────────────────────────────────────────────────
//
// HDD に別用途データ（ドローン映像等）が存在する環境で、
// アプリが HDD 上の許可領域（SS_LIVE_ARCHIVE_ROOT）以外にアクセスしないことを保証する。
//
// 隔離ルール:
//   1. アプリディレクトリ（appPath）内のパス → 常に許可
//   2. SS_LIVE_ARCHIVE_ROOT と同一ドライブのパス → archive root 内のみ許可、それ以外は 403
//   3. それ以外のドライブのパス → ユーザーがダイアログで明示選択したパスのみ許可
//
// この設計により:
//   - E:\shuttlescope_archive\... → 許可
//   - E:\drone_footage\...        → 403 (同一ドライブでも archive root 外)
//   - C:\Users\...\video.mp4      → ダイアログ選択済みなら許可

// ユーザーがダイアログで明示的に選択したパスのセッション内ホワイトリスト
const _userSelectedPaths = new Set<string>()

function _resolveRealPath(filePath: string): string {
  // realpathSync でシンボリックリンク/ジャンクションを実体パスに解決する。
  // 失敗時（ファイル未作成等）は path.resolve() にフォールバックするが、
  // 後段の statSync チェックでブロックされるため安全。
  try {
    return realpathSync(filePath)
  } catch {
    return path.resolve(filePath)
  }
}

function _isAllowedVideoPath(filePath: string): boolean {
  // CRITICAL: シンボリックリンク経由の HDD 漏洩を防ぐため realpathSync を使用する。
  // path.resolve() だけだと appPath/data/link_to_drone のようなリンクが appPath 内と
  // 誤判定されてしまう。
  const resolved = _resolveRealPath(filePath)
  const appPath = path.resolve(app.getAppPath())

  // 1. アプリディレクトリ内は常に許可（backend/data/, videos/, out/ 等）
  if (resolved === appPath || resolved.startsWith(appPath + path.sep)) return true

  // 2. SS_LIVE_ARCHIVE_ROOT が設定されている場合のドライブ隔離
  //    HDD と同じドライブ上のパスは archive root 配下以外すべて拒否する。
  const archiveRootRaw = (process.env.SS_LIVE_ARCHIVE_ROOT || '').trim()
  if (archiveRootRaw) {
    const archiveRoot = path.resolve(archiveRootRaw)
    const archiveDrive = path.parse(archiveRoot).root.toLowerCase()
    const fileDrive = path.parse(resolved).root.toLowerCase()

    if (fileDrive === archiveDrive) {
      const lower = resolved.toLowerCase()
      const archLower = archiveRoot.toLowerCase()
      const withinArchive = lower === archLower || lower.startsWith(archLower + path.sep)
      if (!withinArchive) {
        console.warn('[localfile] BLOCKED: path on HDD but outside archive root:', resolved)
      }
      return withinArchive
    }
  }

  // 3. ss_video_root が別ドライブに設定されている場合は許可
  const videoRootRaw = (process.env.SS_VIDEO_ROOT || path.join(appPath, 'videos')).trim()
  const videoRoot = path.resolve(videoRootRaw)
  if (resolved === videoRoot || resolved.startsWith(videoRoot + path.sep)) return true

  // 4. SS_VIDEO_EXTRA_ROOTS（; 区切り）に含まれる場合は許可
  const extraRoots = (process.env.SS_VIDEO_EXTRA_ROOTS || '').split(';').map((s) => s.trim()).filter(Boolean)
  for (const r of extraRoots) {
    const root = path.resolve(r)
    if (resolved === root || resolved.startsWith(root + path.sep)) return true
  }

  // 5. ユーザーがダイアログで明示選択したファイル
  //    （realpath 後の値で比較するため、_userSelectedPaths も realpath で格納する）
  if (_userSelectedPaths.has(resolved)) return true

  console.warn('[localfile] BLOCKED: path not in any allowed root:', resolved)
  return false
}

// 起動時のフェイルセーフログ。アーカイブ設定の有無を明示する。
function _logArchiveStatus(): void {
  const archiveRoot = (process.env.SS_LIVE_ARCHIVE_ROOT || '').trim()
  if (archiveRoot) {
    console.log('[localfile] HDD drive isolation ENABLED for archive root:', archiveRoot)
  } else {
    console.warn(
      '[localfile] SS_LIVE_ARCHIVE_ROOT is NOT set — HDD drive isolation is DISABLED. ' +
      'If you connect an external HDD with sensitive data, set SS_LIVE_ARCHIVE_ROOT in .env.development.'
    )
  }
}

// バックエンドログバッファ（最新 500 行まで保持、レンダラーに push する）
const BACKEND_LOG_MAX = 500
const backendLogBuffer: string[] = []

function pushBackendLog(line: string): void {
  backendLogBuffer.push(line)
  if (backendLogBuffer.length > BACKEND_LOG_MAX) backendLogBuffer.shift()
  mainWindow?.webContents.send('backend-log', line)
}

// ─── スプラッシュ画面 HTML（ファイルなし・data URL で即時表示） ────────────────
const SPLASH_HTML = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: 100%; height: 100%; background: #0f172a; }
  body { display: flex; align-items: center; justify-content: center; font-family: system-ui, -apple-system, sans-serif; }
  .wrap { text-align: center; }
  .logo { font-size: 2rem; font-weight: 800; color: #fff; letter-spacing: -0.02em; }
  .logo span { color: #3b82f6; }
  .sub { margin-top: 6px; font-size: 0.75rem; color: #6b7280; letter-spacing: 0.05em; }
  .dots { display: flex; gap: 8px; justify-content: center; margin-top: 24px; }
  .dot { width: 8px; height: 8px; background: #3b82f6; border-radius: 50%; animation: b 1.2s ease-in-out infinite; }
  .dot:nth-child(2) { animation-delay: 0.2s; }
  .dot:nth-child(3) { animation-delay: 0.4s; }
  @keyframes b { 0%,80%,100%{opacity:.2;transform:scale(.8)} 40%{opacity:1;transform:scale(1)} }
</style>
</head>
<body>
  <div class="wrap">
    <div class="logo">Shuttle<span>Scope</span></div>
    <div class="sub">BADMINTON ANALYSIS</div>
    <div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
  </div>
</body>
</html>`

// ─── バックエンド起動待機 ────────────────────────────────────────────────────

function waitForBackend(url: string, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = () => {
      http
        .get(url, (res) => {
          if (res.statusCode === 200) {
            resolve()
          } else {
            retry()
          }
        })
        .on('error', () => {
          retry()
        })
    }
    const retry = () => {
      if (Date.now() - start > timeoutMs) {
        reject(new Error('Backend startup timeout'))
        return
      }
      setTimeout(check, 500)
    }
    check()
  })
}

// ─── Python バックエンド起動 ─────────────────────────────────────────────────

function startPythonBackend(): ChildProcess {
  const appPath = app.getAppPath()
  const pythonExecutable =
    process.platform === 'win32'
      ? path.join(appPath, 'backend', '.venv', 'Scripts', 'python.exe')
      : path.join(appPath, 'backend', '.venv', 'bin', 'python')

  const scriptPath = path.join(appPath, 'backend', 'main.py')

  const proc = spawn(pythonExecutable, [scriptPath], {
    cwd: appPath,
    env: {
      ...process.env,
      API_PORT: '8765',
      // LAN_MODE=true で 0.0.0.0 バインド → iOS / 同一 LAN デバイスからアクセス可能
      LAN_MODE: 'true',
      // DATABASE_URL は .env.development を尊重するため Electron 側からの上書きはしない。
      // .env.development が postgresql/sqlite を切り替える SoT。
      // 旧コード（参考）:
      //   DATABASE_URL: `sqlite:///${path.join(appPath, 'backend', 'db', 'shuttlescope.db')}`,
      // watchfiles の自動リロードを無効化（起動時間を 10s → 1s に短縮）
      ENVIRONMENT: 'production',
      // Python の stdout/stderr バッファリングを無効化 → ログが即時流れる
      PYTHONUNBUFFERED: '1',
      // Windows の CP932 デフォルトエンコーディングを UTF-8 に強制する
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
    },
    windowsHide: true,
  })

  proc.stdout?.on('data', (data: Buffer) => {
    const text = data.toString('utf8').trim()
    console.log('[Python]', text)
    for (const line of text.split('\n')) {
      if (line.trim()) pushBackendLog(line.trim())
    }
  })
  proc.stderr?.on('data', (data: Buffer) => {
    const text = data.toString('utf8').trim()
    for (const line of text.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed) continue
      // Python ロギングの実際のレベルで分類する。
      // WARNING / INFO / DEBUG は console.warn、ERROR / CRITICAL / Traceback は console.error。
      const isError = /\b(ERROR|CRITICAL)\b|\bTraceback\b|\bException\b/.test(trimmed)
      if (isError) {
        console.error('[Python ERROR]', trimmed)
        pushBackendLog('[ERR] ' + trimmed)
      } else {
        console.warn('[Python]', trimmed)
        pushBackendLog(trimmed)
      }
    }
  })
  proc.on('exit', (code) => {
    const msg = `[Python] Process exited (code: ${code})`
    console.log(msg)
    pushBackendLog(msg)
  })

  return proc
}

// ─── ローカルファイルプロトコルハンドラー ────────────────────────────────────
//
// localfile:///C:/path/to/video.mp4 を Node.js の fs.createReadStream で
// 直接ストリーミングする。Range ヘッダーを処理することでシーク操作も動作する。
// net.fetch('file://') は Range を透過しないためこの実装が必要。

const VIDEO_MIME: Record<string, string> = {
  mp4: 'video/mp4',
  webm: 'video/webm',
  mkv: 'video/x-matroska',
  avi: 'video/x-msvideo',
  mov: 'video/quicktime',
  wmv: 'video/x-ms-wmv',
  flv: 'video/x-flv',
  m4v: 'video/mp4',
  ts: 'video/mp2t',
  mts: 'video/mp2t',
}

function registerLocalFileProtocol(): void {
  protocol.handle('localfile', (request) => {
    // URL から localfile:/// プレフィックスを除去してファイルパスを復元
    const rawPath = request.url.slice('localfile:///'.length)
    const filePath = decodeURIComponent(rawPath)

    // 拡張子チェック（動画ファイル以外へのアクセスを拒否 — XSS 経由の任意ファイル読み取り防止）
    const ALLOWED_VIDEO_EXTS = new Set(['mp4', 'webm', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'm4v', 'ts', 'mts'])
    const ext = path.extname(filePath).slice(1).toLowerCase()
    if (!ALLOWED_VIDEO_EXTS.has(ext)) {
      console.warn('[localfile] Blocked non-video file access:', filePath)
      return new Response(null, { status: 403, statusText: 'Forbidden: not a video file' })
    }

    // パスジェイル: HDD 上の許可領域以外へのアクセスを封鎖する
    // SS_LIVE_ARCHIVE_ROOT と同一ドライブのパスは archive root 内のみ許可。
    // ドローン映像等の別データへの誤アクセスをここで防ぐ。
    if (!_isAllowedVideoPath(filePath)) {
      console.error('[localfile] Path jail: access denied:', filePath)
      return new Response(null, { status: 403, statusText: 'Forbidden: path outside allowed video roots' })
    }

    // ファイル存在確認
    let fileStat: ReturnType<typeof statSync>
    try {
      fileStat = statSync(filePath)
    } catch {
      console.error('[localfile] File not found:', filePath)
      return new Response(null, { status: 404 })
    }

    const fileSize = fileStat.size
    const contentType = VIDEO_MIME[ext] ?? 'application/octet-stream'

    // Range ヘッダー処理（ビデオシーク操作に必須）
    const rangeHeader = request.headers.get('range')
    if (rangeHeader) {
      const m = rangeHeader.match(/bytes=(\d+)-(\d*)/)
      if (m) {
        const start = parseInt(m[1], 10)
        const end = m[2] ? Math.min(parseInt(m[2], 10), fileSize - 1) : fileSize - 1
        const chunkSize = end - start + 1

        const nodeStream = createReadStream(filePath, { start, end })
        nodeStream.on('error', (err: NodeJS.ErrnoException) => {
          // レンダラーがリクエストをキャンセルしたときに発生するベニーンエラーは無視する
          // （シーク・ソース切替・アンマウント時の正常動作）
          if (
            err.code === 'ERR_STREAM_DESTROYED' ||
            err.name === 'AbortError' ||
            err.message?.toLowerCase().includes('abort')
          ) return
          console.error('[localfile] Stream error:', err)
        })
        const webStream = Readable.toWeb(nodeStream) as ReadableStream

        return new Response(webStream, {
          status: 206,
          headers: {
            'Content-Type': contentType,
            'Content-Length': String(chunkSize),
            'Content-Range': `bytes ${start}-${end}/${fileSize}`,
            'Accept-Ranges': 'bytes',
          },
        })
      }
    }

    // Range なし: フルファイル送信
    const nodeStream = createReadStream(filePath)
    nodeStream.on('error', (err: NodeJS.ErrnoException) => {
      if (
        err.code === 'ERR_STREAM_DESTROYED' ||
        err.name === 'AbortError' ||
        err.message?.toLowerCase().includes('abort')
      ) return
      console.error('[localfile] Stream error:', err)
    })
    const webStream = Readable.toWeb(nodeStream) as ReadableStream

    return new Response(webStream, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(fileSize),
        'Accept-Ranges': 'bytes',
      },
    })
  })
}

// ─── app://video/{token} プロトコル ──────────────────────────────────────────
//
// レンダラーが <video src="app://video/{token}"> として参照すると、
// バックエンドの /api/videos/{token}/stream へプロキシして配信する。
//
// セキュリティ:
//   - レンダラーは生のファイルパスを一切知らない（video_token のみ）
//   - 認証ヘッダ X-Operator-Token は main プロセスが付与する
//   - Range ヘッダはそのまま転送して <video> シーク再生を維持

const _BACKEND_BASE = 'http://127.0.0.1:8765'

function registerAppProtocol(): void {
  protocol.handle('app', async (request) => {
    try {
      const url = new URL(request.url)
      // app://video/{token}  → host = "video", pathname = "/{token}"
      if (url.host !== 'video') {
        return new Response(null, { status: 404, statusText: 'Unknown app:// route' })
      }
      const token = url.pathname.replace(/^\//, '')
      if (!/^[a-f0-9]{32}$/.test(token)) {
        return new Response(null, { status: 400, statusText: 'Invalid token format' })
      }

      const headers: Record<string, string> = {}
      const range = request.headers.get('range')
      if (range) headers['Range'] = range
      const operatorToken = (process.env.SS_OPERATOR_TOKEN || '').trim()
      if (operatorToken) headers['X-Operator-Token'] = operatorToken

      const upstream = await fetch(`${_BACKEND_BASE}/api/videos/${token}/stream`, {
        method: request.method,
        headers,
      })
      // レスポンスヘッダから不要・不正なものを除去しつつ転送
      const passthrough = new Headers()
      for (const [k, v] of upstream.headers) {
        const kl = k.toLowerCase()
        if (kl === 'content-length' || kl === 'content-range' ||
            kl === 'content-type' || kl === 'accept-ranges') {
          passthrough.set(k, v)
        }
      }
      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: passthrough,
      })
    } catch (err) {
      console.error('[app://] proxy error:', err)
      return new Response(null, { status: 502, statusText: 'Backend unreachable' })
    }
  })
}

// ─── IPC: ディスプレイ一覧 ──────────────────────────────────────────────────

ipcMain.handle('get-displays', () => {
  const primary = screen.getPrimaryDisplay()
  return screen.getAllDisplays().map((d) => ({
    id: d.id,
    label: `${d.size.width}×${d.size.height}${d.id === primary.id ? ' (メイン)' : ''}`,
    isPrimary: d.id === primary.id,
    bounds: d.bounds,
  }))
})

// ─── IPC: 別ウィンドウで動画を表示 ──────────────────────────────────────────

ipcMain.handle('open-video-window', (_event, src: string, displayId: number, startTime: number = 0, paused: boolean = false, matchId?: string) => {
  if (videoWindow && !videoWindow.isDestroyed()) {
    videoWindow.focus()
    return
  }

  const allDisplays = screen.getAllDisplays()
  const targetDisplay = allDisplays.find((d) => d.id === displayId) ?? allDisplays[0]

  videoWindow = new BrowserWindow({
    x: targetDisplay.bounds.x,
    y: targetDisplay.bounds.y,
    width: targetDisplay.bounds.width,
    height: targetDisplay.bounds.height,
    fullscreen: true,
    frame: false,
    title: 'ShuttleScope Video',
    backgroundColor: '#000000',
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
      webviewTag: true,
    },
  })

  videoWindow.webContents.setUserAgent(BROWSER_UA)

  const encodedSrc = encodeURIComponent(src)
  const matchParam = matchId ? `&matchId=${encodeURIComponent(matchId)}` : ''
  const query = `src=${encodedSrc}&t=${startTime}${paused ? '&paused=1' : ''}${matchParam}`
  if (process.env.NODE_ENV === 'development') {
    videoWindow.loadURL(`http://localhost:5173/#/video-only?${query}`)
  } else if (app.isPackaged) {
    videoWindow.loadFile(path.join(__dirname, '../renderer/index.html'), {
      hash: `/video-only?${query}`,
    })
  } else {
    const rendererFile = path.join(app.getAppPath(), 'out', 'renderer', 'index.html')
    videoWindow.loadFile(rendererFile, { hash: `/video-only?${query}` })
  }

  videoWindow.on('closed', () => {
    videoWindow = null
    // メインウィンドウに通知
    mainWindow?.webContents.send('video-window-closed')
  })
})

ipcMain.handle('close-video-window', () => {
  if (videoWindow && !videoWindow.isDestroyed()) {
    videoWindow.close()
    videoWindow = null
  }
})

// ─── IPC: メイン↔別モニタ間ミラー（main プロセスをハブにブロードキャスト） ──
// BroadcastChannel は Electron 別ウィンドウ間で session/partition 都合により
// 届かない場合があるため、main プロセス経由に統一する。
ipcMain.on('mirror-broadcast', (event, payload: unknown) => {
  // 送信元以外の全ウィンドウへ転送
  for (const win of BrowserWindow.getAllWindows()) {
    if (win.webContents.id !== event.sender.id && !win.isDestroyed()) {
      win.webContents.send('mirror-message', payload)
    }
  }
})

// ─── IPC: 録画データの保存ダイアログ ─────────────────────────────────────────
// MediaRecorder で録画した Uint8Array を受け取り、保存先をユーザーに選ばせてファイル書き込みする。

ipcMain.handle('save-recorded-video', async (_event, data: ArrayBuffer, defaultFilename: string) => {
  const result = await dialog.showSaveDialog({
    defaultPath: defaultFilename,
    filters: [
      { name: 'Video', extensions: ['webm', 'mp4', 'mkv'] },
      { name: 'All Files', extensions: ['*'] },
    ],
  })
  if (result.canceled || !result.filePath) return null
  const { writeFileSync } = require('fs') as typeof import('fs')
  writeFileSync(result.filePath, Buffer.from(data))
  // Windows パスを localfile:// URL に変換して返す（動画登録に使用）
  const normalized = result.filePath.replace(/\\/g, '/')
  return `localfile:///${normalized}`
})

// ─── IPC: P5 WebView フレームキャプチャ（実験的）─────────────────────────────
// WebViewPlayer が表示している映像の現在フレームをキャプチャして Base64 で返す。
// TrackNet frame_hint API に渡す3フレーム（前・中・後）を取得するために使用する。

ipcMain.handle('capture-webview-frame', async () => {
  if (!mainWindow || mainWindow.isDestroyed()) return null
  try {
    const image = await mainWindow.webContents.capturePage()
    return image.toDataURL().replace(/^data:image\/png;base64,/, '')
  } catch {
    return null
  }
})

// ─── IPC: 動画ファイル選択ダイアログ ─────────────────────────────────────────

ipcMain.handle('open-video-file', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [
      {
        name: 'Video',
        extensions: ['mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'm4v', 'webm', 'ts', 'mts'],
      },
      { name: 'All Files', extensions: ['*'] },
    ],
  })
  if (result.canceled || result.filePaths.length === 0) return null
  const selectedPath = result.filePaths[0]
  // realpath 後のパスをホワイトリストに格納する（_isAllowedVideoPath が realpath で比較するため）。
  // ただし HDD 上のドローン映像をユーザーが誤選択しても、後段の _isAllowedVideoPath で
  // ドライブ隔離チェックが優先されるためブロックされる（ホワイトリストでもバイパス不可）。
  _userSelectedPaths.add(_resolveRealPath(selectedPath))
  const normalized = selectedPath.replace(/\\/g, '/')
  return `localfile:///${normalized}`
})

// ─── IPC: アプリ再起動 ────────────────────────────────────────────────────────

ipcMain.handle('relaunch-app', () => {
  app.relaunch()
  app.exit(0)
})

// バックエンドログ取得（初期ロード用）
ipcMain.handle('get-backend-log', () => backendLogBuffer.slice())

// ─── YouTube Live DRM キャプチャ ─────────────────────────────────────────────
// castLabs Electron (Widevine 内蔵) でのみ DRM 保護コンテンツを再生できる。
// 非 DRM の場合はバックエンドが HLS 方式で録画するため、ここには到達しない。
//
// castLabs Electron への切り替え方法:
//   package.json の "electron" を以下のように変更する:
//   "electron": "github:castlabs/electron-releases#<最新バージョン>"
//   最新バージョンは https://github.com/castlabs/electron-releases/releases で確認する。
//   (例: v33.3.4+wvcus — バージョン番号は本リリースに合わせて更新すること)

let _ytLiveWindow: BrowserWindowInstance | null = null
let _ytRecorderWindow: BrowserWindowInstance | null = null
let _ytDrmJobId: string | null = null
let _ytDrmToken: string | null = null

ipcMain.handle('youtube-live-drm-start', async (_event, url: string, jobId: string, token: string) => {
  _ytDrmJobId = jobId
  _ytDrmToken = token

  // 1. YouTube を表示するウィンドウを開く（ユーザーが視聴しながら録画できる）
  _ytLiveWindow = new BrowserWindow({
    width: 1280,
    height: 720,
    title: 'YouTube Live — ShuttleScope',
    webPreferences: {
      webSecurity: false,
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  _ytLiveWindow.webContents.setUserAgent(BROWSER_UA)
  _ytLiveWindow.loadURL(url)
  _ytLiveWindow.on('closed', () => { _ytLiveWindow = null })

  // YouTube が読み込まれるまで待機
  await new Promise<void>((resolve) => {
    _ytLiveWindow!.webContents.once('did-finish-load', () => resolve())
    setTimeout(resolve, 5000) // タイムアウト保険
  })

  // 2. desktopCapturer で YouTube ウィンドウのソース ID を取得
  const sources = await desktopCapturer.getSources({
    types: ['window'],
    thumbnailSize: { width: 0, height: 0 },
  })
  const ytTitle = _ytLiveWindow?.isDestroyed() ? '' : _ytLiveWindow?.getTitle() ?? ''
  const source =
    sources.find((s) => s.name === ytTitle) ??
    sources.find((s) => s.name.toLowerCase().includes('youtube')) ??
    sources.find((s) => s.name.toLowerCase().includes('shuttlescope'))

  if (!source) {
    throw new Error('YouTube ウィンドウが desktopCapturer で見つかりません')
  }

  // 3. 隠しウィンドウで MediaRecorder による webm キャプチャを開始
  _ytRecorderWindow = new BrowserWindow({
    show: false,
    width: 1,
    height: 1,
    webPreferences: {
      // 内部専用ウィンドウのみ nodeIntegration を使用する
      nodeIntegration: true,
      contextIsolation: false,
    },
  })

  // スクリーンキャプチャ権限を許可
  _ytRecorderWindow.webContents.session.setPermissionRequestHandler(
    (_wc, permission, callback) => {
      callback(permission === 'media' || permission === 'display-capture')
    },
  )

  _ytRecorderWindow.loadURL('data:text/html,<html><body></body></html>')
  await _ytRecorderWindow.webContents.executeJavaScript(`
    (async () => {
      const { ipcRenderer } = require('electron')
      const sourceId = ${JSON.stringify(source.id)}
      let stream
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            mandatory: {
              chromeMediaSource: 'desktop',
              chromeMediaSourceId: sourceId,
              maxWidth: 1920,
              maxHeight: 1080,
              maxFrameRate: 30,
            }
          }
        })
      } catch (err) {
        ipcRenderer.send('youtube-drm-error', String(err))
        return
      }
      const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
        ? 'video/webm;codecs=vp9'
        : 'video/webm;codecs=vp8'
      const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 5_000_000 })
      recorder.ondataavailable = async (e) => {
        if (e.data && e.data.size > 0) {
          const buf = await e.data.arrayBuffer()
          ipcRenderer.send('youtube-drm-chunk', buf)
        }
      }
      recorder.onerror = (e) => ipcRenderer.send('youtube-drm-error', String(e.error))
      recorder.start(2000) // 2 秒ごとにチャンクを送出
      ipcRenderer.on('youtube-drm-stop', () => {
        recorder.stop()
        stream.getTracks().forEach((t) => t.stop())
      })
    })()
  `)

  return { sourceId: source.id, sourceName: source.name }
})

// レコーダーウィンドウから webm チャンクを受信してバックエンドへ転送
// Phase B4: チャンクサイズ上限を設けて memory exhaustion 攻撃を防ぐ
const _DRM_CHUNK_MAX_BYTES = 50 * 1024 * 1024 // 50 MB / chunk (現状 2 秒チャンクで通常 1〜5 MB)
ipcMain.on('youtube-drm-chunk', (_event, chunk: ArrayBuffer) => {
  const jobId = _ytDrmJobId
  const token = _ytDrmToken
  if (!jobId) return
  if (!chunk || !(chunk instanceof ArrayBuffer)) {
    console.warn('[yt-drm] invalid chunk type')
    return
  }
  if (chunk.byteLength > _DRM_CHUNK_MAX_BYTES) {
    console.error('[yt-drm] chunk too large (rejected):', chunk.byteLength)
    return
  }
  fetch(`http://localhost:8765/api/youtube_live/${jobId}/chunk`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/octet-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: chunk,
  }).catch((err) => console.error('[yt-drm] chunk upload failed:', err))
})

// レコーダーウィンドウのエラーをコンソールに記録
ipcMain.on('youtube-drm-error', (_event, msg: string) => {
  console.error('[yt-drm] capture error:', msg)
})

ipcMain.handle('youtube-live-drm-stop', async () => {
  // レコーダーに停止シグナルを送信
  if (_ytRecorderWindow && !_ytRecorderWindow.isDestroyed()) {
    _ytRecorderWindow.webContents.send('youtube-drm-stop')
    await new Promise<void>((r) => setTimeout(r, 1500)) // 最終チャンク送出を待機
    _ytRecorderWindow.close()
    _ytRecorderWindow = null
  }
  if (_ytLiveWindow && !_ytLiveWindow.isDestroyed()) {
    _ytLiveWindow.close()
    _ytLiveWindow = null
  }
  _ytDrmJobId = null
  _ytDrmToken = null
})

// ─── スプラッシュウィンドウ作成（即時表示用） ─────────────────────────────────

function createSplashWindow(): void {
  splashWindow = new BrowserWindow({
    width: 380,
    height: 240,
    frame: false,
    transparent: false,
    resizable: false,
    center: true,
    backgroundColor: '#0f172a',
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  })
  splashWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(SPLASH_HTML)}`)
  splashWindow.once('ready-to-show', () => splashWindow?.show())
}

// ─── メインウィンドウ作成 ─────────────────────────────────────────────────────

function createWindow(): void {
  Menu.setApplicationMenu(null)
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1200,
    minHeight: 700,
    title: 'ShuttleScope',
    backgroundColor: '#0f172a',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
      // <webview> タグを有効化（DRM対応 WebView プレイヤーに必要）
      webviewTag: true,
    },
  })

  // YouTube が Electron UA を検知してブロックするのを防ぐため UA を上書き
  // （loadURL より前に設定すること）
  mainWindow.webContents.setUserAgent(BROWSER_UA)

  // ─── ナビゲーション / 新ウィンドウの制限（XSS → 外部誘導の防御） ─────────────
  // webSecurity:false の副作用で SOP が無効化されているため、
  // 悪意のあるスクリプトが別 URL に遷移しないよう明示的にブロックする。
  const ALLOWED_NAV_ORIGINS = new Set([
    'http://localhost:5173',
    'http://localhost:8765',
    'http://127.0.0.1:8765',
  ])
  mainWindow.webContents.on('will-navigate', (event: Electron.Event, url: string) => {
    try {
      const u = new URL(url)
      if (u.protocol === 'file:' || u.protocol === 'localfile:') return
      if (!ALLOWED_NAV_ORIGINS.has(`${u.protocol}//${u.host}`)) {
        event.preventDefault()
        // 外部 http(s) URL は既定ブラウザで開く
        if (u.protocol === 'http:' || u.protocol === 'https:') {
          shell.openExternal(url).catch(() => {})
        }
      }
    } catch {
      event.preventDefault()
    }
  })
  mainWindow.webContents.setWindowOpenHandler(({ url }: { url: string }) => {
    try {
      const u = new URL(url)
      if (u.protocol === 'http:' || u.protocol === 'https:') {
        shell.openExternal(url).catch(() => {})
      }
    } catch {}
    return { action: 'deny' }
  })
  // webview へ不審な webPreferences を差し込ませない
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(mainWindow.webContents as any).on('will-attach-webview', (_event: Electron.Event, webPreferences: Record<string, unknown>) => {
    delete (webPreferences as any).preload
    ;(webPreferences as any).nodeIntegration = false
    ;(webPreferences as any).contextIsolation = true
  })

  const rendererFile = path.join(app.getAppPath(), 'out', 'renderer', 'index.html')
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5173')
    mainWindow.webContents.openDevTools()
  } else if (app.isPackaged) {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
  } else if (existsSync(rendererFile)) {
    mainWindow.loadFile(rendererFile)
  } else {
    // renderer がまだビルド中のときは、生成完了まで待ってから読み込む
    const pollRenderer = () => {
      if (existsSync(rendererFile)) {
        mainWindow?.loadFile(rendererFile)
      } else {
        setTimeout(pollRenderer, 500)
      }
    }
    pollRenderer()
  }

  // React が完全に描画されたらスプラッシュを閉じてメインウィンドウを表示
  mainWindow.webContents.once('did-finish-load', () => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close()
      splashWindow = null
    }
    mainWindow?.show()
  })

  mainWindow.on('closed', () => {
    if (videoWindow && !videoWindow.isDestroyed()) {
      videoWindow.close()
      videoWindow = null
    }
    mainWindow = null
  })
}

// ─── アプリ起動フロー ─────────────────────────────────────────────────────────

async function startApp(): Promise<void> {
  try {
    // スプラッシュを最初に表示（~100ms で表示される）
    createSplashWindow()

    // Windows Firewall に port 8765 の受信許可ルールを追加（LAN デバイスから接続できるようにする）
  // ルールが存在しない場合のみ UAC 昇格して追加する
  if (process.platform === 'win32') {
    // ルール存在確認: 存在しない場合は netsh が非ゼロ終了コードで throw する
    let ruleExists = false
    try {
      execSync(
        'netsh advfirewall firewall show rule name="ShuttleScope LAN"',
        { timeout: 3000, stdio: 'ignore' }
      )
      ruleExists = true
    } catch { /* ルールなし or 確認失敗 */ }

    if (!ruleExists) {
      // UAC 昇格ダイアログを表示してルール追加（ユーザーがキャンセルした場合は無視）
      try {
        execSync(
          `powershell -Command "Start-Process netsh -ArgumentList 'advfirewall firewall add rule name=\\"ShuttleScope LAN\\" protocol=TCP dir=in localport=8765 action=allow profile=private' -Verb RunAs -Wait"`,
          { timeout: 30000, stdio: 'ignore' }
        )
      } catch { /* UAC キャンセル等は無視 */ }
    }
  }

  // SKIP_BACKEND_SPAWN=1 のときは backend 起動を Electron 外 (Scheduled Task 等) に委譲する。
  // 遠隔運用 (連休中など) で SSH からのみ backend を再起動可能にするためのフック。
  if (process.env.SKIP_BACKEND_SPAWN === '1' || process.env.SKIP_BACKEND_SPAWN === 'true') {
    console.log('[Python] SKIP_BACKEND_SPAWN set; expecting external supervisor on port 8765')
    pushBackendLog('[Python] SKIP_BACKEND_SPAWN set; not spawning python from Electron')
    pythonProcess = null
  } else {
    pythonProcess = startPythonBackend()
  }

    // localfile:// プロトコルハンドラーを登録（ウィンドウ作成前に必要）
    registerLocalFileProtocol()
    // app://video/{token} プロトコルハンドラを登録（バックエンドストリームへのプロキシ）
    registerAppProtocol()
    // パスジェイル設定の状態をログに出力（HDD 隔離が有効か警告するため）
    _logArchiveStatus()

    // メインウィンドウをバックグラウンドでロード
    createWindow()

    if (!mainWindow) return

    // バックエンド起動確認はバックグラウンドで継続（ログ用）
    waitForBackend('http://localhost:8765/api/health', 30000)
      .then(() => console.log('[Main] Backend ready'))
      .catch((err) => console.error('[Main] Backend startup warning:', err.message))

    // ── DRM / EME 権限ハンドラー ──────────────────────────────────────────────
    mainWindow.webContents.session.setPermissionRequestHandler((_webContents: unknown, permission: string, callback: (granted: boolean) => void) => {
      const allowed = new Set(['media', 'mediaKeySystem', 'geolocation'])
      callback(allowed.has(permission))
    })

    mainWindow.webContents.session.setPermissionCheckHandler((_webContents: unknown, permission: string) => {
      const allowed = new Set(['media', 'mediaKeySystem'])
      return allowed.has(permission)
    })

    // YouTube / 外部コンテンツを iframe で読み込めるよう CSP を設定
    mainWindow.webContents.session.webRequest.onHeadersReceived((details: Electron.OnHeadersReceivedListenerDetails, callback: (response: Electron.HeadersReceivedResponse) => void) => {
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          'Content-Security-Policy': [
            // app: は Phase 1 で追加した不透明トークン経由の動画ストリーム用プロトコル。
            // localfile: は既存ファイル選択用 (将来的に廃止予定)。
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' localfile: app: blob: data: http://localhost:*;" +
              " media-src 'self' localfile: app: blob: data: https:;" +
              " script-src 'self' 'unsafe-inline' 'unsafe-eval';" +
              " frame-src *;" +
              " img-src 'self' localfile: app: blob: data: https:;" +
              " connect-src 'self' http://localhost:* ws://localhost:* https:;",
          ],
        },
      })
    })

    // YouTube リクエストに対して UA を明示的にブラウザ UA に設定
    mainWindow.webContents.session.webRequest.onBeforeSendHeaders(
      {
        urls: [
          'https://*.youtube.com/*',
          'https://*.youtube-nocookie.com/*',
          'https://*.googlevideo.com/*',
          'https://*.ytimg.com/*',
        ],
      },
      (details: Electron.OnBeforeSendHeadersListenerDetails, callback: (response: Electron.BeforeSendResponse) => void) => {
        callback({
          requestHeaders: {
            ...details.requestHeaders,
            'User-Agent': BROWSER_UA,
          },
        })
      }
    )

    // ─── X-Operator-Token 自動付与 ────────────────────────────────────────────
    // 同一ホストへの SSH lateral movement / ローカルマルウェアによる
    // localhost:8765 への select grant 経由 admin/analyst 奪取を防ぐため、
    // backend が SS_OPERATOR_TOKEN を有効化している場合に Electron 経由の
    // 全 API 呼び出しに `X-Operator-Token` を自動付与する。
    // 攻撃者は backend ホストの env (`.env`) を読み取らない限り token を知り得ない。
    const operatorToken = (process.env.SS_OPERATOR_TOKEN || '').trim()
    if (operatorToken) {
      mainWindow.webContents.session.webRequest.onBeforeSendHeaders(
        { urls: ['http://localhost:8765/*', 'http://127.0.0.1:8765/*'] },
        (details: Electron.OnBeforeSendHeadersListenerDetails, callback: (response: Electron.BeforeSendResponse) => void) => {
          callback({
            requestHeaders: {
              ...details.requestHeaders,
              'X-Operator-Token': operatorToken,
            },
          })
        }
      )
    }
  } catch (err) {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close()
      splashWindow = null
    }
    const msg = err instanceof Error ? err.message : String(err)
    console.error('[Main] Startup failed:', msg)
    dialog.showErrorBox(
      'ShuttleScope Startup Error',
      `Failed to start backend.\n\n${msg}\n\nPlease verify Python and requirements.txt packages are installed.`
    )
    app.quit()
  }
}

app.whenReady().then(startApp)

app.on('window-all-closed', () => {
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow()
  }
})

app.on('before-quit', () => {
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
})
