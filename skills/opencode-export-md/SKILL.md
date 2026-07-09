---
name: opencode-export-md
description: Convert an `opencode export` JSON dump of a chat session into a readable Markdown transcript for sharing, review, or archival. Use when the user asks to export an opencode session, save a chat as Markdown, share a transcript, or convert session JSON to .md. Do not use for editing existing Markdown — that is the regular document workflow.
---

# OpenCode session export to Markdown

Convert an `opencode export <sessionID>` JSON dump into a single Markdown file that preserves the conversation order and shows user / assistant messages, attached files, tool calls with inputs and outputs, and reasoning blocks.

## When to use

- The user says "export this chat", "save the conversation as md", "дай экспорт чата", "скинь транскрипт".
- The user wants to share or archive a specific opencode session as a standalone file.
- The user has an `opencode export ... > chat.json` file and wants a `.md` next to it.

Do not use when:

- The user only wants to read a session back inside opencode — use `opencode --continue` or `opencode --session <id>`.
- The session was exported with `--sanitize`; the textual content is already redacted and no Markdown export will recover it. Re-export without `--sanitize` first.

## Inputs

| Input | How it is obtained |
| --- | --- |
| Session JSON | `opencode export <sessionID> > chat.json` (no `--sanitize` unless the user explicitly wants redaction) |
| Session ID (current session) | `opencode session list` — pick the row matching the current task |
| Session ID (non-interactive) | `opencode session list --max-count 1` (most recent) or filter by title |

`opencode export` writes the JSON to stdout and prepends one line `Exporting session: <id>`. The converter skips that line automatically.

## Workflow

1. Pick the session ID:
   - Current session — the user knows it, or use `opencode session list` and confirm.
   - Most recent — `opencode session list --max-count 1` and read the first `Session ID` column.
2. Export the session:

   ```bash
   opencode export <sessionID> > /tmp/opencode/chat-export.json
   ```

3. Convert to Markdown:

   ```bash
   python3 ~/.agents/skills/opencode-export-md/scripts/opencode-md.py \
       /tmp/opencode/chat-export.json \
       -o /tmp/opencode/chat-export.md
   ```

4. Hand the path back to the user. Default destination under `/tmp/opencode/` is fine; copy the file elsewhere only if the user asks.

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

## Operational gotchas

- The script reads both files with a leading `Exporting session: ...` line and from raw stdin; the line is stripped before `json.loads`.
- Tool outputs longer than 4 000 chars are truncated. If the user needs the full output, re-export and split the file, or post-process the JSON.
- Reasoning blocks come back as `type: "reasoning"` parts; they are rendered as fenced code so they are visually distinct from regular prose.
- File attachments (drag-and-drop, paste) appear as `type: "file"` parts with `filename` and `mime`. The Markdown output only lists the metadata; the bytes are not embedded.

## Related

- `opencode session list` — list session IDs and titles.
- `opencode export --help` — flag reference; the only flag the skill cares about is `--sanitize` (avoid unless redacted output is wanted).
- `opencode-md` in `~/.local/bin/` is a symlink shortcut to `scripts/opencode-md.py` if installed; otherwise call the script by full path.
