// ShuttleScope PM2 ecosystem (INFRA Phase C)
// すべて「明示実行しない限り」起動しない。
// 起動: pm2 start scripts/pm2/ecosystem.config.js
// 停止: pm2 delete all

// Round 258 R7 P1 fix (Codex review):
// 旧定義は uvicorn を `--host 0.0.0.0` で直接起動しており、main.py 側の
// LAN_MODE / SS_OPERATOR_TOKEN ガード (LAN_MODE=true で SS_OPERATOR_TOKEN 未設定なら
// fatal exit) を完全に迂回していた。
// 既定は loopback bind に倒し、LAN/tunnel 公開時のみ環境変数で opt-in する。
//   - SS_API_BIND_HOST  (default 127.0.0.1)
//   - 0.0.0.0 を選ぶ場合は SS_OPERATOR_TOKEN + (PUBLIC_MODE or LAN_MODE) を伴うこと。
//     起動前 sanity check を別 script (scripts/preflight_pm2.sh) で実装する想定。
const _API_BIND_HOST = process.env.SS_API_BIND_HOST || '127.0.0.1'
const _API_PORT = process.env.SS_API_PORT || '8765'
if (_API_BIND_HOST !== '127.0.0.1' && _API_BIND_HOST !== '::1') {
  // 公開バインドする場合は安全 envの存在を必須にする
  const _opTok = (process.env.SS_OPERATOR_TOKEN || '').trim()
  const _public = process.env.PUBLIC_MODE === '1' || process.env.PUBLIC_MODE === 'true'
  const _lan = process.env.LAN_MODE === 'true'
  if (!_opTok || (!_public && !_lan)) {
    // PM2 起動時に throw すれば pm2 はエラーで起動を止める
    throw new Error(
      `[ecosystem.config.js] Refusing to bind API on ${_API_BIND_HOST}: ` +
      `SS_OPERATOR_TOKEN must be set AND (PUBLIC_MODE=1 or LAN_MODE=true) is required. ` +
      `Set SS_API_BIND_HOST=127.0.0.1 for local-only deployments (recommended).`
    )
  }
}

module.exports = {
  apps: [
    {
      // FastAPI / uvicorn 本体
      name: 'shuttlescope-api',
      script: 'python',
      args: `-m uvicorn backend.main:app --host ${_API_BIND_HOST} --port ${_API_PORT}`,
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
