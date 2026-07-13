"""Aider adapter — reads .aider.chat.history.md Markdown sessions."""

from __future__ import annotations

from pathlib import Path

from . import register
from .base import (
    AgentAdapter,
    NormalizedMessage,
    NormalizedSession,
    RawSession,
    SessionInfo,
)


class AiderAdapter(AgentAdapter):
    name = "aider"

    # ── discovery ────────────────────────────────────────────

    def discover_sessions(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []
        cwd = Path.cwd()

        for md in cwd.rglob("*.aider.chat.history.md"):
            sid = md.stem  # e.g. "aider.chat.history"
            title = self._peek_title(md)
            sessions.append(
                SessionInfo(
                    session_id=sid,
                    title=title,
                    agent=self.name,
                    file_path=md,
                )
            )

        sessions.sort(key=lambda s: s.file_path.stat().st_mtime, reverse=True)
        return sessions

    def _peek_title(self, path: Path) -> str:
        """Read the first line for a '# ...' header."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if line.startswith("# "):
                        return line[2:].strip()
                    if line.strip():
                        break
        except OSError:
            pass
        return ""

    # ── read raw ─────────────────────────────────────────────

    def read_session(self, session_id: str) -> RawSession:
        p = Path(session_id)
        if p.is_file() and p.suffix == ".md":
            md_path = p
        else:
            # Match by stem (filename without .md)
            candidates = [
                f for f in Path.cwd().rglob("*.aider.chat.history.md")
                if f.stem == session_id or session_id in f.stem
            ]
            if not candidates:
                raise FileNotFoundError(
                    f"No Aider session found matching '{session_id}'"
                )
            md_path = candidates[0]

        text = md_path.read_text(encoding="utf-8", errors="replace")
        return RawSession(
            agent=self.name,
            session_id=md_path.stem,
            raw_data={"text": text, "path": str(md_path)},
        )

    # ── normalize ────────────────────────────────────────────

    def normalize(self, raw: RawSession) -> NormalizedSession:
        text: str = raw.raw_data["text"]
        md_path = Path(raw.raw_data["path"])
        lines = text.split("\n")

        messages = self._parse_lines(lines)

        # Derive title from first header
        title = ""
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break

        if not title:
            title = md_path.parent.name.replace("-", " ").strip().title() or raw.session_id

        # Build normalized messages
        norm_msgs: list[NormalizedMessage] = []
        for role, content in messages:
            content = content.strip()
            if not content:
                continue
            # Skip command-only lines like /exit, /clear, /model
            if role == "user" and content.startswith("/"):
                continue
            norm_msgs.append(NormalizedMessage(role=role, content=content))

        return NormalizedSession(
            agent=self.name,
            id=raw.session_id,
            title=title,
            directory=str(md_path.parent),
            messages=norm_msgs,
        )

    def _parse_lines(self, lines: list[str]) -> list[tuple[str, str]]:
        """State machine matching aider/utils.py split_chat_history_markdown.

        Returns list of (role, content) pairs.
        Roles: 'user' (#### lines), 'assistant' (plain lines), 'tool' (> lines).
        """
        user: list[str] = []
        assistant: list[str] = []
        tool: list[str] = []
        messages: list[tuple[str, str]] = []

        def flush(role: str, buf: list[str]) -> None:
            content = "\n".join(buf).strip()
            if content:
                messages.append((role, content))
            buf.clear()

        for line in lines:
            if line.startswith("# "):
                # Header line — skip
                continue

            if line.startswith("> "):
                # Tool/context output
                flush("assistant", assistant)
                flush("user", user)
                tool.append(line[2:])
                continue

            if line.startswith("#### "):
                # User message
                flush("assistant", assistant)
                flush("tool", tool)
                user.append(line[5:])
                continue

            # Regular line — belongs to assistant
            flush("user", user)
            flush("tool", tool)
            assistant.append(line)

        # Flush remaining
        flush("assistant", assistant)
        flush("user", user)
        flush("tool", tool)

        return messages


register(AiderAdapter)
