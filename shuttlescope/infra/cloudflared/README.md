# Cloudflare Tunnel setup for ShuttleScope

Target public app URL:

- `https://app.shuttle-scope.com`

## 1. Authenticate and create the named tunnel

```powershell
cloudflared tunnel login
cloudflared tunnel create shuttlescope
```

This creates:

- a tunnel UUID
- `~/.cloudflared/<UUID>.json`

## 2. Fill the template config

Update [`config.yml`](./config.yml):

- replace `<UUID>`
- replace `<USER>`

The template is already prepared for:

- `app.shuttle-scope.com -> http://localhost:8765`
- `ssh.shuttle-scope.com -> ssh://localhost:22`

## 3. Bind DNS

```powershell
cloudflared tunnel route dns shuttlescope app.shuttle-scope.com
cloudflared tunnel route dns shuttlescope ssh.shuttle-scope.com
```

## 4. Local run

```powershell
cloudflared tunnel --config infra\cloudflared\config.yml run
```

## 5. Windows service

```powershell
Copy-Item infra\cloudflared\config.yml $env:USERPROFILE\.cloudflared\config.yml
cloudflared service install
Start-Service Cloudflared
Get-Service Cloudflared
```

## 6. Access

After DNS propagation and tunnel startup:

- open `https://app.shuttle-scope.com`

## Notes

- Cloudflare dashboard / Zero Trust policies must still be configured in the actual Cloudflare account.
- The ShuttleScope backend now prefers named tunnel config when `cloudflared` is available and the config file is valid.
