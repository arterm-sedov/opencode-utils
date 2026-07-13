"""Cursor adapter — VS Code AI chat sessions stored in SQLite VSCDB.

Cursor stores chat sessions in per-workspace SQLite databases:
  ~/.cursor/User/workspaceStorage/<hash>/state.vscdb

Chat data is stored as JSON blobs in ItemTable with key:
  workbench.panel.aichat.view.aichat.chatdata

Message format:
  {"role": "user"|"assistant", "message": {"content": [{"type": "text", "text": "..."}]}}

User messages may have XML wrapper:
  <attached_files>...</attached_files>
  <user_query>actual prompt</user_query>
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
    _global_db = Path("~/.cursor/User/globalStorage/state.vscdb").expanduser()
    _workspace_pattern = Path("~/.cursor/User/workspaceStorage/*/state.vscdb").expanduser()

    def discover_sessions(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []

        # Scan all workspace databases
        for db_path in sorted(self._workspace_pattern.parent.glob(self._workspace_pattern.name)):
            workspace_id = db_path.parent.name
            sessions.extend(self._scan_db(db_path, workspace_id))

        return sessions

    def _scan_db(self, db_path: Path, workspace_id: str) -> list[SessionInfo]:
        """Extract session info from a single VSCDB file."""
        if not db_path.exists():
            return []

        sessions: list[SessionInfo] = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()

            # Cursor stores chat data as JSON in ItemTable
            cur.execute(
                "SELECT value FROM ItemTable "
                "WHERE key = 'workbench.panel.aichat.view.aichat.chatdata'"
            )
            rows = cur.fetchall()
            conn.close()

            for row in rows:
                try:
                    data = json.loads(row[0])
                    if isinstance(data, dict):
                        # Single chat session
                        sessions.append(self._extract_session_info(data, db_path, workspace_id))
                    elif isinstance(data, list):
                        # Multiple chat sessions
                        for item in data:
                            if isinstance(item, dict):
                                sessions.append(self._extract_session_info(item, db_path, workspace_id))
                except (json.JSONDecodeError, KeyError):
                    continue

        except (sqlite3.Error, OSError):
            pass

        return sessions

    def _extract_session_info(self, data: dict, db_path: Path, workspace_id: str) -> SessionInfo:
        """Extract session metadata from chat data."""
        session_id = data.get("id") or data.get("chatId") or workspace_id
        title = data.get("title") or data.get("name") or ""
        return SessionInfo(
            session_id=str(session_id),
            title=title,
            agent="cursor",
            file_path=db_path,
        )

    def read_session(self, session_id: str) -> RawSession:
        """Read a session from the appropriate VSCDB database."""
        # Try global DB first
        if self._global_db.exists():
            data = self._read_from_db(self._global_db, session_id)
            if data is not None:
                return RawSession(agent="cursor", session_id=session_id, raw_data=data)

        # Search workspace databases
        for db_path in sorted(self._workspace_pattern.parent.glob(self._workspace_pattern.name)):
            data = self._read_from_db(db_path, session_id)
            if data is not None:
                return RawSession(agent="cursor", session_id=session_id, raw_data=data)

        raise RuntimeError(f"Session {session_id} not found in any Cursor database")

    def _read_from_db(self, db_path: Path, session_id: str) -> dict | None:
        """Read chat data from a single database file."""
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()

            cur.execute(
                "SELECT value FROM ItemTable "
                "WHERE key = 'workbench.panel.aichat.view.aichat.chatdata'"
            )
            rows = cur.fetchall()
            conn.close()

            for row in rows:
                try:
                    data = json.loads(row[0])
                    if isinstance(data, dict):
                        if str(data.get("id") or data.get("chatId") or "") == session_id:
                            return data
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                if str(item.get("id") or item.get("chatId") or "") == session_id:
                                    return item
                except (json.JSONDecodeError, KeyError):
                    continue

        except (sqlite3.Error, OSError):
            pass

        return None

    def normalize(self, raw: RawSession) -> NormalizedSession:
        data = raw.raw_data if isinstance(raw.raw_data, dict) else json.loads(raw.raw_data)

        # Extract metadata
        session_id = str(data.get("id") or data.get("chatId") or raw.session_id)
        title = data.get("title") or data.get("name") or ""
        model = data.get("model") or ""
        created_at = data.get("createdAt") or data.get("createdAtTime") or ""

        # Normalize messages
        messages_data = data.get("messages") or data.get("chatMessages") or []
        norm_messages = [_normalize_message(msg) for msg in messages_data]
        norm_messages = [m for m in norm_messages if m is not None]

        return NormalizedSession(
            agent="cursor",
            id=session_id,
            title=title,
            model=model,
            directory=data.get("workspace") or "",
            created_at=created_at,
            messages=norm_messages,
        )


def _normalize_message(msg: dict) -> NormalizedMessage | None:
    """Normalize a Cursor chat message."""
    role = msg.get("role", "").lower()
    if role not in ("user", "assistant"):
        return None

    content_data = msg.get("message", {}).get("content", [])

    # Handle string content (some versions)
    if isinstance(content_data, str):
        text = _clean_user_content(content_data) if role == "user" else content_data
        if not text.strip():
            return None
        return NormalizedMessage(role=role, content=text)

    # Handle array content
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
        timestamp=msg.get("timestamp"),
    )


def _clean_user_content(text: str) -> str:
    """Extract user_query from Cursor's XML wrapper, stripping attached_files."""
    # Try to extract <user_query> content
    match = re.search(r"<user_query>\s*(.*?)</user_query>", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Strip <attached_files> blocks
    cleaned = re.sub(r"<attached_files>.*?</attached_files>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<code_selection[^>]*>.*?</code_selection>", "", cleaned, flags=re.DOTALL)

    return cleaned.strip()


# Register the adapter
register(CursorAdapter)
