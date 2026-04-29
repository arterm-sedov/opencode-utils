# opencode-utils

Utility scripts and skills for [OpenCode](https://opencode.ai) — the open source AI coding agent.

## Scripts

### `scripts/opencode-serve.ps1`

Start and manage a persistent OpenCode server on Windows.

**Usage:**
```powershell
.\scripts\opencode-serve.ps1           # Start server
.\scripts\opencode-serve.ps1 -Stop     # Stop server
.\scripts\opencode-serve.ps1 -Restart  # Restart server
.\scripts\opencode-serve.ps1 -Help     # Show help
```

Defaults: `hostname=0.0.0.0`, `port=64763`  
Logs: `%LOCALAPPDATA%\OpenCode\serve-logs`

Requires: PowerShell 7+, OpenCode installed (`npm i -g opencode-ai`)

## License

MIT — see [LICENSE](./LICENSE)
