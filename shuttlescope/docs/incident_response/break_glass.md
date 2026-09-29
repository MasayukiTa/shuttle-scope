# Break-glass Runbook

admin パスワード喪失または admin アカウント不在時の救済手順。

## シナリオ A: admin パスワードを忘れた

### 手順 (30 分以内)

```powershell
# 1. backend を停止
Stop-Process -Name python -ErrorAction SilentlyContinue

# 2. .env.development に bootstrap 用の新パスワードを設定
#    BOOTSTRAP_ADMIN_PASSWORD=<openssl rand -base64 24>
#    BOOTSTRAP_ADMIN_USERNAME=admin   (既存と同じユーザー名にすること)

# 3. backend の bootstrap_admin ロジックを起動するため、
#    既存 admin の password_hash を一時的に NULL にする
.\backend\.venv\Scripts\python -c "
from backend.db.database import SessionLocal
from backend.db.models import User
with SessionLocal() as db:
    u = db.query(User).filter(User.role == 'admin').first()
    if u:
        u.password_hash = None
        db.commit()
        print(f'reset password_hash for admin user_id={u.id}')
"

# 4. backend を起動 → 起動時の bootstrap が新パスワードを設定
.\start.bat

# 5. 新パスワードで login → access_log で 'login' イベント確認
```

## シナリオ B: 全 admin アカウントが消失/ロック

```powershell
# 1. backend 停止
# 2. .env.development の BOOTSTRAP_ADMIN_USERNAME を新規ユーザー名に変更
# 3. BOOTSTRAP_ADMIN_PASSWORD を強パスフレーズに設定
# 4. backend 起動 → 新規 admin ユーザーが自動作成される
# 5. 旧 admin ユーザーの監査記録を確認 (なぜ消えたか)
```

## シナリオ C: SECRET_KEY 喪失で全 JWT が無効

通常運用: SECRET_KEY ローテで全員ログアウト → 再ログイン要
Break-glass: ユーザーがログインできない場合、シナリオ A の手順で admin パスワード再発行

## 監査記録

Break-glass を実行した場合、必ず以下を記録:

- 実行者氏名・実行日時
- 実行理由 (パスワード喪失、admin 不在等)
- 実行手順 (シナリオ A/B/C のどれか)
- 事後の admin アカウント数と権限

記録先: `docs/incident_response/incidents/YYYY-MM-DD_break_glass.md`
