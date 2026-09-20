"""
Adolf-StreamX — Remote Control Core
Step 13A

This module is intentionally standalone.
It does NOT modify QR pairing, streaming, database, or existing routes.

Step 13A provides the safe server-side session/command layer that the
next integration step can connect to a FastAPI WebSocket endpoint.

Supported commands:
    play
    pause
    toggle
    seek_forward
    seek_backward
    seek
    volume_up
    volume_down
    set_volume
    mute
    fullscreen
    exit_fullscreen
    stop

The module does not execute player actions itself. It validates commands
and forwards them to the currently connected TV WebSocket.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REMOTE_SESSION_TTL = 60 * 60          # 1 hour without activity
REMOTE_PAIR_TIMEOUT = 10 * 60         # unused sessions expire after 10 min
REMOTE_MAX_SESSIONS = 1000
REMOTE_MAX_MESSAGE_SIZE = 4096

ALLOWED_COMMANDS = frozenset(
    {
        "play",
        "pause",
        "toggle",
        "seek_forward",
        "seek_backward",
        "seek",
        "volume_up",
        "volume_down",
        "set_volume",
        "mute",
        "fullscreen",
        "exit_fullscreen",
        "stop",
    }
)


@dataclass
class RemoteSession:
    """One phone/TV remote-control session."""

    session_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    tv_socket: Any = None
    phone_socket: Any = None

    def touch(self) -> None:
        self.last_activity = time.time()

    @property
    def expired(self) -> bool:
        return (time.time() - self.last_activity) > REMOTE_SESSION_TTL


class RemoteControlManager:
    """
    In-memory remote-control session manager.

    A session can have at most one TV socket and one phone socket.
    Socket objects are deliberately treated as opaque so this module stays
    independent of FastAPI/Starlette versions.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, RemoteSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(self) -> str:
        """Create a cryptographically random remote session ID."""
        async with self._lock:
            await self._cleanup_locked()

            if len(self._sessions) >= REMOTE_MAX_SESSIONS:
                raise RuntimeError("Remote session limit reached")

            for _ in range(10):
                session_id = secrets.token_urlsafe(24)
                if session_id not in self._sessions:
                    self._sessions[session_id] = RemoteSession(
                        session_id=session_id
                    )
                    return session_id

            raise RuntimeError("Could not create remote session")

    async def get_session(self, session_id: str) -> Optional[RemoteSession]:
        """Return an active session or None."""
        if not self.valid_session_id(session_id):
            return None

        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.expired:
                if session is not None:
                    self._sessions.pop(session_id, None)
                return None

            session.touch()
            return session

    async def attach_tv(self, session_id: str, websocket: Any) -> bool:
        """Attach/re-attach the TV socket for a valid session."""
        session = await self.get_session(session_id)
        if session is None:
            return False

        async with self._lock:
            session.tv_socket = websocket
            session.touch()
        return True

    async def attach_phone(self, session_id: str, websocket: Any) -> bool:
        """Attach/re-attach the phone socket for a valid session."""
        session = await self.get_session(session_id)
        if session is None:
            return False

        async with self._lock:
            session.phone_socket = websocket
            session.touch()
        return True

    async def detach(self, session_id: str, websocket: Any = None) -> None:
        """
        Detach a socket.

        If websocket is supplied, only that exact socket is detached.
        This prevents an old connection from accidentally clearing a newer
        reconnecting connection.
        """
        if not self.valid_session_id(session_id):
            return

        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return

            if websocket is None:
                session.tv_socket = None
                session.phone_socket = None
            elif session.tv_socket is websocket:
                session.tv_socket = None
            elif session.phone_socket is websocket:
                session.phone_socket = None

            session.touch()

    async def close_session(self, session_id: str) -> None:
        """Remove a session completely."""
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def send_to_tv(self, session_id: str, payload: dict[str, Any]) -> bool:
        """Send a validated command payload to the TV socket."""
        session = await self.get_session(session_id)
        if session is None or session.tv_socket is None:
            return False

        socket = session.tv_socket

        try:
            await socket.send_json(payload)
            session.touch()
            return True
        except Exception:
            # Socket cleanup is handled by the integration endpoint.
            return False

    async def send_to_phone(
        self, session_id: str, payload: dict[str, Any]
    ) -> bool:
        """Send a status/event payload to the phone socket."""
        session = await self.get_session(session_id)
        if session is None or session.phone_socket is None:
            return False

        socket = session.phone_socket

        try:
            await socket.send_json(payload)
            session.touch()
            return True
        except Exception:
            return False

    async def broadcast(
        self, session_id: str, payload: dict[str, Any]
    ) -> tuple[bool, bool]:
        """Send a payload to both connected sides."""
        tv_ok = await self.send_to_tv(session_id, payload)
        phone_ok = await self.send_to_phone(session_id, payload)
        return tv_ok, phone_ok

    async def cleanup(self) -> int:
        """Remove expired sessions and return the number removed."""
        async with self._lock:
            return await self._cleanup_locked()

    async def _cleanup_locked(self) -> int:
        now = time.time()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if (now - session.last_activity) > REMOTE_SESSION_TTL
            or (
                session.tv_socket is None
                and session.phone_socket is None
                and (now - session.created_at) > REMOTE_PAIR_TIMEOUT
            )
        ]

        for sid in expired:
            self._sessions.pop(sid, None)

        return len(expired)

    def count(self) -> int:
        """Current in-memory session count."""
        return len(self._sessions)

    @staticmethod
    def valid_session_id(session_id: str) -> bool:
        """
        Validate the opaque session ID format.

        URL-safe tokens generated by secrets.token_urlsafe(24) are roughly
        32 characters. We accept a bounded range for forward compatibility.
        """
        if not isinstance(session_id, str):
            return False
        if not (20 <= len(session_id) <= 128):
            return False
        return all(
            ch.isalnum() or ch in "-_"
            for ch in session_id
        )


# One process-local manager. Step 13B will import this instance.
remote_manager = RemoteControlManager()


def validate_command(payload: Any) -> Optional[dict[str, Any]]:
    """
    Validate an incoming phone command.

    Returns a normalized payload or None if invalid.
    No player action is executed here.
    """
    if not isinstance(payload, dict):
        return None

    command = payload.get("command")
    if not isinstance(command, str) or command not in ALLOWED_COMMANDS:
        return None

    normalized: dict[str, Any] = {"command": command}

    if command in {"seek", "seek_forward", "seek_backward"}:
        value = payload.get("seconds", 10)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if abs(float(value)) > 3600:
            return None
        normalized["seconds"] = float(value)

    elif command == "set_volume":
        value = payload.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not 0 <= float(value) <= 100:
            return None
        normalized["value"] = float(value)

    return normalized


def command_payload(command: str, **kwargs: Any) -> Optional[dict[str, Any]]:
    """Build a validated command payload for the phone UI."""
    return validate_command({"command": command, **kwargs})


def message_size_ok(message: Any) -> bool:
    """Reject unexpectedly large WebSocket messages before JSON processing."""
    if isinstance(message, (bytes, bytearray)):
        return len(message) <= REMOTE_MAX_MESSAGE_SIZE
    if isinstance(message, str):
        return len(message.encode("utf-8")) <= REMOTE_MAX_MESSAGE_SIZE
    return False
