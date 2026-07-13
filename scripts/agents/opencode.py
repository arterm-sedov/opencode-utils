"""OpenCode / MiMoCode adapter — shared message schema, separate DBs.

OpenCode: queries ~/.local/share/opencode/opencode.db, exports via `opencode export` CLI.
MiMoCode: queries ~/.local/share/mimocode/mimocode.db, reads message/part tables directly.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
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


class OpenCodeAdapter(AgentAdapter):
    name = "opencode"
    _db_path = Path("~/.local/share/opencode/opencode.db").expanduser()

    def discover_sessions(self) -> list[SessionInfo]:
        if not self._db_path.exists():
            return []
        sessions: list[SessionInfo] = []
        conn = sqlite3.connect(str(self._db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, directory, time_created "
            "FROM session ORDER BY time_created DESC LIMIT 500"
        )
        for row in cur.fetchall():
            sid, title, directory, ts = row
            sessions.append(
                SessionInfo(
                    session_id=sid,
                    title=title or "",
                    agent="opencode",
                    file_path=self._db_path,
                )
            )
        conn.close()
        return sessions

    def read_session(self, session_id: str) -> RawSession:
        """Export via `opencode export` CLI using shell redirect (avoids 128KB pipe)."""
        with tempfile.TemporaryDirectory(prefix="agent-export-") as tmp_dir:
            json_path = os.path.join(tmp_dir, f"export-{session_id}.json")
            cmd = f'opencode export {session_id} > "{json_path}" 2>/dev/null'
            result = subprocess.run(cmd, shell=True, timeout=60)
            if result.returncode != 0 or not os.path.exists(json_path) or os.path.getsize(json_path) == 0:
                raise RuntimeError(f"Failed to export session {session_id}")

            with open(json_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Strip "Exporting session: ..." header line
            if content.startswith("Exporting session:"):
                content = content.split("\n", 1)[1]

            # Try to find JSON start if header leaked
            try:
                json.loads(content)
            except json.JSONDecodeError:
                idx = content.find("{")
                if idx > 0:
                    content = content[idx:]
                    json.loads(content)
                else:
                    raise RuntimeError(f"Invalid JSON for session {session_id}")

        return RawSession(agent="opencode", session_id=session_id, raw_data=content)

    def normalize(self, raw: RawSession) -> NormalizedSession:
        data = json.loads(raw.raw_data)
        info = data.get("info", {})
        messages = data.get("messages", [])

        model_info = info.get("model", {})
        model_name = model_info.get("id", "") if isinstance(model_info, dict) else str(model_info)

        time_info = info.get("time", {})
        created_ms = time_info.get("created") if isinstance(time_info, dict) else None
        created_at = ""
        if created_ms:
            created_at = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()

        norm_messages = [_normalize_message(msg) for msg in messages]
        norm_messages = [m for m in norm_messages if m is not None]

        return NormalizedSession(
            agent=raw.agent,
            id=raw.session_id,
            title=info.get("title", ""),
            model=model_name,
            directory=info.get("directory", ""),
            created_at=created_at,
            messages=norm_messages,
        )


class MiMoCodeAdapter(AgentAdapter):
    name = "mimocode"
    _db_path = Path("~/.local/share/mimocode/mimocode.db").expanduser()

    def discover_sessions(self) -> list[SessionInfo]:
        if not self._db_path.exists():
            return []
        sessions: list[SessionInfo] = []
        conn = sqlite3.connect(str(self._db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, directory, time_created "
            "FROM session ORDER BY time_created DESC LIMIT 500"
        )
        for row in cur.fetchall():
            sid, title, directory, ts = row
            sessions.append(
                SessionInfo(
                    session_id=sid,
                    title=title or "",
                    agent="mimocode",
                    file_path=self._db_path,
                )
            )
        conn.close()
        return sessions

    def read_session(self, session_id: str) -> RawSession:
        """Read session directly from mimocode DB (no CLI available)."""
        if not self._db_path.exists():
            raise RuntimeError(f"Mimocode DB not found: {self._db_path}")

        conn = sqlite3.connect(str(self._db_path))
        cur = conn.cursor()

        # Fetch session metadata
        cur.execute(
            "SELECT id, title, directory, time_created, time_updated "
            "FROM session WHERE id = ?", (session_id,)
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            raise RuntimeError(f"Session {session_id} not found")
        sid, title, directory, time_created, time_updated = row

        # Fetch messages in order
        cur.execute(
            "SELECT id, data FROM message WHERE session_id = ? ORDER BY time_created",
            (session_id,),
        )
        raw_messages = cur.fetchall()

        # Fetch parts per message
        messages = []
        for msg_id, msg_data in raw_messages:
            msg = json.loads(msg_data)
            cur2 = conn.cursor()
            cur2.execute(
                "SELECT data FROM part WHERE message_id = ? ORDER BY time_created",
                (msg_id,),
            )
            parts = [json.loads(prow[0]) for prow in cur2.fetchall()]
            messages.append({"info": msg, "parts": parts})

        conn.close()

        # Reconstruct the OpenCode-compatible JSON format
        session_data = {
            "info": {
                "id": sid,
                "title": title or "",
                "directory": directory or "",
                "time": {
                    "created": time_created,
                    "updated": time_updated,
                },
            },
            "messages": messages,
        }

        return RawSession(agent="mimocode", session_id=session_id, raw_data=json.dumps(session_data))

    def normalize(self, raw: RawSession) -> NormalizedSession:
        data = json.loads(raw.raw_data)
        info = data.get("info", {})
        messages = data.get("messages", [])

        time_info = info.get("time", {})
        created_ms = time_info.get("created") if isinstance(time_info, dict) else None
        created_at = ""
        if created_ms:
            created_at = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()

        norm_messages = [_normalize_message(msg) for msg in messages]
        norm_messages = [m for m in norm_messages if m is not None]

        return NormalizedSession(
            agent="mimocode",
            id=raw.session_id,
            title=info.get("title", ""),
            model="",
            directory=info.get("directory", ""),
            created_at=created_at,
            messages=norm_messages,
        )


# ---------------------------------------------------------------------------
# Shared normalization helpers (ported from opencode-md.py)
# ---------------------------------------------------------------------------

def _normalize_message(msg: dict) -> NormalizedMessage | None:
    info = msg.get("info", {}) or {}
    role = info.get("role", "unknown")
    parts = msg.get("parts", []) or []

    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    patches: list[Patch] = []
    reasoning: str | None = None

    for part in parts:
        t = part.get("type", "")
        if t == "text":
            text = part.get("text", "").rstrip()
            if text:
                content_parts.append(text)
        elif t == "reasoning":
            text = part.get("text", "").rstrip()
            if text:
                reasoning = text
        elif t == "tool":
            tc = _normalize_tool(part)
            if tc:
                tool_calls.append(tc)
        elif t == "patch":
            p = _normalize_patch(part)
            if p:
                patches.append(p)
        elif t == "file":
            fname = part.get("filename", "file")
            mime = part.get("mime", "")
            content_parts.append(f"_attachment: `{fname}` ({mime})_")
        elif t == "agent":
            name = part.get("name", "agent")
            content_parts.append(f"_sub-agent: {name}_")
        elif t == "subtask":
            desc = part.get("description", "")
            content_parts.append(f"_subtask: {desc}_")
        elif t == "snapshot":
            snap = part.get("snapshot", "")
            content_parts.append(f"_snapshot: `{snap}`_")
        # step-start / step-finish → skip

    content = "\n\n".join(content_parts)
    if not content and not tool_calls and not patches and not reasoning:
        return None

    return NormalizedMessage(
        role=role,
        content=content,
        tool_calls=tool_calls,
        reasoning=reasoning,
        patches=patches,
    )


def _normalize_tool(part: dict) -> ToolCall | None:
    name = part.get("tool", "tool")
    state = part.get("state", {}) or {}
    args = state.get("input", {}) or {}
    output = state.get("output")
    meta = state.get("metadata", {}) or {}
    title = meta.get("title", "")

    out_str = ""
    if output:
        out_str = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)

    return ToolCall(
        name=name,
        input=args,
        output=out_str,
        metadata={"title": title} if title else {},
    )


def _normalize_patch(part: dict) -> Patch | None:
    files = part.get("files") or []
    if not files:
        return None
    return Patch(files=files, hash=part.get("hash", ""))


# Register both adapters
register(OpenCodeAdapter)
register(MiMoCodeAdapter)
