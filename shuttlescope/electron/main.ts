import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import * as path from 'path'
import * as http from 'http'
import { existsSync } from 'fs'
import { pathToFileURL } from 'url'

let pythonProcess: ChildProcess | null = null
let mainWindow: BrowserWindow | null = null

// Wait for backend to be ready (polling)
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

// Start Python backend as child process
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

// IPC: open video file picker dialog
ipcMain.handle('open-video-file', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [
      { name: 'Video', extensions: ['mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'm4v', 'webm', 'ts', 'mts'] },
      { name: 'All Files', extensions: ['*'] },
    ],
  })
  if (result.canceled || result.filePaths.length === 0) return null
  // Convert OS path to file:// URL so <video src> can load it
  return pathToFileURL(result.filePaths[0]).href
})

// Create main window
function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1200,
    minHeight: 700,
    title: 'ShuttleScope',
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
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
    mainWindow.loadURL('http://localhost:5173')
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

// App startup flow
async function startApp(): Promise<void> {
  try {
    pythonProcess = startPythonBackend()
    await waitForBackend('http://localhost:8765/api/health', 10000)
    console.log('[Main] Backend ready')
    createWindow()
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
