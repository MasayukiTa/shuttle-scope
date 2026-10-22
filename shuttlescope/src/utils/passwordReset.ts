// パスワードリセット機能の有効/無効 (画面側の単一の切替)。
// 申請画面 (PasswordResetRequestPage) と確定画面 (PasswordResetConfirmPage) の
// 両方がこの値を見る。バックエンドは SS_PASSWORD_RESET_ENABLED で同じ状態にそろえる。
// 再開するときはここを true にし、サーバー側の SS_PASSWORD_RESET_ENABLED=1 も立てる。
export const PASSWORD_RESET_ENABLED = false
