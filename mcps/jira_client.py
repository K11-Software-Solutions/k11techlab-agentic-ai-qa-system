# Copyright 2026 K11 Software Solutions LLC
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
"""Jira MCP Client.

Wraps the Jira MCP server (jira-mcp/) that exposes issue creation,
search (JQL), comment, and status transition tools.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base_client import BaseMCPClient

_DEFAULT_URL = os.getenv("JIRA_MCP_URL", "http://localhost:8004")


class JiraMCPClient(BaseMCPClient):
    """Client for the Jira MCP server."""

    SERVER_NAME = "jira"

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
        if data.get("isError"):
            raise RuntimeError(str(data.get("content", "Jira MCP error")))
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

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        description: str,
        issue_type: str = "Bug",
        priority: str = "High",
        labels: list[str] | None = None,
    ) -> dict:
        return await self.call_tool(
            "create_issue",
            {
                "project_key": project_key,
                "summary": summary,
                "description": description,
                "issue_type": issue_type,
                "priority": priority,
                "labels": labels or [],
            },
        )

    async def search_issues(self, jql: str, max_results: int = 50) -> dict:
        return await self.call_tool("search_issues", {"jql": jql, "max_results": max_results})

    async def add_comment(self, issue_key: str, body: str) -> dict:
        return await self.call_tool("add_comment", {"issue_key": issue_key, "body": body})

    async def transition_issue(self, issue_key: str, transition_name: str) -> dict:
        return await self.call_tool("transition_issue", {"issue_key": issue_key, "transition_name": transition_name})
