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
"""Postgres MCP Client.

Wraps the Postgres MCP server (postgres-mcp/) that exposes read-only
and read-write SQL execution, schema introspection, and migration tools.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base_client import BaseMCPClient

_DEFAULT_URL = os.getenv("POSTGRES_MCP_URL", "http://localhost:8005")


class PostgresMCPClient(BaseMCPClient):
    """Client for the Postgres MCP server."""

    SERVER_NAME = "postgres"

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
            raise RuntimeError(str(data.get("content", "Postgres MCP error")))
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

    async def execute_query(self, sql: str, read_only: bool = True, params: list | None = None) -> dict:
        return await self.call_tool(
            "execute_query",
            {"sql": sql, "read_only": read_only, "params": params or []},
        )

    async def list_tables(self, schema: str = "public") -> dict:
        return await self.call_tool("list_tables", {"schema": schema})

    async def describe_table(self, table_name: str, schema: str = "public") -> dict:
        return await self.call_tool("describe_table", {"table_name": table_name, "schema": schema})

    async def run_migration(self, migration_sql: str) -> dict:
        return await self.call_tool("run_migration", {"sql": migration_sql})
