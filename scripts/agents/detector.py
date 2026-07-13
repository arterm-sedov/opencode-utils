"""Auto-detection: sniff a file's content to identify which agent produced it.

Ported from artificial-investigator/parser.js detection rules.
"""

from __future__ import annotations

import json
from pathlib import Path


def detect_agent(file_path: Path) -> str | None:
    """Return the agent name if the file's content can be identified, else None."""
    path = Path(file_path)

    if not path.is_file():
        return None

    # Fast path: path-based hints
    name_lower = path.name.lower()
    parent_parts = [p.lower() for p in path.parts]

    if "opencode" in parent_parts or "mimocode" in parent_parts:
        return "opencode"
    if ".claude" in parent_parts and name_lower.endswith(".jsonl"):
        return "claude-code"
    if ".codex" in parent_parts and name_lower.endswith(".jsonl"):
        return "codex"
    if ".continue" in parent_parts and name_lower.endswith(".jsonl"):
        return "continue"
    if "cursor" in parent_parts and name_lower.endswith(".vscdb"):
        return "cursor"
    if name_lower.endswith(".aider.chat.history.md"):
        return "aider"
    if ".cline" in parent_parts or ".roo" in parent_parts:
        return "cline"

    # Content sniffing
    try:
        head = _read_head(path)
    except Exception:
        return None

    if not head.strip():
        return None

    # Try JSON parse
    try:
        data = json.loads(head)
        return _detect_json(data, head)
    except (json.JSONDecodeError, ValueError):
        pass

    # Try JSONL (line-by-line JSON)
    first_line = head.split("\n", 1)[0].strip()
    try:
        first_obj = json.loads(first_line)
        return _detect_jsonl(first_obj, first_line)
    except (json.JSONDecodeError, ValueError):
        pass

    # Markdown heuristic: aider uses #### for prompts
    if "#### " in head:
        return "aider"

    return None


def detect_agent_from_string(content: str) -> str | None:
    """Detect agent from a raw string (for piped/stdin input)."""
    head = content[:8192]
    if not head.strip():
        return None

    try:
        data = json.loads(head)
        return _detect_json(data, head)
    except (json.JSONDecodeError, ValueError):
        pass

    first_line = head.split("\n", 1)[0].strip()
    try:
        first_obj = json.loads(first_line)
        return _detect_jsonl(first_obj, first_line)
    except (json.JSONDecodeError, ValueError):
        pass

    if "#### " in head:
        return "aider"

    return None


# -- internal helpers ---------------------------------------------------------


def _read_head(path: Path, nbytes: int = 8192) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read(nbytes)


def _detect_json(data: object, raw_head: str) -> str | None:
    """Classify a top-level JSON value."""

    # OpenCode / MiMoCode: JSON object with "info" and "messages" keys
    if isinstance(data, dict):
        if "info" in data and "messages" in data:
            return "opencode"

        # Single-object JSON can also match JSONL patterns
        return _detect_jsonl(data, raw_head)

    # ChatGPT: JSON array with "mapping" key inside items
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and "mapping" in first:
            return "chatgpt"

    return None


def _detect_jsonl(first_obj: dict, raw_line: str) -> str | None:
    """Classify the first object of a JSONL stream."""

    # Continue.dev: has "eventName" key
    if "eventName" in first_obj:
        return "continue"

    # Claude Code: has "type" in {user, assistant, system}
    msg_type = first_obj.get("type")
    if msg_type in ("user", "assistant", "system"):
        return "claude-code"

    # Cursor: has "role" and nested "message" with "content"
    if "role" in first_obj and "message" in first_obj:
        return "cursor"

    # Codex: has "type" == "session_meta" or has "session" + "events"
    if first_obj.get("type") == "session_meta" or "session" in first_obj:
        return "codex"

    # OpenCode: has "info" and "messages" as top-level keys in the JSONL line
    if "info" in first_obj and "messages" in first_obj:
        return "opencode"

    return None
