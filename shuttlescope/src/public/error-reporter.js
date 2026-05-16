/* 白画面診断: bundle 評価より前に error / unhandledrejection を捕捉して
   画面最上部に banner で表示する。
   - CSP `script-src 'self'` のため inline <script> は不可、別ファイルで配信。
   - React の ErrorBoundary が捕捉できない module-level throw (ESM import 時の
     sync エラー) もここで確実に拾う。
   - PWA / iOS Safari で Web Inspector が無いユーザのための唯一の診断手段。 */
(function () {
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
          'border-bottom:2px solid #f87171';
        (document.body || document.documentElement).appendChild(bar);
      }
      var t = new Date().toISOString().slice(11, 19);
      bar.textContent = '[' + t + '] ' + label + ': ' + msg + '\n' + (bar.textContent || '');
    } catch (_e) {
      /* DOM 未準備時は無視 */
    }
  };
  window.addEventListener('error', function (e) {
    var src = e.error && (e.error.stack || e.error.message);
    var msg = src || e.message || String(e);
    show('Error', msg + '\n  at ' + (e.filename || '?') + ':' + e.lineno + ':' + e.colno);
  });
  window.addEventListener('unhandledrejection', function (e) {
    var r = e.reason;
    var msg = (r && (r.stack || r.message)) || String(r);
    show('PromiseRejection', msg);
  });
})();
