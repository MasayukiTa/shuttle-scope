import electron from 'electron'
import { spawn, execSync, ChildProcess } from 'child_process'
import * as path from 'path'
import * as http from 'http'
import { existsSync, statSync, createReadStream } from 'fs'
import { Readable } from 'stream'

const { app, BrowserWindow, dialog, ipcMain, protocol, screen } = electron

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
])

let pythonProcess: ChildProcess | null = null
let mainWindow: BrowserWindow | null = null
let splashWindow: BrowserWindow | null = null
let videoWindow: BrowserWindow | null = null

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
      DATABASE_URL: `sqlite:///${path.join(appPath, 'backend', 'db', 'shuttlescope.db')}`,
      // watchfiles の自動リロードを無効化（起動時間を 10s → 1s に短縮）
      ENVIRONMENT: 'production',
    },
    windowsHide: true,
  })

  proc.stdout?.on('data', (data) => {
    console.log('[Python]', data.toString().trim())
  })
  proc.stderr?.on('data', (data) => {
    console.error('[Python ERROR]', data.toString().trim())
  })
  proc.on('exit', (code) => {
    console.log(`[Python] Process exited (code: ${code})`)
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

ipcMain.handle('open-video-window', (_event, src: string, displayId: number, startTime: number = 0, paused: boolean = false) => {
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
  const query = `src=${encodedSrc}&t=${startTime}${paused ? '&paused=1' : ''}`
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
  // Windows パスを localfile:// プロトコル URL に変換（バックスラッシュをフォワードスラッシュへ）
  const normalized = result.filePaths[0].replace(/\\/g, '/')
  return `localfile:///${normalized}`
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

  pythonProcess = startPythonBackend()

    // localfile:// プロトコルハンドラーを登録（ウィンドウ作成前に必要）
    registerLocalFileProtocol()

    // メインウィンドウをバックグラウンドでロード
    createWindow()

    if (!mainWindow) return

    // バックエンド起動確認はバックグラウンドで継続（ログ用）
    waitForBackend('http://localhost:8765/api/health', 30000)
      .then(() => console.log('[Main] Backend ready'))
      .catch((err) => console.error('[Main] Backend startup warning:', err.message))

    // ── DRM / EME 権限ハンドラー ──────────────────────────────────────────────
    mainWindow.webContents.session.setPermissionRequestHandler((_webContents, permission, callback) => {
      const allowed = new Set(['media', 'mediaKeySystem', 'geolocation'])
      callback(allowed.has(permission))
    })

    mainWindow.webContents.session.setPermissionCheckHandler((_webContents, permission) => {
      const allowed = new Set(['media', 'mediaKeySystem'])
      return allowed.has(permission)
    })

    // YouTube / 外部コンテンツを iframe で読み込めるよう CSP を設定
    mainWindow.webContents.session.webRequest.onHeadersReceived((details, callback) => {
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          'Content-Security-Policy': [
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' localfile: blob: data: http://localhost:*;" +
              " media-src 'self' localfile: blob: data: https:;" +
              " script-src 'self' 'unsafe-inline' 'unsafe-eval';" +
              " frame-src *;" +
              " img-src 'self' localfile: blob: data: https:;" +
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
      (details, callback) => {
        callback({
          requestHeaders: {
            ...details.requestHeaders,
            'User-Agent': BROWSER_UA,
          },
        })
      }
    )
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
