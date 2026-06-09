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
"""k6 MCP Client.

Wraps the k6 MCP server (k6-mcp/) that exposes load test execution,
threshold evaluation, and performance metrics collection.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base_client import BaseMCPClient

_DEFAULT_URL = os.getenv("K6_MCP_URL", "http://localhost:8003")


class K6MCPClient(BaseMCPClient):
    """Client for the k6 MCP server."""

    SERVER_NAME = "k6"

    def __init__(self, server_url: str | None = None, timeout: float = 360.0) -> None:
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
            raise RuntimeError(str(data.get("content", "k6 MCP error")))
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

    async def run_load_test(
        self,
        scenarios: list[dict],
        thresholds: dict | None = None,
        vus: int = 10,
        duration: str = "30s",
    ) -> dict:
        return await self.call_tool(
            "run_load_test",
            {
                "scenarios": scenarios,
                "thresholds": thresholds or {"http_req_duration": "p(95)<2000"},
                "vus": vus,
                "duration": duration,
            },
        )

    async def get_test_results(self, test_id: str) -> dict:
        return await self.call_tool("get_test_results", {"test_id": test_id})
