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

## Skills

Skills live under `skills/<skill-name>/` following the
[`skill-creator`](https://github.com/anomalyco/skill-creator) layout (one
`SKILL.md` per skill, plus `scripts/`, `references/`, `examples/` as needed).
They can be installed locally by symlinking the individual skill directory
into `~/.agents/skills/`:

```bash
ln -sfn "$(pwd)/skills/opencode-export-md" ~/.agents/skills/opencode-export-md
```

| Skill | Purpose |
| --- | --- |
| [`skills/opencode-export-md/`](skills/opencode-export-md/SKILL.md) | Convert an `opencode export` JSON dump into a readable Markdown transcript. |

## Layout

```
opencode-utils/
├── README.md
├── LICENSE
├── .gitignore
├── scripts/                       # executable utilities
│   ├── opencode-serve.ps1
│   └── opencode-serve.sh
└── skills/
    └── opencode-export-md/        # self-contained skill
        ├── SKILL.md
        ├── scripts/
        │   └── opencode-md.py
        ├── references/
        │   └── parts-and-sanitize.md
        └── examples/
            ├── minimal-session.json
            └── minimal-session.md
```

## License

MIT — see [LICENSE](./LICENSE)
