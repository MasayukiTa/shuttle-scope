import { app, BrowserWindow, dialog, ipcMain, protocol } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import * as path from 'path'
import * as http from 'http'
import { existsSync, statSync, createReadStream } from 'fs'
import { Readable } from 'stream'

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

// ─── バックエンド起動待機 ────────────────────────────────────────────────────

function waitForBackend(url: string, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = () => {
      http.get(url, (res) => {
        if (res.statusCode === 200) {
          resolve()
        } else {
          retry()
        }
      }).on('error', () => {
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
  const pythonExecutable = process.platform === 'win32'
    ? path.join(appPath, 'backend', '.venv', 'Scripts', 'python.exe')
    : path.join(appPath, 'backend', '.venv', 'bin', 'python')

  const scriptPath = path.join(appPath, 'backend', 'main.py')

  const proc = spawn(pythonExecutable, [scriptPath], {
    cwd: appPath,
    env: {
      ...process.env,
      API_PORT: '8765',
      DATABASE_URL: `sqlite:///${path.join(appPath, 'shuttlescope.db')}`,
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

    // ファイル存在確認
    let fileStat: ReturnType<typeof statSync>
    try {
      fileStat = statSync(filePath)
    } catch {
      console.error('[localfile] File not found:', filePath)
      return new Response(null, { status: 404 })
    }

    const fileSize = fileStat.size
    const ext = path.extname(filePath).slice(1).toLowerCase()
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
        nodeStream.on('error', (err) => console.error('[localfile] Stream error:', err))
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
    nodeStream.on('error', (err) => console.error('[localfile] Stream error:', err))
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

// ─── IPC: 動画ファイル選択ダイアログ ─────────────────────────────────────────

ipcMain.handle('open-video-file', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [
      { name: 'Video', extensions: ['mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'm4v', 'webm', 'ts', 'mts'] },
      { name: 'All Files', extensions: ['*'] },
    ],
  })
  if (result.canceled || result.filePaths.length === 0) return null
  // Windows パスを localfile:// プロトコル URL に変換（バックスラッシュをフォワードスラッシュへ）
  const normalized = result.filePaths[0].replace(/\\/g, '/')
  return `localfile:///${normalized}`
})

// ─── メインウィンドウ作成 ─────────────────────────────────────────────────────

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1200,
    minHeight: 700,
    title: 'ShuttleScope',
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
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
    mainWindow.loadURL('http://localhost:5173')
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

// ─── アプリ起動フロー ─────────────────────────────────────────────────────────

async function startApp(): Promise<void> {
  try {
    pythonProcess = startPythonBackend()
    await waitForBackend('http://localhost:8765/api/health', 10000)
    console.log('[Main] Backend ready')

    // localfile:// プロトコルハンドラーを登録
    registerLocalFileProtocol()

    createWindow()

    if (!mainWindow) return

    // ── DRM / EME 権限ハンドラー ──────────────────────────────────────────────
    // <webview> 内で DRM コンテンツ（Widevine L3）を再生するために
    // EME（Encrypted Media Extensions）と保護コンテンツの権限を許可する。
    // Electron 20+ は Widevine L3（ソフトウェア CDM）を内蔵している。
    mainWindow.webContents.session.setPermissionRequestHandler(
      (_webContents, permission, callback) => {
        // EME (encrypted-media), media, notifications などを許可
        const ALLOWED = new Set([
          'media',
          'mediaKeySystem',
          'geolocation', // 一部サイトが要求
        ])
        callback(ALLOWED.has(permission))
      }
    )

    mainWindow.webContents.session.setPermissionCheckHandler(
      (_webContents, permission) => {
        const ALLOWED = new Set(['media', 'mediaKeySystem'])
        return ALLOWED.has(permission)
      }
    )

    // YouTube / 外部コンテンツを iframe で読み込めるよう CSP を設定
    // onHeadersReceived は HTTP/HTTPS レスポンスのみ対象（dev モード用）
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
            " connect-src 'self' http://localhost:* ws://localhost:* https:;"
          ],
        },
      })
    })

    // YouTube リクエストに対して UA を明示的にブラウザ UA に設定（iframe 内も含む）
    mainWindow.webContents.session.webRequest.onBeforeSendHeaders(
      { urls: ['https://*.youtube.com/*', 'https://*.youtube-nocookie.com/*', 'https://*.googlevideo.com/*', 'https://*.ytimg.com/*'] },
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
