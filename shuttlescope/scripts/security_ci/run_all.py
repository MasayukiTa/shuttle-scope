# -*- coding: utf-8 -*-
"""全 CI 攻撃テストを順次実行。1 つでも CRITICAL が出たら exit 1。

使い方:
  python run_all.py                              # 本番 (app.shuttle-scope.com) を攻撃
  SS_ATTACK_HOST=localhost SS_ATTACK_PORT=8765 \
    SS_ATTACK_INSECURE=1 python run_all.py       # ローカル backend を攻撃

環境変数で attack 対象を切替可能。admin 認証情報は不要。
"""
import subprocess, sys, os, time, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = [
    "test_no_auth_endpoints.py",
    "test_jwt_forgery.py",
    "test_tls_headers.py",
    "test_smuggling_methods.py",
    "test_public_endpoints.py",
]


def main():
    print(f"[*] Target: {os.environ.get('SS_ATTACK_HOST', 'app.shuttle-scope.com')}:{os.environ.get('SS_ATTACK_PORT', '443')}")
    print(f"[*] Insecure TLS: {os.environ.get('SS_ATTACK_INSECURE', '0')}")
    print(f"[*] Suites: {len(SUITES)}\n")

    failures = []
    t_start = time.time()
    for suite in SUITES:
        path = os.path.join(HERE, suite)
        print(f"\n{'='*60}\n  {suite}\n{'='*60}")
        rc = subprocess.run([sys.executable, path]).returncode
        if rc != 0:
            failures.append((suite, rc))

    dt = time.time() - t_start
    print(f"\n\n{'='*60}\n  TOTAL: {len(SUITES) - len(failures)}/{len(SUITES)} passed in {dt:.1f}s\n{'='*60}")
    if failures:
        for suite, rc in failures:
            print(f"  ❌ {suite} (rc={rc})")
        sys.exit(1)
    print("  ✅ ALL PASSED")


if __name__ == "__main__":
    main()
