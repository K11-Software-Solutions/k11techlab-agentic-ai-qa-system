"""Base MCP client — thin async wrapper around the MCP stdio/HTTP transport."""
from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Raised when an MCP call fails."""


class BaseMCPClient(ABC):
    """
    Minimal async MCP client base class.

    Sub-classes set SERVER_NAME and implement _send_request().
    The public call_tool() method handles logging and error wrapping.
    """

    SERVER_NAME: str = "base"

    def __init__(self, server_url: str | None = None, timeout: float = 60.0) -> None:
        self._server_url = server_url
        self._timeout = timeout
        self._log = logging.getLogger(f"mcps.{self.SERVER_NAME}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on this MCP server and return the result dict."""
        self._log.debug("→ %s.%s %s", self.SERVER_NAME, tool_name, arguments)
        try:
            result = await asyncio.wait_for(
                self._send_request(tool_name, arguments),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise MCPClientError(
                f"{self.SERVER_NAME}.{tool_name} timed out after {self._timeout}s"
            ) from exc
        except Exception as exc:
            raise MCPClientError(
                f"{self.SERVER_NAME}.{tool_name} failed: {exc}"
            ) from exc

        self._log.debug("← %s.%s OK", self.SERVER_NAME, tool_name)
        return result

    # ------------------------------------------------------------------ #
    # Abstract
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def _send_request(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Transport-specific implementation."""

    # ------------------------------------------------------------------ #
    # Context manager support
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "BaseMCPClient":
        await self._connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._disconnect()

    async def _connect(self) -> None:  # noqa: B027 — optional override
        pass

    async def _disconnect(self) -> None:  # noqa: B027 — optional override
        pass
