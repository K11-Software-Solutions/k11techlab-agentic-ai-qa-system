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
"""Slack MCP Client.

Wraps the Slack MCP server (slack-mcp/) that exposes message sending,
channel listing, and slash-command response tools.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base_client import BaseMCPClient

_DEFAULT_URL = os.getenv("SLACK_MCP_URL", "http://localhost:8006")


class SlackMCPClient(BaseMCPClient):
    """Client for the Slack MCP server."""

    SERVER_NAME = "slack"

    def __init__(self, server_url: str | None = None, timeout: float = 15.0) -> None:
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
            raise RuntimeError(str(data.get("content", "Slack MCP error")))
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

    async def post_message(self, channel: str, text: str, blocks: list | None = None) -> dict:
        return await self.call_tool(
            "post_message",
            {"channel": channel, "text": text, "blocks": blocks or []},
        )

    async def post_qa_report(self, channel: str, report_md: str, pr_number: int, repo: str) -> dict:
        """Post a formatted QA report summary to Slack."""
        # Truncate to Slack's 3000-char block limit
        summary = report_md[:2800] + ("..." if len(report_md) > 2800 else "")
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"QA Report — {repo}#{pr_number}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": summary},
            },
        ]
        return await self.post_message(channel=channel, text=f"QA Report for PR #{pr_number}", blocks=blocks)

    async def list_channels(self) -> dict:
        return await self.call_tool("list_channels", {})
