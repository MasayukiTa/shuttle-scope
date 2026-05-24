import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// SKIP_RENDERER=true のときは main+preload のみビルド（start スクリプト用）
const skipRenderer = process.env.SKIP_RENDERER === 'true'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'electron/main.ts'),
        },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'electron/preload.ts'),
          // Round 258 R33 fix (R6 deferred P1): recorder hidden-window 用 preload を
          // 別 entry で出力する。main.ts は <preload>/recorder-preload.cjs を参照する。
          'recorder-preload': resolve(__dirname, 'electron/recorder-preload.ts'),
        },
        output: {
          // package.json "type":"module" だと .mjs になり Electron sandbox と非互換のため CJS 強制
          format: 'cjs',
          entryFileNames: '[name].cjs',
        },
      },
    },
  },
  ...(skipRenderer
    ? {}
    : {
        renderer: {
          root: 'src',
          // src/public/ 配下を out/renderer/ に自動コピーさせる。
          // 既定の publicDir は <root>/public だが electron-vite では
          // 解決されないケースがあるため絶対パスで明示。これがないと
          // error-reporter.js / favicon 等が ship されず、白画面診断
          // banner や PWA icon が壊れる。
          publicDir: resolve(__dirname, 'src/public'),
          build: {
            rollupOptions: {
              input: {
                index: resolve(__dirname, 'src/index.html'),
              },
            },
          },
          plugins: [react()],
          resolve: {
            alias: {
              '@': resolve(__dirname, 'src'),
            },
          },
        },
      }),
})
