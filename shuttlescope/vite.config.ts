import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// Electronを使わない場合の単体Vite設定（開発デバッグ用）
export default defineConfig({
  plugins: [react()],
  root: 'src',
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
  },
  build: {
    outDir: '../dist/renderer',
    emptyOutDir: true,
  },
})
