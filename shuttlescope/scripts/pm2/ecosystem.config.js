// ShuttleScope PM2 ecosystem (INFRA Phase C)
// すべて「明示実行しない限り」起動しない。
// 起動: pm2 start scripts/pm2/ecosystem.config.js
// 停止: pm2 delete all

module.exports = {
  apps: [
    {
      // FastAPI / uvicorn 本体
      name: 'shuttlescope-api',
      script: 'python',
      args: '-m uvicorn backend.main:app --host 0.0.0.0 --port 8765',
      cwd: '.',
      env: {
        PYTHONUNBUFFERED: '1',
        // ワーカーは別プロセス (shuttlescope-worker) で実行されるため、
        // FastAPI プロセス内の in-process runner は停止させる。
        SS_WORKER_STANDALONE: '1'
      },
      restart_delay: 3000,
      max_restarts: 50,
      autorestart: true
    },
    {
      // 解析ワーカー (backend.pipeline.worker スタンドアロン実装済み)
      // SS_WORKER_STANDALONE=1 で FastAPI 側の in-process runner を無効化し
      // 本プロセスが AnalysisJob を逐次処理する。ファイルロック
      // (backend/data/worker.lock) で多重起動を防止。
      name: 'shuttlescope-worker',
      script: 'python',
      args: '-m backend.pipeline.worker',
      cwd: '.',
      env: {
        PYTHONUNBUFFERED: '1',
        // スタンドアロンワーカー側でも同フラグを立て、意図しない二重起動を抑止する。
        SS_WORKER_STANDALONE: '1'
      },
      restart_delay: 3000,
      max_restarts: 50,
      autorestart: true
    },
    {
      // Ray head (Phase D 以降で有効化)。デフォルト disabled。
      // 起動する場合: pm2 start scripts/pm2/ecosystem.config.js --only ray-head
      name: 'ray-head',
      script: 'ray',
      args: 'start --head --port=6379 --block',
      cwd: '.',
      autorestart: false, // 明示的に起動するまで停止扱い
      max_restarts: 50,
      restart_delay: 3000
    },
    {
      // ヘルスモニタ (常時)
      name: 'health-monitor',
      script: 'python',
      args: 'scripts/health_monitor.py',
      cwd: '.',
      env: {
        PYTHONUNBUFFERED: '1',
        SS_NOTIFY_KIND: process.env.SS_NOTIFY_KIND || 'log',
        SS_HEALTH_URL: process.env.SS_HEALTH_URL || 'http://localhost:8765/api/health'
      },
      restart_delay: 3000,
      max_restarts: 50,
      autorestart: true
    }
  ]
}
