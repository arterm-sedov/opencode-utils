#!/usr/bin/env python3
"""Universal multi-agent session exporter to Markdown.

Supports: OpenCode, MiMoCode, Claude Code, Aider, Codex, Cline, Cursor, and more.
Each agent is handled by an adapter in scripts/agents/.

Usage:
    agent-export.py --agent <name> --session <id> [-o output.md]
    agent-export.py --detect <file> [-o output.md]
    agent-export.py --agent <name> --list
    agent-export.py --all [--output-dir ./chats/]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the scripts directory is on the path so agents package resolves.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from agents import all_adapters, get_adapter
from agents.detector import detect_agent, detect_agent_from_string


def cmd_list(agent_name: str | None) -> int:
    adapters = all_adapters() if agent_name is None else {agent_name: get_adapter(agent_name)}
    if agent_name and agent_name not in adapters:
        print(f"error: unknown agent '{agent_name}'", file=sys.stderr)
        _print_available()
        return 1

    for name, cls in sorted(adapters.items()):
        adapter = cls()
        sessions = adapter.discover_sessions()
        if not sessions:
            continue
        print(f"\n=== {name} ({len(sessions)} sessions) ===\n")
        for s in sessions:
            print(f"  {s.session_id}  {s.title or '(untitled)'}  [{s.file_path}]")

    return 0


def cmd_export(agent_name: str, session_id: str, output: Path | None) -> int:
    cls = get_adapter(agent_name)
    if cls is None:
        print(f"error: unknown agent '{agent_name}'", file=sys.stderr)
        _print_available()
        return 1

    adapter = cls()
    raw = adapter.read_session(session_id)
    normalized = adapter.normalize(raw)
    md = adapter.export_markdown(normalized)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md, encoding="utf-8")
        print(f"wrote {output} ({len(md):,} chars)", file=sys.stderr)
    else:
        sys.stdout.write(md)

    return 0


def cmd_detect(file_path: Path, output: Path | None) -> int:
    agent_name = detect_agent(file_path)
    if agent_name is None:
        print("error: could not detect agent format", file=sys.stderr)
        return 1

    print(f"detected agent: {agent_name}", file=sys.stderr)
    cls = get_adapter(agent_name)
    if cls is None:
        print(f"error: no adapter registered for '{agent_name}'", file=sys.stderr)
        return 1

    adapter = cls()
    raw = adapter.read_session(str(file_path))
    normalized = adapter.normalize(raw)
    md = adapter.export_markdown(normalized)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md, encoding="utf-8")
        print(f"wrote {output} ({len(md):,} chars)", file=sys.stderr)
    else:
        sys.stdout.write(md)

    return 0


def cmd_export_all(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    total = 0

    for name, cls in sorted(all_adapters().items()):
        adapter = cls()
        sessions = adapter.discover_sessions()
        if not sessions:
            continue

        agent_dir = output_dir / name
        agent_dir.mkdir(exist_ok=True)

        for s in sessions:
            try:
                raw = adapter.read_session(s.session_id)
                normalized = adapter.normalize(raw)
                md = adapter.export_markdown(normalized)
                slug = normalized.title or s.session_id
                slug = _slugify(slug)[:80]
                out_file = agent_dir / f"{slug}.md"
                out_file.write_text(md, encoding="utf-8")
                total += 1
            except Exception as exc:
                print(f"  warning: {name}/{s.session_id}: {exc}", file=sys.stderr)

    print(f"\nexported {total} session(s) to {output_dir}", file=sys.stderr)
    return 0


# -- helpers -------------------------------------------------------------------


def _slugify(text: str) -> str:
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def _print_available() -> None:
    adapters = all_adapters()
    if adapters:
        print(f"available agents: {', '.join(sorted(adapters))}", file=sys.stderr)
    else:
        print("no adapters registered", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = ap.add_mutually_exclusive_group()
    group.add_argument("--agent", help="agent name (e.g. opencode, claude-code)")
    group.add_argument("--detect", type=Path, metavar="FILE", help="auto-detect agent from file")
    group.add_argument("--all", action="store_true", help="bulk export all agents")

    ap.add_argument("--session", help="session ID to export")
    ap.add_argument("-o", "--output", type=Path, help="output path (file or directory)")
    ap.add_argument("--list", action="store_true", dest="list_sessions", help="list available sessions")
    ap.add_argument("--agents", action="store_true", help="list available adapters")

    args = ap.parse_args()

    # List available adapters
    if args.agents:
        _print_available()
        return 0

    # List sessions
    if args.list_sessions:
        return cmd_list(args.agent)

    # Auto-detect
    if args.detect:
        if not args.detect.is_file():
            print(f"error: {args.detect} not found", file=sys.stderr)
            return 1
        return cmd_detect(args.detect, args.output)

    # Bulk export
    if args.all:
        out_dir = args.output or Path("./agent-chats")
        return cmd_export_all(out_dir)

    # Single export
    if args.agent:
        if not args.session:
            print("error: --session is required with --agent", file=sys.stderr)
            return 1
        return cmd_export(args.agent, args.session, args.output)

    # Nothing specified
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
