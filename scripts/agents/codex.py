"""Codex adapter — reads ~/.codex/sessions/**/rollout-*.jsonl sessions."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import register
from .base import (
    AgentAdapter,
    NormalizedMessage,
    NormalizedSession,
    RawSession,
    SessionInfo,
    ToolCall,
)

_CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
_SESSIONS_DIR = _CODEX_HOME / "sessions"
_SESSION_INDEX = _CODEX_HOME / "session_index.jsonl"
_ROLLOUT_RE = re.compile(r"rollout-[a-f0-9-]+\.jsonl$", re.IGNORECASE)


def _load_thread_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if not _SESSION_INDEX.exists():
        return names
    try:
        with open(_SESSION_INDEX, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tid = entry.get("id")
                tname = entry.get("thread_name")
                if isinstance(tid, str) and isinstance(tname, str) and tname.strip():
                    names[tid] = tname.strip()
    except OSError:
        pass
    return names


class CodexAdapter(AgentAdapter):
    name = "codex"

    # ── discovery ────────────────────────────────────────────

    def discover_sessions(self) -> list[SessionInfo]:
        if not _SESSIONS_DIR.is_dir():
            return []

        thread_names = _load_thread_names()
        sessions: list[SessionInfo] = []
        seen_ids: set[str] = set()

        for rollout in _SESSIONS_DIR.rglob("rollout-*.jsonl"):
            sid = self._session_id_from_path(rollout)
            if sid in seen_ids:
                continue
            seen_ids.add(sid)

            title = thread_names.get(sid, "")
            if not title:
                title = self._peek_title(rollout)

            sessions.append(
                SessionInfo(
                    session_id=sid,
                    title=title,
                    agent=self.name,
                    file_path=rollout,
                )
            )

        sessions.sort(key=lambda s: s.file_path.stat().st_mtime, reverse=True)
        return sessions

    def _session_id_from_path(self, path: Path) -> str:
        """Extract session ID from rollout filename."""
        # rollout-<uuid>.jsonl → <uuid>
        stem = path.stem  # rollout-<uuid>
        return stem.removeprefix("rollout-")

    def _peek_title(self, path: Path) -> str:
        """Scan the first few lines for session_meta or first user_message."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for _ in range(30):
                    line = fh.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    if obj.get("type") == "session_meta":
                        cwd = obj.get("cwd", "")
                        if cwd:
                            return Path(cwd).name or cwd

                    if obj.get("type") == "event_msg":
                        payload = obj.get("payload", obj)
                        if payload.get("type") == "user_message":
                            msg = payload.get("message", "")
                            text = self._extract_message_text(msg)
                            if text.strip():
                                first_line = text.strip().splitlines()[0][:80]
                                return first_line
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
            matches = list(_SESSIONS_DIR.rglob(f"rollout-{session_id}.jsonl"))
            if not matches:
                # Also try matching the filename directly
                matches = list(_SESSIONS_DIR.rglob(f"{session_id}.jsonl"))
            if not matches:
                raise FileNotFoundError(
                    f"No Codex session found matching '{session_id}'"
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
            session_id=self._session_id_from_path(jsonl_path),
            raw_data={"events": events, "path": str(jsonl_path)},
        )

    # ── normalize ────────────────────────────────────────────

    def normalize(self, raw: RawSession) -> NormalizedSession:
        events = raw.raw_data["events"]
        jsonl_path = Path(raw.raw_data["path"])

        title = ""
        model = ""
        cwd = ""
        created_at = ""
        messages: list[NormalizedMessage] = []
        # Accumulator for streaming assistant blocks within a turn
        current_assistant_text: list[str] = []
        current_assistant_reasoning: list[str] = []
        current_assistant_tools: list[ToolCall] = []

        for ev in events:
            ev_type = ev.get("type")
            ts = ev.get("timestamp", "")

            if not created_at and ts:
                created_at = ts

            # ── Session metadata ──
            if ev_type == "session_meta":
                if not title:
                    cwd = ev.get("cwd", "")
                    if cwd:
                        title = Path(cwd).name or cwd
                    title = title or raw.session_id
                if not model and ev.get("model"):
                    model = ev["model"]
                continue

            # ── Event messages (streaming) ──
            if ev_type == "event_msg":
                payload = ev.get("payload", ev)
                msg_type = payload.get("type")

                if msg_type == "user_message":
                    # Flush any pending assistant content
                    self._flush_assistant(
                        current_assistant_text,
                        current_assistant_reasoning,
                        current_assistant_tools,
                        messages,
                        ts,
                    )

                    msg = payload.get("message", "")
                    text = self._extract_message_text(msg)
                    if text.strip():
                        messages.append(
                            NormalizedMessage(
                                role="user",
                                content=text.strip(),
                                timestamp=ts,
                            )
                        )

                elif msg_type == "agent_message":
                    text = payload.get("message", "")
                    text = self._extract_message_text(text)
                    is_reasoning = payload.get("is_reasoning", False)

                    if text.strip():
                        if is_reasoning:
                            current_assistant_reasoning.append(text.strip())
                        else:
                            current_assistant_text.append(text.strip())

                continue

            # ── Response items (structured record) ──
            if ev_type == "response_item":
                payload = ev.get("payload", ev)
                item_type = payload.get("type")

                if item_type == "message" and payload.get("role") == "assistant":
                    # If we already collected content from event_msgs, skip this
                    if not current_assistant_text and not current_assistant_reasoning:
                        content = payload.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if block.get("type") == "output_text":
                                    current_assistant_text.append(
                                        block.get("text", "").strip()
                                    )
                                elif block.get("type") == "reasoning_text":
                                    current_assistant_reasoning.append(
                                        block.get("text", "").strip()
                                    )

                elif item_type == "function_call":
                    current_assistant_tools.append(
                        ToolCall(
                            name=payload.get("name", "unknown"),
                            input=payload.get("arguments", {}),
                            metadata={"call_id": payload.get("call_id", "")},
                        )
                    )

                elif item_type == "function_call_output":
                    # Flush assistant blocks before the tool result
                    self._flush_assistant(
                        current_assistant_text,
                        current_assistant_reasoning,
                        current_assistant_tools,
                        messages,
                        ts,
                    )

                    output = payload.get("output", "")
                    if not isinstance(output, str):
                        try:
                            output = json.dumps(output)
                        except (TypeError, ValueError):
                            output = str(output)

                    messages.append(
                        NormalizedMessage(
                            role="user",
                            content=output,
                            timestamp=ts,
                        )
                    )

                continue

            # ── Turn context (model info) ──
            if ev_type in ("TurnContext", "turn_context"):
                if not model and ev.get("model"):
                    model = ev["model"]
                continue

            # Skip token_count and other events

        # Flush final assistant content
        self._flush_assistant(
            current_assistant_text,
            current_assistant_reasoning,
            current_assistant_tools,
            messages,
            "",
        )

        if not title:
            title = raw.session_id

        return NormalizedSession(
            agent=self.name,
            id=raw.session_id,
            title=title,
            model=model,
            directory=cwd,
            created_at=created_at,
            messages=messages,
        )

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _extract_message_text(msg) -> str:
        if isinstance(msg, str):
            return msg
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                return "\n".join(parts)
            return str(content) if content else ""
        return str(msg) if msg else ""

    @staticmethod
    def _flush_assistant(
        text_parts: list[str],
        reasoning_parts: list[str],
        tool_calls: list[ToolCall],
        messages: list[NormalizedMessage],
        timestamp: str,
    ) -> None:
        content = "\n\n".join(text_parts)
        reasoning = "\n\n".join(reasoning_parts) if reasoning_parts else None

        if not content.strip() and not tool_calls and not reasoning:
            return

        messages.append(
            NormalizedMessage(
                role="assistant",
                content=content,
                reasoning=reasoning,
                tool_calls=tool_calls[:],
                timestamp=timestamp,
            )
        )

        text_parts.clear()
        reasoning_parts.clear()
        tool_calls.clear()


register(CodexAdapter)
