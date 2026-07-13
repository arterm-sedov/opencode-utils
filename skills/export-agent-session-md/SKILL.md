---
name: export-agent-session-md
description: Export AI coding agent sessions to Markdown. Supports OpenCode, MiMoCode, Claude Code, Aider, Codex, Cline, Cursor, and more. Use when the user asks to export any AI chat session, save conversations as Markdown, or share chat transcripts.
---

# AI Agent Session Export to Markdown

Export sessions from multiple AI coding agents to readable Markdown transcripts. Supports OpenCode, MiMoCode, Claude Code, Aider, Codex CLI, Cline/Roo Code, and Cursor.

## When to use

- The user says "export this chat", "save the conversation as md", "дай экспорт чата", "скинь транскрипт".
- The user wants to share or archive a specific agent session as a standalone file.
- The user wants to export sessions from any supported AI coding agent.

Do not use when:

- The user only wants to read a session back inside the agent — use the agent's native continue/resume.
- The session was exported with `--sanitize`; the textual content is already redacted.

## Supported Agents

| Agent | Storage | Export Method |
|-------|---------|---------------|
| **OpenCode** | SQLite `~/.local/share/opencode/opencode.db` | CLI `opencode export` |
| **MiMoCode** | SQLite `~/.local/share/mimocode/mimocode.db` | Direct DB read |
| **Claude Code** | JSONL `~/.claude/projects/**/*.jsonl` | Direct file read |
| **Aider** | Markdown `.aider.chat.history.md` | Direct file read |
| **Codex CLI** | JSONL `~/.codex/sessions/**/rollout-*.jsonl` | Direct file read |
| **Cline/Roo Code** | SQLite `~/.cline/data/sessions/` | Direct DB read |
| **Cursor** | SQLite `~/.cursor/chats/*/store.db` | Direct DB read |

## Automatic Sanitization

**All exports are automatically sanitized** to remove secrets and sensitive data. The exported Markdown will include a warning header if any patterns were redacted.

### What gets sanitized

| Pattern | Replacement | Example |
|---------|-------------|---------|
| Private IPs | `192.168.x.x`, `10.x.x.x` | `192.168.1.100` → `192.168.x.x` |
| VPN/Tailscale IPs | `100.x.x.x` | `100.98.142.108` → `100.x.x.x` |
| SSH key paths | `id_KEY` | `id_rsa` → `id_KEY` |
| Home directories | `/home/USER/` | `/home/alice/` → `/home/USER/` |
| Usernames | `USER` | `alice-lnx` → `USER` |
| API keys | `sk-REDACTED` | `sk-abc123...` → `sk-REDACTED` |
| GitHub tokens | `ghp_REDACTED` | `ghp_abc123...` → `ghp_REDACTED` |
| Private keys | `-----BEGIN REDACTED KEY-----` | Full key block redacted |
| Passwords | `REDACTED` | `-p mypassword` → `-p REDACTED` |
| Corp hostnames | `hostname.corp.example` | `server.corp.acme.com` → `hostname.corp.example` |

### Example warning in exported file

```markdown
# Session Title

> ⚠️ **Sanitized:** private IP (3 occurrences), username (2 occurrences), API key (1 occurrence)

- **Session:** `ses_abc123`
...
```
| **Cursor** | SQLite `~/.cursor/User/workspaceStorage/*/state.vscdb` | Direct DB read |

## Quick Start

### List sessions for an agent
```bash
python3 scripts/agent-export.py --agent opencode --list
python3 scripts/agent-export.py --agent claude-code --list
python3 scripts/agent-export.py --agent aider --list
```

### Export a single session
```bash
python3 scripts/agent-export.py --agent opencode --session <id> -o output.md
python3 scripts/agent-export.py --agent claude-code --session <id> -o output.md
```

### Auto-detect agent from file
```bash
python3 scripts/agent-export.py --detect session.jsonl -o output.md
```

### List all available adapters
```bash
python3 scripts/agent-export.py --agents
```

## CLI Reference

```
agent-export.py [-h] [--agent AGENT | --detect FILE | --all]
                [--session SESSION] [-o OUTPUT] [--list] [--agents]
                [--no-sanitize]

options:
  --agent AGENT         agent name (opencode, mimocode, claude-code, aider, codex, cline, cursor)
  --detect FILE         auto-detect agent from file content
  --all                 bulk export all agents
  --session SESSION     session ID to export
  -o OUTPUT, --output OUTPUT  output path (file or directory)
  --list                list available sessions
  --agents              list available adapters
  --no-sanitize         skip secret sanitization (exports raw content)
```

### Sanitization control

By default, all exports are **automatically sanitized** to remove secrets (IPs, tokens, usernames, etc.). To export raw content without sanitization:

```bash
# Default: sanitized
python3 scripts/agent-export.py --agent opencode --session <id> -o output.md

# Raw: no sanitization
python3 scripts/agent-export.py --agent opencode --session <id> --no-sanitize -o output.md
```

## Output

- One Markdown file.
- Header: session title, ID, slug, agent + model, working directory.
- Each message becomes a `## 👤 User` or `## 🤖 Assistant` block.
- Part rendering:
  - `text` — plain prose, no extra wrapper.
  - `reasoning` — fenced ` ``` ` block, prefixed by a small inline marker is unnecessary; the fence is enough.
  - `file` — italic line `📎 attachment: \`<name>\` (<mime>)`.
  - `tool` — bold line `🔧 tool: \`<name>\` — *<title>*`, then a JSON ```json``` block of `state.input` and a ``` ``` block of `state.output` (truncated to 4 000 chars to keep the file readable).
  - `agent` / `subtask` — short italic line with the name or description.
  - `step-start` / `step-finish` — skipped (empty body).
- Messages with no body after part filtering are skipped, so empty assistants and pure step boundaries do not pollute the transcript.

## CLI

```
opencode-md.py <input.json|-> [-o OUT.md] [--title TEXT]
```

- Positional `input`: path or `-` for stdin.
- `-o / --output`: write to file instead of stdout.
- `--title`: override the document title (defaults to `info.title` from the JSON).
- Non-zero exit only on JSON parse error or unreadable input — the converter does not reject malformed messages, it just skips the bad ones.

## Batch export

A bulk-export script is available at `references/opencode-bulk-export.py`. It reads the opencode SQLite database directly, groups sessions by repository, and exports all sessions as dated Markdown files.

```bash
python3 ~/.agents/skills/opencode-export-md/references/opencode-bulk-export.py \
    --output ~/repos/.agent-chats \
    --repos-base ~/repos
```

Output structure:
```
~/repos/.agent-chats/
├── my-project/
│   ├── 20260709-1842-Some-session-title.md
│   └── ...
├── another-project/
│   └── ...
├── _home/
│   └── ...
└── ...
```

Options: `--output`, `--converter`, `--repos-base`, `--db`, `--tmp-dir`. See `--help` for defaults.

## Operational gotchas

- **128 KB pipe buffer truncation.** `subprocess.run(capture_output=True)` silently truncates stdout at 128 KB. Sessions larger than this (common for long chats with tool calls) produce broken JSON. The fix: always use shell redirect (`opencode export <id> > file.json`) instead of capturing stdout. The bulk-export script does this automatically.
- The script reads both files with a leading `Exporting session: ...` line and from raw stdin; the line is stripped before `json.loads`.
- `opencode session list` filters by the current working directory. To see all sessions, query the SQLite database directly at `~/.local/share/opencode/opencode.db` (table: `session`).
- Tool outputs longer than 4 000 chars are truncated in the Markdown output. If the user needs the full output, re-export and split the file, or post-process the JSON.
- Reasoning blocks come back as `type: "reasoning"` parts; they are rendered as fenced code so they are visually distinct from regular prose.
- File attachments (drag-and-drop, paste) appear as `type: "file"` parts with `filename` and `mime`. The Markdown output only lists the metadata; the bytes are not embedded.

## Architecture

```
scripts/
├── agent-export.py          # Main CLI entry point
├── opencode-md.py           # Legacy single-agent converter
└── agents/
    ├── __init__.py          # Agent registry (auto-discovery)
    ├── base.py              # Abstract AgentAdapter + NormalizedSession
    ├── detector.py          # Auto-detection by content sniffing
    ├── opencode.py          # OpenCode/MiMoCode adapter
    ├── claude_code.py       # Claude Code adapter
    ├── aider.py             # Aider adapter
    ├── codex.py             # Codex CLI adapter
    ├── cline.py             # Cline/Roo Code adapter
    └── cursor.py            # Cursor adapter
```

## Related

- `opencode session list` — list session IDs and titles (filtered to current directory).
- `opencode export --help` — flag reference; the only flag the skill cares about is `--sanitize` (avoid unless redacted output is wanted).
- `opencode-md` in `~/.local/bin/` is a symlink shortcut to `scripts/opencode-md.py` if installed; otherwise call the script by full path.
- `references/opencode-bulk-export.py` — batch export all sessions from the SQLite database.
- `scripts/agent-export.py` — universal multi-agent session exporter.
