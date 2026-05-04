import { execSync, spawn } from 'node:child_process'
import { existsSync, readdirSync, rmSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = join(__dirname, '..')

const require = createRequire(import.meta.url)
const electronExe = require('electron')
const rendererOut = join(root, 'out', 'renderer', 'index.html')
const electronEnv = { ...process.env }

delete electronEnv.ELECTRON_RUN_AS_NODE

const SKIP_DIRS = new Set([
  'node_modules',
  '.venv',
  'out',
  '__pycache__',
  '.git',
  'dist',
  'scripts',
])

function newestMtime(dir) {
  let newest = 0
  let entries = []

  try {
    entries = readdirSync(dir, { withFileTypes: true })
  } catch {
    return 0
  }

  for (const entry of entries) {
    if (SKIP_DIRS.has(entry.name)) continue

    const fullPath = join(dir, entry.name)
    if (entry.isDirectory()) {
      const childMtime = newestMtime(fullPath)
      if (childMtime > newest) newest = childMtime
      continue
    }

    try {
      const mtime = statSync(fullPath).mtimeMs
      if (mtime > newest) newest = mtime
    } catch {
      // Ignore transient filesystem errors while checking timestamps.
    }
  }

  return newest
}

function shouldBuildRenderer() {
  if (!existsSync(rendererOut)) return true

  const rendererMtime = statSync(rendererOut).mtimeMs
  const srcMtime = newestMtime(join(root, 'src'))
  const electronMtime = newestMtime(join(root, 'electron'))

  return Math.max(srcMtime, electronMtime) > rendererMtime
}

let needsRendererBuild = shouldBuildRenderer()

if (needsRendererBuild && existsSync(join(root, 'out', 'renderer'))) {
  console.log('[start] Source changed. Clearing renderer cache...')
  rmSync(join(root, 'out', 'renderer'), { recursive: true, force: true })
} else if (!needsRendererBuild) {
  console.log('[start] Source unchanged. Reusing renderer cache.')
}

process.stdout.write('[start] Building main/preload... ')
const t0 = Date.now()
execSync('npm run build', {
  cwd: root,
  stdio: 'pipe',
  env: { ...process.env, SKIP_RENDERER: 'true' },
})
console.log(`done (${Date.now() - t0}ms)`)

const launchLabel = needsRendererBuild
  ? '[start] Launching Electron. Renderer will build in the background...'
  : '[start] Launching Electron with cached renderer...'
console.log(launchLabel)

const electron = spawn(electronExe, ['.'], {
  cwd: root,
  stdio: 'inherit',
  detached: false,
  env: electronEnv,
})

electron.on('exit', (code) => process.exit(code ?? 0))

if (needsRendererBuild) {
  const t1 = Date.now()

  try {
    execSync('npm run build', {
      cwd: root,
      stdio: 'inherit',
      env: { ...process.env, SKIP_RENDERER: 'false' },
    })
    console.log(
      `[start] Renderer build finished (${Date.now() - t1}ms). App should now be visible.`
    )
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    console.error('[start] Renderer build failed:', message)
  }
}
