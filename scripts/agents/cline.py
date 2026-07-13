"""Cline / Roo Code adapter — reads sessions from SQLite database."""

from __future__ import annotations

import json
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

# ---------------------------------------------------------------------------
# Storage locations (checked in order)
# ---------------------------------------------------------------------------

_CLINE_HOME = Path.home() / ".cline"
_ROO_HOME = Path.home() / ".roo"

_SESSION_DB_CANDIDATES = [
    _CLINE_HOME / "data" / "sessions" / "sessions.db",
    _CLINE_HOME / "data" / "sessions.db",
    _CLINE_HOME / "sessions.db",
    _ROO_HOME / "data" / "sessions" / "sessions.db",
    _ROO_HOME / "data" / "sessions.db",
    _ROO_HOME / "sessions.db",
]


def _find_db() -> Path | None:
    for p in _SESSION_DB_CANDIDATES:
        if p.is_file():
            return p
    return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ClineAdapter(AgentAdapter):
    name = "cline"
    session_dirs = [_CLINE_HOME / "data" / "sessions", _ROO_HOME / "data" / "sessions"]

    # -- discovery -------------------------------------------------------------

    def discover_sessions(self) -> list[SessionInfo]:
        db = _find_db()
        if db is not None:
            return self._discover_from_sqlite(db)
        return self._discover_from_files()

    def _discover_from_sqlite(self, db: Path) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            # Try the most likely table/column names
            for table, cols in _TABLE_CANDIDATES:
                try:
                    cur.execute(f"SELECT {cols} FROM {table} ORDER BY rowid DESC")
                    for row in cur.fetchall():
                        sessions.append(
                            SessionInfo(
                                session_id=str(row["session_id"]),
                                title=str(row["title"] or ""),
                                agent="cline",
                                file_path=db,
                            )
                        )
                    break
                except sqlite3.OperationalError:
                    continue
            conn.close()
        except Exception:
            pass
        return sessions

    def _discover_from_files(self) -> list[SessionInfo]:
        """Fallback: glob for .json conversation files."""
        sessions: list[SessionInfo] = []
        for base in (_CLINE_HOME, _ROO_HOME):
            if not base.is_dir():
                continue
            # Check for JSON conversation exports
            for p in base.rglob("*.json"):
                if "session" in p.name.lower() or "conversation" in p.name.lower():
                    sessions.append(
                        SessionInfo(
                            session_id=p.stem,
                            title=p.stem,
                            agent="cline",
                            file_path=p,
                        )
                    )
        return sessions

    # -- read ------------------------------------------------------------------

    def read_session(self, session_id: str) -> RawSession:
        db = _find_db()
        if db is not None:
            return self._read_from_sqlite(db, session_id)
        return self._read_from_file(session_id)

    def _read_from_sqlite(self, db: Path, session_id: str) -> RawSession:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Read session record
        session_data: dict[str, Any] = {}
        messages: list[dict[str, Any]] = []

        for table, _ in _TABLE_CANDIDATES:
            try:
                cur.execute(f"SELECT * FROM {table} WHERE session_id = ?", (session_id,))
                row = cur.fetchone()
                if row is not None:
                    session_data = dict(row)
                    break
            except sqlite3.OperationalError:
                continue

        # Read messages — try dedicated messages table, then inline content
        for msg_table, msg_cols in _MESSAGE_TABLE_CANDIDATES:
            try:
                cur.execute(
                    f"SELECT {msg_cols} FROM {msg_table} WHERE session_id = ? ORDER BY rowid",
                    (session_id,),
                )
                for row in cur.fetchall():
                    messages.append(dict(row))
                break
            except sqlite3.OperationalError:
                continue

        # If no dedicated message table, try to parse messages from JSON column
        if not messages:
            for key in ("messages", "conversation", "content", "data"):
                val = session_data.get(key)
                if isinstance(val, str):
                    try:
                        parsed = json.loads(val)
                        if isinstance(parsed, list):
                            messages = parsed
                    except (json.JSONDecodeError, TypeError):
                        pass
                elif isinstance(parsed := val, list):
                    messages = parsed

        conn.close()

        return RawSession(
            agent="cline",
            session_id=session_id,
            raw_data={"session": session_data, "messages": messages},
        )

    def _read_from_file(self, session_id: str) -> RawSession:
        """Fallback: read a JSON conversation file."""
        for base in (_CLINE_HOME, _ROO_HOME):
            for p in base.rglob("*.json"):
                if p.stem == session_id or session_id in str(p):
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return RawSession(
                        agent="cline",
                        session_id=session_id,
                        raw_data=data,
                    )
        raise FileNotFoundError(f"Cline session not found: {session_id}")

    # -- normalize -------------------------------------------------------------

    def normalize(self, raw: RawSession) -> NormalizedSession:
        data = raw.raw_data

        # Extract session metadata
        session = data.get("session", {}) if isinstance(data, dict) else {}
        title = (
            session.get("title")
            or session.get("name")
            or ""
        )
        model = ""
        metadata = session.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        model = metadata.get("model", "")
        created = session.get("createdAt") or session.get("created_at") or ""

        # Extract messages
        raw_messages = data.get("messages", []) if isinstance(data, dict) else []
        messages = self._normalize_messages(raw_messages)

        return NormalizedSession(
            agent="cline",
            id=raw.session_id,
            title=title,
            model=model,
            directory=session.get("cwd", ""),
            created_at=created,
            messages=messages,
        )

    def _normalize_messages(self, raw_messages: list[dict]) -> list[NormalizedMessage]:
        normalized: list[NormalizedMessage] = []

        for msg in raw_messages:
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue

            content_raw = msg.get("content", "")
            content = ""
            tool_calls: list[ToolCall] = []
            reasoning: str | None = None

            if isinstance(content_raw, str):
                content = content_raw
            elif isinstance(content_raw, list):
                text_parts: list[str] = []
                for block in content_raw:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "tool_use":
                        tool_calls.append(
                            ToolCall(
                                name=block.get("name", "unknown"),
                                input=block.get("input", {}),
                            )
                        )
                    elif btype == "tool_result":
                        # Attach result to the last matching tool call or as content
                        result_text = block.get("content", "")
                        if isinstance(result_text, list):
                            result_text = "\n".join(
                                b.get("text", "") for b in result_text if isinstance(b, dict)
                            )
                        if tool_calls:
                            tool_calls[-1].output = str(result_text)
                        else:
                            text_parts.append(str(result_text))
                    elif btype == "reasoning":
                        reasoning = block.get("text", "")
                content = "\n".join(text_parts)

            # Some Cline exports store reasoning as a top-level field
            if not reasoning and msg.get("reasoning"):
                reasoning = msg["reasoning"]

            # Model info
            model_info = msg.get("modelInfo", {})
            if not content and not tool_calls and not reasoning:
                continue

            normalized.append(
                NormalizedMessage(
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                    reasoning=reasoning,
                    timestamp=str(msg.get("timestamp", "")) or None,
                )
            )

        return normalized


# -- table discovery heuristics -----------------------------------------------

# (table_name, columns_sql) — tried in order until one works
_TABLE_CANDIDATES = [
    ("sessions", "session_id, title, createdAt, updatedAt, metadata"),
    ("session", "session_id, title, createdAt, updatedAt, metadata"),
    ("conversations", "session_id, title, createdAt, updatedAt, metadata"),
]

_MESSAGE_TABLE_CANDIDATES = [
    ("messages", "session_id, role, content, timestamp"),
    ("message", "session_id, role, content, timestamp"),
    ("conversation_messages", "session_id, role, content, timestamp"),
]

# -- auto-register -----------------------------------------------------------

register(ClineAdapter)
