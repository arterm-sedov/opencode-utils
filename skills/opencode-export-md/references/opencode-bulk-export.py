#!/usr/bin/env python3
"""Bulk export all opencode sessions to organized Markdown files.

Reads the opencode SQLite database directly, groups sessions by repository,
and exports each as a dated Markdown transcript.

Usage:
    python3 opencode-bulk-export.py [--output DIR] [--converter PATH] [--repos-base PATH]

Output structure:
    <output>/<repo>/<YYYYMMDD-HHMM-<sanitized-title>.md>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_DB = "~/.local/share/opencode/opencode.db"
DEFAULT_OUTPUT = "~/repos/.agent-chats"
DEFAULT_REPOS_BASE = "~/repos"


def sanitize_filename(title: str, max_len: int = 80) -> str:
    """Make a string safe for filenames while preserving readability."""
    title = re.sub(r'[<>:"/\\|?*\[\]]', "", title)
    title = re.sub(r"\s+", "-", title.strip())
    title = re.sub(r"-+", "-", title)
    title = title.strip("-")
    if len(title) > max_len:
        title = title[:max_len].rstrip("-")
    return title or "untitled"


def get_repo_folder(directory: str | None, repos_base: str) -> str:
    """Determine repo subfolder from session directory."""
    if not directory:
        return "_other"

    d = os.path.normpath(directory)
    rb = os.path.normpath(repos_base)

    if d.startswith(rb):
        parts = d[len(rb) :].strip(os.sep).split(os.sep)
        if parts and parts[0]:
            return parts[0]
        return "_repos-root"

    home = os.path.expanduser("~")
    if d == home:
        return "_home"

    if d.startswith(home):
        home_parts = d[len(home) :].strip(os.sep).split(os.sep)
        if home_parts and home_parts[0]:
            return f"_home-{home_parts[0]}"

    return "_other"


def export_session(session_id: str, tmp_dir: str) -> str | None:
    """Export session JSON via opencode CLI using shell redirect.

    IMPORTANT: subprocess.run(capture_output=True) truncates at 128KB pipe
    buffer.  Large sessions (3MB+ JSON) must use shell redirect (>) instead.
    """
    json_path = os.path.join(tmp_dir, f"export-{session_id}.json")
    cmd = f'opencode export {session_id} > "{json_path}" 2>/dev/null'
    result = subprocess.run(cmd, shell=True, timeout=60)
    if result.returncode != 0 or not os.path.exists(json_path) or os.path.getsize(json_path) == 0:
        return None

    # Strip the "Exporting session: ..." first line if present
    with open(json_path, "r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline()

    if first_line.startswith("Exporting session:"):
        with open(json_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        content = content[len(first_line) :]
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(content)

    # Validate JSON; retry by finding first '{' if header leaked in
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            json.load(f)
        return json_path
    except json.JSONDecodeError:
        with open(json_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        idx = content.find("{")
        if idx > 0:
            content = content[idx:]
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(content)
            try:
                json.loads(content)
                return json_path
            except json.JSONDecodeError:
                pass
        return None


def convert_to_markdown(json_path: str, md_path: str, converter: str) -> bool:
    """Convert JSON to markdown using the skill converter script."""
    result = subprocess.run(
        ["python3", converter, json_path, "-o", md_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "-o", "--output", type=Path, default=Path(DEFAULT_OUTPUT),
        help=f"output root directory (default: {DEFAULT_OUTPUT})",
    )
    ap.add_argument(
        "--converter", type=Path,
        default=Path("~/.agents/skills/opencode-export-md/scripts/opencode-md.py").expanduser(),
        help="path to opencode-md.py converter script",
    )
    ap.add_argument(
        "--repos-base", type=Path, default=Path(DEFAULT_REPOS_BASE),
        help=f"base repos directory for grouping (default: {DEFAULT_REPOS_BASE})",
    )
    ap.add_argument(
        "--db", type=Path, default=Path(DEFAULT_DB).expanduser(),
        help=f"opencode SQLite database (default: {DEFAULT_DB})",
    )
    ap.add_argument(
        "--tmp-dir", type=Path, default=Path("/tmp/opencode"),
        help="temporary directory for JSON exports (default: /tmp/opencode)",
    )
    args = ap.parse_args()

    db_path = args.db.expanduser()
    output_root = args.output.expanduser()
    repos_base = str(args.repos_base.expanduser())
    converter = str(args.converter.expanduser())
    tmp_dir = str(args.tmp_dir.expanduser())

    os.makedirs(tmp_dir, exist_ok=True)

    if not db_path.exists():
        print(f"Error: database not found at {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, directory, time_created, time_updated "
        "FROM session ORDER BY time_created ASC"
    )
    sessions = cur.fetchall()
    conn.close()

    print(f"Found {len(sessions)} sessions to export")

    # Group by repo folder
    by_repo: dict[str, list[dict]] = {}
    for session_id, title, directory, time_created, time_updated in sessions:
        repo = get_repo_folder(directory, repos_base)
        by_repo.setdefault(repo, []).append({
            "id": session_id,
            "title": title or "untitled",
            "directory": directory,
            "time_created": time_created,
            "time_updated": time_updated,
        })

    print(f"Distribution across {len(by_repo)} repos:")
    for repo, items in sorted(by_repo.items()):
        print(f"  {repo}: {len(items)} sessions")

    # Create directories
    for repo in by_repo:
        os.makedirs(os.path.join(str(output_root), repo), exist_ok=True)

    # Export each session
    success = 0
    failed = 0
    for repo, items in by_repo.items():
        for item in items:
            session_id = item["id"]
            title = item["title"]
            time_ms = item["time_created"]

            dt = datetime.fromtimestamp(time_ms / 1000)
            date_prefix = dt.strftime("%Y%m%d-%H%M")

            safe_title = sanitize_filename(title)
            filename = f"{date_prefix}-{safe_title}.md"
            md_path = os.path.join(str(output_root), repo, filename)

            # Skip if already exists and non-trivial
            if os.path.exists(md_path) and os.path.getsize(md_path) > 100:
                print(f"  SKIP (exists): {repo}/{filename}")
                success += 1
                continue

            print(f"  Exporting: {repo}/{filename}...", end=" ", flush=True)
            json_path = export_session(session_id, tmp_dir)
            if not json_path:
                print("FAIL (export)")
                failed += 1
                continue

            if convert_to_markdown(json_path, md_path, converter):
                size = os.path.getsize(md_path)
                print(f"OK ({size:,} bytes)")
                success += 1
            else:
                print("FAIL (convert)")
                failed += 1

            try:
                os.remove(json_path)
            except OSError:
                pass

    print(f"\nDone: {success} exported, {failed} failed")
    print(f"Output: {output_root}/")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
