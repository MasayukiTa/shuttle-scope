/**
 * ShuttleScope 高速起動スクリプト
 *
 * ── renderer の再ビルド判定 ────────────────────────────────────────────────────
 *   src/ または electron/ 配下に renderer ビルドより新しいファイルがあれば再ビルド
 *   変更がなければキャッシュを再利用 → 0.5s でアプリ起動
 *
 * ── 起動フロー ─────────────────────────────────────────────────────────────────
 *   main+preload ビルド (0.5s)
 *     → Electron 起動（スプラッシュ即時表示）
 *     → [変更あり] renderer を並行ビルド (~10s) → 完了後アプリ表示
 *     → [変更なし] そのままアプリ表示
 */

import { execSync, spawn } from 'node:child_process'
import { existsSync, statSync, readdirSync, rmSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join } from 'node:path'
import { createRequire } from 'node:module'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = join(__dirname, '..')

// electron パッケージから直接バイナリパスを取得（PATH に依存しない）
const require = createRequire(pathToFileURL(join(root, 'package.json')).href)
const electronExe = require('electron')
const rendererOut = join(root, 'out', 'renderer', 'index.html')

// ── ソースファイルの最終更新時刻を再帰取得 ────────────────────────────────────
const SKIP_DIRS = new Set(['node_modules', '.venv', 'out', '__pycache__', '.git', 'dist', 'scripts'])

function newestMtime(dir) {
  let newest = 0
  let entries
  try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return 0 }
  for (const e of entries) {
    if (SKIP_DIRS.has(e.name)) continue
    const p = join(dir, e.name)
    if (e.isDirectory()) {
      const t = newestMtime(p)
      if (t > newest) newest = t
    } else {
      try {
        const t = statSync(p).mtimeMs
        if (t > newest) newest = t
      } catch {}
    }
  }
  return newest
}

// ── renderer 再ビルドが必要か判定 ─────────────────────────────────────────────
let needsRendererBuild = !existsSync(rendererOut)

if (!needsRendererBuild) {
  const rendererMtime = statSync(rendererOut).mtimeMs
  const srcMtime    = newestMtime(join(root, 'src'))
  const electronMtime = newestMtime(join(root, 'electron'))
  const newest = Math.max(srcMtime, electronMtime)
  if (newest > rendererMtime) {
    console.log('[start] ソース変更を検出 → renderer 再ビルドします')
    rmSync(join(root, 'out', 'renderer'), { recursive: true, force: true })
    needsRendererBuild = true
  } else {
    console.log('[start] ソース変更なし → renderer キャッシュ利用')
  }
}

// ── Step 1: main + preload ビルド (~0.5s) ────────────────────────────────────
process.stdout.write('[start] Building main/preload... ')
const t0 = Date.now()
execSync('npm run build', {
  cwd: root,
  stdio: 'pipe',  // "renderer config is missing" 警告を抑制
  env: { ...process.env, SKIP_RENDERER: 'true' },
})
console.log(`done (${Date.now() - t0}ms)`)

// ── Step 2: Electron 起動（スプラッシュ即時表示） ─────────────────────────────
const label = needsRendererBuild
  ? '[start] Electron 起動 → renderer をバックグラウンドでビルド中...'
  : '[start] Electron 起動 → キャッシュ済み renderer をロード'
console.log(label)

const electron = spawn(electronExe, ['.'], {
  cwd: root,
  stdio: 'inherit',
  detached: false,
})
electron.on('exit', (code) => process.exit(code ?? 0))

// ── Step 3: renderer 再ビルド（変更があった場合のみ） ─────────────────────────
if (needsRendererBuild) {
  const t1 = Date.now()
  try {
    execSync('npm run build', {
      cwd: root,
      stdio: 'inherit',
      env: { ...process.env, SKIP_RENDERER: 'false' },
    })
    console.log(`[start] renderer ビルド完了 (${Date.now() - t1}ms) → アプリを自動表示`)
  } catch (err) {
    console.error('[start] renderer ビルド失敗:', err.message)
  }
}
