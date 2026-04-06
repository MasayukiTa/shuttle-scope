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
