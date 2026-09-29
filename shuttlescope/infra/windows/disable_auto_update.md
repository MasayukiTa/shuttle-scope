# Windows 自動更新 / GPU ドライバ自動更新の抑止 (ShuttleScope 常時稼働ホスト向け)

> 常時稼働ホスト (i7/i9 + RTX) 用。開発機 (i5-1235U) では **適用しない**。

## 1. Windows Update の自動再起動抑止

### gpedit.msc (Pro/Enterprise)

1. `Win+R` → `gpedit.msc`
2. コンピューターの構成 > 管理用テンプレート > Windows コンポーネント > Windows Update
3. 「ログオンしているユーザーがいる場合、自動更新による自動的な再起動を行わない」→ **有効**
4. 「自動更新を構成する」→ **有効**、オプション 2「ダウンロードと自動インストールを通知」

### レジストリ (Home も可)

管理者 PowerShell:

```powershell
$p = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
New-Item -Path $p -Force | Out-Null
Set-ItemProperty $p NoAutoRebootWithLoggedOnUsers 1 -Type DWord
Set-ItemProperty $p AUOptions 2 -Type DWord
# アクティブ時間を 0-23 に
$p2 = 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'
Set-ItemProperty $p2 ActiveHoursStart 0 -Type DWord
Set-ItemProperty $p2 ActiveHoursEnd 23 -Type DWord
```

## 2. GPU ドライバ自動更新の抑止

Windows Update がドライバを上書きしないようにする。

### gpedit.msc

- コンピューターの構成 > 管理用テンプレート > Windows コンポーネント > Windows Update > Windows Update からのドライバーを除外する → **有効**

### レジストリ

```powershell
$p = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate'
New-Item -Path $p -Force | Out-Null
Set-ItemProperty $p ExcludeWUDriversInQualityUpdate 1 -Type DWord
```

### デバイスインストール制限 (任意、強力)

- コンピューターの構成 > 管理用テンプレート > システム > デバイスのインストール > デバイスのインストールの制限
- 「これらのデバイス セットアップ クラスのいずれかに一致するドライバーのインストールを禁止」
  - `{4d36e968-e325-11ce-bfc1-08002be10318}` (Display adapters) を追加

## 3. NVIDIA GeForce Experience / Game Ready

- GeForce Experience は導入しない。Studio ドライバを手動で半年に 1 回更新。
- 既に入っている場合はサービス `NVIDIA Display Container LS` 配下の自動更新タスクを無効化:

```powershell
Get-ScheduledTask -TaskPath '\NVIDIA\*' | Disable-ScheduledTask
```

## 4. 確認

```powershell
Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate'
```

再起動後、`gpupdate /force` でポリシー反映。
