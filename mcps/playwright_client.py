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
"""Playwright MCP Client.

Wraps the Playwright MCP server (playwright-mcp/) that exposes browser
automation, E2E scenario execution, accessibility scanning, screenshot
comparison, and cross-browser testing tools.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base_client import BaseMCPClient

_DEFAULT_URL = os.getenv("PLAYWRIGHT_MCP_URL", "http://localhost:8002")


class PlaywrightMCPClient(BaseMCPClient):
    """Client for the Playwright MCP server."""

    SERVER_NAME = "playwright"

    def __init__(self, server_url: str | None = None, timeout: float = 120.0) -> None:
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
        if data.get("isError"):
            raise RuntimeError(str(data.get("content", "Playwright MCP error")))
        content = data.get("content", [{}])
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":
                try:
                    return json.loads(first["text"])
                except Exception:
                    return {"raw": first["text"]}
        return data

    # ------------------------------------------------------------------ #
    # Convenience methods
    # ------------------------------------------------------------------ #

    async def run_scenario(self, url: str, steps: list[dict], **kwargs) -> dict:
        return await self.call_tool("run_scenario", {"url": url, "steps": steps, **kwargs})

    async def run_accessibility_scan(self, url: str, tags: list[str] | None = None, **kwargs) -> dict:
        return await self.call_tool("run_accessibility_scan", {"url": url, "tags": tags or ["wcag2aa"], **kwargs})

    async def run_cross_browser(self, browser: str, url: str, **kwargs) -> dict:
        return await self.call_tool("run_cross_browser", {"browser": browser, "url": url, **kwargs})

    async def compare_screenshots(self, screenshots: dict[str, str], threshold: float = 0.05) -> dict:
        return await self.call_tool("compare_screenshots", {"screenshots": screenshots, "threshold": threshold})
