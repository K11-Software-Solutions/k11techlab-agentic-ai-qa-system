# Copyright 2026 Kavita Jadhav / K11 Software Solutions LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""GitHub MCP Client.

Wraps the GitHub MCP server (github-mcp/) that exposes PR, file,
secret-scanning, and commit tools over stdio/HTTP.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from .base_client import BaseMCPClient

_DEFAULT_URL = os.getenv("GITHUB_MCP_URL", "http://localhost:8001")


class GitHubMCPClient(BaseMCPClient):
    """Client for the GitHub MCP server."""

    SERVER_NAME = "github"

    def __init__(self, server_url: str | None = None, timeout: float = 30.0) -> None:
        super().__init__(server_url or _DEFAULT_URL, timeout)
        self._http: httpx.AsyncClient | None = None

    async def _connect(self) -> None:
        self._http = httpx.AsyncClient(base_url=self._server_url, timeout=self._timeout)

    async def _disconnect(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def _send_request(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self._server_url, timeout=self._timeout)
        resp = await self._http.post(
            "/tools/call",
            json={"name": tool_name, "arguments": arguments},
        )
        resp.raise_for_status()
        data = resp.json()
        # MCP response format: {"content": [...], "isError": bool}
        if data.get("isError"):
            raise RuntimeError(str(data.get("content", "MCP error")))
        content = data.get("content", [{}])
        # Return first text block parsed as JSON, or raw dict
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":
                import json
                try:
                    return json.loads(first["text"])
                except Exception:
                    return {"raw": first["text"]}
        return data

    # ------------------------------------------------------------------ #
    # Convenience methods
    # ------------------------------------------------------------------ #

    async def get_pull_request(self, repo: str, pull_number: int) -> dict:
        return await self.call_tool("get_pull_request", {"repo": repo, "pull_number": pull_number})

    async def get_pull_request_diff(self, repo: str, pull_number: int) -> dict:
        return await self.call_tool("get_pull_request_diff", {"repo": repo, "pull_number": pull_number})

    async def list_pull_request_files(self, repo: str, pull_number: int) -> dict:
        return await self.call_tool("list_pull_request_files", {"repo": repo, "pull_number": pull_number})

    async def list_secret_scanning_alerts(self, repo: str, state: str = "open") -> dict:
        return await self.call_tool("list_secret_scanning_alerts", {"repo": repo, "state": state})
