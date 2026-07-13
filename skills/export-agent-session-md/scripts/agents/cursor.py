"""Cursor adapter — AI chat sessions stored in SQLite.

Cursor stores chat sessions in:
  ~/.cursor/chats/<hash>/<session-uuid>/

Each session directory contains:
  - meta.json: {"createdAtMs": ..., "updatedAtMs": ..., "hasConversation": ...}
  - store.db: SQLite with blobs table (messages) and meta table (session name)
  - prompt_history.json: Prompt history (optional)

Session name from store.db meta table (hex-encoded JSON):
  {"name": "Session Title", "agentId": "...", ...}

Message format in store.db blobs table:
  {"role": "user"|"assistant", "content": "text"|"[{...}]"}

Some sessions only have meta.json + prompt_history.json (no store.db).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from . import register
from .base import (
    AgentAdapter,
    NormalizedMessage,
    NormalizedSession,
    RawSession,
    SessionInfo,
    ToolCall,
)


class CursorAdapter(AgentAdapter):
    name = "cursor"
    _chats_base = Path("~/.cursor/chats").expanduser()

    def discover_sessions(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []

        if not self._chats_base.exists():
            return sessions

        # Find all session directories (UUID-named subdirs under hash dirs)
        for hash_dir in sorted(self._chats_base.iterdir()):
            if not hash_dir.is_dir():
                continue
            for session_dir in sorted(hash_dir.iterdir()):
                if not session_dir.is_dir():
                    continue
                session_info = self._read_session_info(session_dir)
                if session_info:
                    sessions.append(session_info)

        return sessions

    def _read_session_info(self, session_dir: Path) -> SessionInfo | None:
        """Read session metadata from directory."""
        session_uuid = session_dir.name
        store_db = session_dir / "store.db"
        meta_json = session_dir / "meta.json"

        name = "unknown"
        has_store = store_db.exists()

        # Try to get name from store.db meta table
        if has_store:
            try:
                conn = sqlite3.connect(f"file:{store_db}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute('SELECT value FROM meta WHERE key = "0"')
                row = cur.fetchone()
                conn.close()

                if row:
                    decoded = bytes.fromhex(row[0]).decode("utf-8")
                    data = json.loads(decoded)
                    name = data.get("name", "unknown")
            except Exception:
                pass

        return SessionInfo(
            session_id=session_uuid,
            title=name,
            agent="cursor",
            file_path=session_dir,
        )

    def read_session(self, session_id: str) -> RawSession:
        """Read a session from its directory."""
        # Find the session directory
        for hash_dir in self._chats_base.iterdir():
            if not hash_dir.is_dir():
                continue
            session_dir = hash_dir / session_id
            if session_dir.exists():
                messages = self._read_messages(session_dir)
                info = self._read_session_info(session_dir)
                return RawSession(
                    agent="cursor",
                    session_id=session_id,
                    raw_data={
                        "id": session_id,
                        "name": info.title if info else "unknown",
                        "messages": messages,
                    },
                )

        raise RuntimeError(f"Session {session_id} not found in Cursor chats")

    def _read_messages(self, session_dir: Path) -> list[dict]:
        """Read messages from store.db or prompt_history.json."""
        messages: list[dict] = []

        store_db = session_dir / "store.db"
        if store_db.exists():
            messages = self._read_from_store_db(store_db)

        # Fallback to prompt_history.json if no store.db or empty
        if not messages:
            prompt_file = session_dir / "prompt_history.json"
            if prompt_file.exists():
                messages = self._read_from_prompt_history(prompt_file)

        return messages

    def _read_from_store_db(self, db_path: Path) -> list[dict]:
        """Read messages from store.db blobs table."""
        messages: list[dict] = []

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT data FROM blobs")
            for row in cur.fetchall():
                data = row[0]
                if isinstance(data, bytes):
                    try:
                        data = data.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                try:
                    parsed = json.loads(data)
                    if isinstance(parsed, dict) and "role" in parsed:
                        messages.append(parsed)
                except (json.JSONDecodeError, TypeError):
                    continue
            conn.close()
        except (sqlite3.Error, OSError):
            pass

        return messages

    def _read_from_prompt_history(self, prompt_file: Path) -> list[dict]:
        """Read messages from prompt_history.json."""
        messages: list[dict] = []

        try:
            data = json.loads(prompt_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        # prompt_history entries are typically just prompts
                        text = item.get("prompt") or item.get("text") or ""
                        if text.strip():
                            messages.append({"role": "user", "content": text})
        except (json.JSONDecodeError, OSError):
            pass

        return messages

    def normalize(self, raw: RawSession) -> NormalizedSession:
        data = raw.raw_data if isinstance(raw.raw_data, dict) else {}

        session_id = data.get("id", raw.session_id)
        title = data.get("name", "unknown")
        messages_data = data.get("messages", [])

        norm_messages = [_normalize_message(msg) for msg in messages_data]
        norm_messages = [m for m in norm_messages if m is not None]

        return NormalizedSession(
            agent="cursor",
            id=session_id,
            title=title,
            model="",
            directory="",
            created_at="",
            messages=norm_messages,
        )


def _normalize_message(msg: dict) -> NormalizedMessage | None:
    """Normalize a Cursor chat message."""
    role = msg.get("role", "").lower()
    if role not in ("user", "assistant"):
        return None

    content_data = msg.get("content", "")

    # Handle string content
    if isinstance(content_data, str):
        text = _clean_user_content(content_data) if role == "user" else content_data
        if not text.strip():
            return None
        return NormalizedMessage(role=role, content=text)

    # Handle array content (content blocks)
    if not isinstance(content_data, list):
        return None

    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in content_data:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type", "")

        if block_type == "text":
            text = block.get("text", "")
            if role == "user":
                text = _clean_user_content(text)
            if text.strip():
                content_parts.append(text)

        elif block_type == "tool_use":
            tc = ToolCall(
                name=block.get("name", "tool"),
                input=block.get("input", {}),
                output=block.get("output", ""),
            )
            tool_calls.append(tc)

    content = "\n\n".join(content_parts)
    if not content.strip() and not tool_calls:
        return None

    return NormalizedMessage(
        role=role,
        content=content,
        tool_calls=tool_calls,
    )


def _clean_user_content(text: str) -> str:
    """Extract user_query from Cursor's XML wrapper, stripping attached_files."""
    match = re.search(r"<user_query>\s*(.*?)</user_query>", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    cleaned = re.sub(r"<attached_files>.*?</attached_files>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<code_selection[^>]*>.*?</code_selection>", "", cleaned, flags=re.DOTALL)

    return cleaned.strip()


# Register the adapter
register(CursorAdapter)
