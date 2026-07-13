"""Claude Code adapter — reads ~/.claude/projects/**/*.jsonl sessions."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import register
from .base import (
    AgentAdapter,
    NormalizedMessage,
    NormalizedSession,
    Patch,
    RawSession,
    SessionInfo,
    ToolCall,
)

_CLAUDE_DIR = Path.home() / ".claude" / "projects"


class ClaudeCodeAdapter(AgentAdapter):
    name = "claude-code"

    # ── discovery ────────────────────────────────────────────

    def discover_sessions(self) -> list[SessionInfo]:
        if not _CLAUDE_DIR.is_dir():
            return []

        sessions: list[SessionInfo] = []
        for jsonl in _CLAUDE_DIR.rglob("*.jsonl"):
            sid = jsonl.stem
            title = self._peek_title(jsonl)
            sessions.append(
                SessionInfo(
                    session_id=sid,
                    title=title,
                    agent=self.name,
                    file_path=jsonl,
                )
            )
        # most-recent first
        sessions.sort(key=lambda s: s.file_path.stat().st_mtime, reverse=True)
        return sessions

    def _peek_title(self, path: Path) -> str:
        """Scan the first few lines for an ai-title event."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for _ in range(50):
                    line = fh.readline()
                    if not line:
                        break
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "ai-title" and obj.get("aiTitle"):
                            return obj["aiTitle"]
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError:
            pass
        return ""

    # ── read raw ─────────────────────────────────────────────

    def read_session(self, session_id: str) -> RawSession:
        # If session_id is already a full path, use it directly
        p = Path(session_id)
        if p.is_file() and p.suffix == ".jsonl":
            jsonl_path = p
        else:
            matches = list(_CLAUDE_DIR.rglob(f"{session_id}.jsonl"))
            if not matches:
                raise FileNotFoundError(
                    f"No Claude Code session found matching '{session_id}'"
                )
            jsonl_path = matches[0]

        events = []
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue

        return RawSession(
            agent=self.name,
            session_id=jsonl_path.stem,
            raw_data={"events": events, "path": str(jsonl_path)},
        )

    # ── normalize ────────────────────────────────────────────

    def normalize(self, raw: RawSession) -> NormalizedSession:
        events = raw.raw_data["events"]
        jsonl_path = Path(raw.raw_data["path"])

        # Sort by timestamp if present (some events may lack it)
        events.sort(key=lambda e: e.get("timestamp", ""))

        title = ""
        model = ""
        messages: list[NormalizedMessage] = []

        for ev in events:
            ev_type = ev.get("type")

            # ── AI title ──
            if ev_type == "ai-title" and ev.get("aiTitle"):
                title = ev["aiTitle"]
                continue

            # ── User message ──
            if ev_type == "user" and isinstance(ev.get("message"), dict):
                msg = ev["message"]
                if msg.get("role") != "user":
                    continue

                # Tool results are user messages with the toolUseResult flag
                if ev.get("toolUseResult"):
                    tool_result = self._extract_tool_result(msg)
                    if tool_result:
                        messages.append(
                            NormalizedMessage(
                                role="user",
                                content=tool_result,
                                timestamp=ev.get("timestamp"),
                            )
                        )
                    continue

                content = msg.get("content", "")
                text = self._extract_text(content)
                # Skip interruption markers
                if text.startswith("[Request interrupted"):
                    continue
                if not text.strip():
                    continue

                messages.append(
                    NormalizedMessage(
                        role="user",
                        content=text,
                        timestamp=ev.get("timestamp"),
                    )
                )

            # ── Assistant message ──
            elif ev_type == "assistant" and isinstance(ev.get("message"), dict):
                msg = ev["message"]
                if msg.get("role") != "assistant":
                    continue

                if not model and msg.get("model"):
                    model = msg["model"]

                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue

                text_parts: list[str] = []
                reasoning_parts: list[str] = []
                tool_calls: list[ToolCall] = []

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")

                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "thinking":
                        thinking = block.get("thinking", "")
                        if thinking:
                            reasoning_parts.append(thinking)
                    elif btype == "tool_use":
                        tool_calls.append(
                            ToolCall(
                                name=block.get("name", "unknown"),
                                input=block.get("input", {}),
                                metadata={"id": block.get("id", "")},
                            )
                        )

                content_str = "\n\n".join(text_parts)
                reasoning_str = "\n\n".join(reasoning_parts) if reasoning_parts else None

                if not content_str.strip() and not tool_calls and not reasoning_str:
                    continue

                messages.append(
                    NormalizedMessage(
                        role="assistant",
                        content=content_str,
                        reasoning=reasoning_str,
                        tool_calls=tool_calls,
                        timestamp=ev.get("timestamp"),
                    )
                )

            # ── Thinking block (standalone, not inside assistant) ──
            elif ev_type == "thinking":
                thinking = ev.get("thinking", "")
                if thinking.strip():
                    # Attach to last assistant message if possible, else new message
                    if messages and messages[-1].role == "assistant":
                        existing = messages[-1].reasoning or ""
                        messages[-1].reasoning = (existing + "\n\n" + thinking).strip()
                    else:
                        messages.append(
                            NormalizedMessage(
                                role="assistant",
                                reasoning=thinking,
                                timestamp=ev.get("timestamp"),
                            )
                        )

        # Derive title from file path if none found
        if not title:
            # ~/.claude/projects/<project-slug>/<session-id>.jsonl
            project_dir = jsonl_path.parent.name
            title = project_dir.replace("-", " ").strip().title() or raw.session_id

        return NormalizedSession(
            agent=self.name,
            id=raw.session_id,
            title=title,
            model=model,
            directory=str(jsonl_path.parent),
            created_at=events[0].get("timestamp", "") if events else "",
            messages=messages,
        )

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _extract_text(content: str | list) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "\n".join(parts)
        return str(content) if content else ""

    @staticmethod
    def _extract_tool_result(msg: dict) -> str:
        content = msg.get("content", [])
        if not isinstance(content, list):
            return ""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, str):
                    return result_content
                if isinstance(result_content, list):
                    parts = []
                    for item in result_content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            parts.append(item.get("text", ""))
                    return "\n".join(parts)
                return str(result_content) if result_content else ""
        return ""


register(ClaudeCodeAdapter)
