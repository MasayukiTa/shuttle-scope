import { spawn } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = join(__dirname, '..')
const require = createRequire(import.meta.url)
const electronExe = require('electron')
const electronEnv = { ...process.env }

delete electronEnv.ELECTRON_RUN_AS_NODE

const child = spawn(electronExe, ['.'], {
  cwd: root,
  stdio: 'inherit',
  env: electronEnv,
})

child.on('exit', (code) => {
  process.exit(code ?? 0)
})
