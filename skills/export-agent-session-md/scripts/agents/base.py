"""Abstract adapter base and common data models for agent export."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .sanitizer import sanitize


@dataclass
class SessionInfo:
    """Lightweight session metadata for listing/discovery."""
    session_id: str
    title: str
    agent: str
    file_path: Path


@dataclass
class RawSession:
    """Unparsed session data as read from disk."""
    agent: str
    session_id: str
    raw_data: Any


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Patch:
    files: list[str] = field(default_factory=list)
    hash: str = ""
    diff: str = ""


@dataclass
class NormalizedMessage:
    role: str  # "user" | "assistant"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning: str | None = None
    patches: list[Patch] = field(default_factory=list)
    timestamp: str | None = None


@dataclass
class NormalizedSession:
    agent: str
    id: str
    title: str
    model: str = ""
    directory: str = ""
    created_at: str = ""
    messages: list[NormalizedMessage] = field(default_factory=list)


class AgentAdapter(ABC):
    """Base class all agent adapters must implement."""

    name: str
    session_dirs: list[Path] = []

    @abstractmethod
    def discover_sessions(self) -> list[SessionInfo]:
        """Find all sessions on this machine."""

    @abstractmethod
    def read_session(self, session_id: str) -> RawSession:
        """Read a session's raw data."""

    @abstractmethod
    def normalize(self, raw: RawSession) -> NormalizedSession:
        """Convert raw session data to the common format."""

    def export_markdown(self, session: NormalizedSession) -> str:
        """Render a normalized session to Markdown (shared implementation).

        Automatically sanitizes secrets and adds a warning if any were found.
        """
        out: list[str] = []
        title = session.title or f"{session.agent} session"
        out.append(f"# {title}")
        out.append("")
        out.append(f"- **Session:** `{session.id}`")
        out.append(f"- **Agent:** `{session.agent}`")
        if session.model:
            out.append(f"- **Model:** `{session.model}`")
        if session.directory:
            out.append(f"- **Directory:** `{session.directory}`")
        if session.created_at:
            out.append(f"- **Created:** {session.created_at}")

        # Sanitize the full output
        full_text = "\n".join(out)
        result = sanitize(full_text)

        if result.sanitized:
            out.append("")
            out.append(f"⚠️ **Sanitized:** {', '.join(result.replacements)}")

        out.append("")

        for msg in session.messages:
            block = self._message_to_md(msg)
            if block:
                out.append(block)

        # Sanitize the complete output
        final = "\n".join(out)
        final_result = sanitize(final)

        if final_result.sanitized:
            # Prepend warning after title
            lines = final_result.content.split("\n")
            # Find the first empty line after title and insert warning
            for i, line in enumerate(lines):
                if line.startswith("# ") and i + 1 < len(lines):
                    lines.insert(i + 2, "")
                    lines.insert(i + 3, f"> ⚠️ **Sanitized:** {', '.join(final_result.replacements)}")
                    break
            return "\n".join(lines)

        return final_result.content

    def _message_to_md(self, msg: NormalizedMessage) -> str:
        role_labels = {"user": "User", "assistant": "Assistant"}
        label = role_labels.get(msg.role, msg.role.title())

        body_parts: list[str] = []

        if msg.content:
            body_parts.append(msg.content.rstrip())

        if msg.reasoning:
            body_parts.append(f"**Reasoning:**\n```\n{msg.reasoning.rstrip()}\n```")

        for tc in msg.tool_calls:
            body_parts.append(self._tool_call_to_md(tc))

        for p in msg.patches:
            body_parts.append(self._patch_to_md(p))

        body = "\n\n".join(body_parts)
        if not body:
            return ""
        return f"## {label}\n\n{body}\n"

    @staticmethod
    def _tool_call_to_md(tc: ToolCall) -> str:
        head = f"**Tool:** `{tc.name}`"
        if tc.metadata.get("title"):
            head += f" -- *{tc.metadata['title']}*"
        parts = [head]
        if tc.input:
            parts.append("```json")
            try:
                parts.append(json.dumps(tc.input, ensure_ascii=False, indent=2))
            except TypeError:
                parts.append(str(tc.input))
            parts.append("```")
        if tc.output:
            out_s = tc.output if isinstance(tc.output, str) else str(tc.output)
            parts.append("```\n" + out_s[:4000] + "\n```")
        return "\n".join(parts)

    @staticmethod
    def _patch_to_md(p: Patch) -> str:
        head = f"**Patch** -- *{len(p.files)} file(s)*"
        if p.hash:
            head += f" -- `{p.hash}`"
        parts = [head]
        for f in p.files[:8]:
            parts.append("```diff")
            parts.append(f[:4000])
            parts.append("```")
        if len(p.files) > 8:
            parts.append(f"_(... {len(p.files) - 8} more file(s) truncated)_")
        return "\n".join(parts)
