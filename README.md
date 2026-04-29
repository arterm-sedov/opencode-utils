# opencode-utils

Utility scripts and skills for [OpenCode](https://opencode.ai) — the open source AI coding agent.

## Scripts

### `scripts/opencode-serve.ps1` (Windows)

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

---

### `scripts/opencode-serve.sh` (macOS / Linux)

Start and manage a persistent OpenCode server on Unix systems.

**Usage:**
```bash
./scripts/opencode-serve.sh start     # Start server
./scripts/opencode-serve.sh stop      # Stop server
./scripts/opencode-serve.sh restart   # Restart server
./scripts/opencode-serve.sh help      # Show help
```

Defaults: `hostname=0.0.0.0`, `port=64763`  
Logs: `~/.local/share/opencode/serve-logs`

Requires: Bash, OpenCode installed (`npm i -g opencode-ai`, `brew install opencode`, etc.)

## License

MIT — see [LICENSE](./LICENSE)
