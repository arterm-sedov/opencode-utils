#!/usr/bin/env python3
"""Convert opencode `export` JSON to a readable Markdown transcript.

Usage:
    opencode-md.py <session.json> [-o out.md]

Skips the leading "Exporting session: ..." line that opencode prints to
stdout alongside the JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def part_to_md(part: dict) -> str:
    t = part.get("type")
    if t == "text":
        return part.get("text", "").rstrip()
    if t == "reasoning":
        return f"```\n{part.get('text', '').rstrip()}\n```"
    if t == "file":
        fname = part.get("filename") or "file"
        mime = part.get("mime", "")
        return f"_📎 attachment: `{fname}` ({mime})_"
    if t == "tool":
        name = part.get("tool", "tool")
        state = part.get("state", {})
        args = state.get("input", {})
        meta = state.get("metadata", {}) or {}
        title = meta.get("title", "")
        head = f"**🔧 tool: `{name}`**"
        if title:
            head += f" — *{title}*"
        body_lines = []
        if args:
            body_lines.append("```json")
            try:
                body_lines.append(json.dumps(args, ensure_ascii=False, indent=2))
            except TypeError:
                body_lines.append(str(args))
            body_lines.append("```")
        out = state.get("output")
        if out:
            out_s = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=2)
            body_lines.append("```")
            body_lines.append(out_s[:4000])
            body_lines.append("```")
        return head + ("\n" + "\n".join(body_lines) if body_lines else "")
    if t == "agent":
        return f"_🤖 sub-agent: {part.get('name', 'agent')}_"
    if t == "subtask":
        return f"_↳ subtask: {part.get('description', '')}_"
    if t == "patch":
        files = part.get("files") or []
        hash_ = part.get("hash", "")
        head = f"**🩹 patch** — *{len(files)} file(s)*"
        if hash_:
            head += f" — `{hash_}`"
        body_lines = []
        for f in files[:8]:
            body_lines.append("```diff")
            body_lines.append((f if isinstance(f, str) else str(f))[:4000])
            body_lines.append("```")
        if len(files) > 8:
            body_lines.append(f"_(… {len(files) - 8} more file(s) truncated)_")
        return head + ("\n" + "\n".join(body_lines) if body_lines else "")
    if t == "snapshot":
        snap = part.get("snapshot", "")
        return f"_📸 snapshot: `{snap}`_"
    if t == "step-start" or t == "step-finish":
        return ""
    return f"_(part: {t})_"


def message_to_md(msg: dict) -> str:
    info = msg.get("info", {}) or {}
    role = info.get("role", "?")
    parts = msg.get("parts", []) or []
    body = "\n\n".join(p for p in (part_to_md(p) for p in parts) if p)
    if not body:
        return ""
    title_map = {"user": "👤 User", "assistant": "🤖 Assistant"}
    title = title_map.get(role, f"ℹ️ {role}")
    return f"## {title}\n\n{body}\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="export JSON file (or - for stdin)")
    ap.add_argument("-o", "--output", type=Path, help="output .md path (default stdout)")
    ap.add_argument("--title", help="override document title")
    args = ap.parse_args()

    raw = args.input.read_text() if args.input != Path("-") else sys.stdin.read()
    if raw.startswith("Exporting session:"):
        raw = raw.split("\n", 1)[1]

    data = json.loads(raw)
    info = data.get("info", {})
    title = args.title or info.get("title") or "OpenCode session"

    out = [f"# {title}", ""]
    out.append(f"- Session: `{info.get('id', '?')}`")
    out.append(f"- Slug: `{info.get('slug', '?')}`")
    out.append(f"- Agent: `{info.get('agent', '?')}` / model: `{info.get('model', {}).get('id', '?')}`")
    if info.get("directory"):
        out.append(f"- Directory: `{info['directory']}`")
    out.append("")

    for msg in data.get("messages", []):
        block = message_to_md(msg)
        if block:
            out.append(block)

    md = "\n".join(out)
    if args.output:
        args.output.write_text(md, encoding="utf-8")
        print(f"wrote {args.output} ({len(md):,} chars)", file=sys.stderr)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
