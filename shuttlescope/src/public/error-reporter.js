/* 白画面診断: bundle 評価より前に error / unhandledrejection を捕捉して
   画面最上部に banner で表示する。
   - CSP `script-src 'self'` のため inline <script> は不可、別ファイルで配信。
   - React の ErrorBoundary が捕捉できない module-level throw (ESM import 時の
     sync エラー) もここで確実に拾う。
   - PWA / iOS Safari で Web Inspector が無いユーザのための唯一の診断手段。 */
/* DIAG_BUILD_TAG: 2026-05-16T04:15:00Z */
(function () {
  /* 起動確認 chip: error-reporter.js が実際に実行されたかを画面右下に常時表示する。
     これが出ていれば「ファイルが load されてない / CSP 拒否」は除外できる。 */
  try {
    var tag = document.createElement('div');
    tag.id = '__ss_diag_tag__';
    tag.style.cssText =
      'position:fixed;bottom:4px;right:4px;z-index:99998;' +
      'padding:3px 6px;font:10px/1 monospace;' +
      'background:rgba(34,197,94,0.85);color:#fff;' +
      'border-radius:3px;pointer-events:none';
    tag.textContent = 'diag@2026-05-16T04:15Z';
    var attach = function () { (document.body || document.documentElement).appendChild(tag); };
    if (document.body) attach();
    else document.addEventListener('DOMContentLoaded', attach);
  } catch { /* ignore */ }

  var show = function (label, msg) {
    try {
      var bar = document.getElementById('__ss_error_bar__');
      if (!bar) {
        bar = document.createElement('div');
        bar.id = '__ss_error_bar__';
        bar.style.cssText =
          'position:fixed;top:0;left:0;right:0;z-index:99999;' +
          'padding:10px 14px;font:12px/1.4 -apple-system,sans-serif;' +
          'background:#7f1d1d;color:#fff;white-space:pre-wrap;' +
          'word-break:break-all;max-height:60vh;overflow:auto;' +
          'border-bottom:2px solid #f87171;' +
          // ★ pointer-events:none 必須。 これを auto のままにすると
          //  Promise rejection 等で bar が高さ 60vh まで成長したとき、
          //  画面上半分をまるごと占有 (z=99999) してその下にある UI
          //  (mobile annotate calib の 6 点設置画面など) のタップを完全に
          //  横取りしてしまう。bar 自体には interaction 不要なので透過させる。
          'pointer-events:none';
        (document.body || document.documentElement).appendChild(bar);
      }
      // JST (Asia/Tokyo) 固定で HH:MM:SS 表示。
      // 旧版は toISOString() = UTC で「米国時刻？」と誤解を招いていた。
      var t = new Date().toLocaleTimeString('ja-JP', {
        hour12: false,
        timeZone: 'Asia/Tokyo',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      });
      bar.textContent = '[' + t + ' JST] ' + label + ': ' + msg + '\n' + (bar.textContent || '');
    } catch {
      /* DOM 未準備時は無視 */
    }
  };
  window.addEventListener('error', function (e) {
    var src = e.error && (e.error.stack || e.error.message);
    var msg = src || e.message || String(e);
    // "Script error." は cross-origin script のエラーで Safari 等が詳細を秘匿
    // するときの generic noise。iOS Safari の "ホーム画面に追加" 共有シート、
    // PWA 内 cross-origin script (analytics 等)、AirPlay などで自動発火する。
    // e.filename が空文字 / null / undefined のいずれでも origin-less ノイズ。
    var isGeneric = /^Script error\.?$/.test(msg);
    var noOrigin = !e.filename && (!e.lineno || e.lineno === 0);
    if (isGeneric && noOrigin) return;
    show('Error', msg + '\n  at ' + (e.filename || '?') + ':' + e.lineno + ':' + e.colno);
  });
  window.addEventListener('unhandledrejection', function (e) {
    var r = e.reason;
    var msg = (r && (r.stack || r.message)) || String(r);
    // AbortError: video element の load/play を unmount や seek でキャンセル
    // した時に発火する既知良性エラー (mobile calib 出入りで video 再 mount
    // するたびに出る)。実害無く noise なので無視する。
    var name = r && r.name;
    if (name === 'AbortError') return;
    if (/The operation was aborted/i.test(msg)) return;
    show('PromiseRejection', msg);
  });
})();
