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
"""Knowledge Store MCP Client.

Wraps the Knowledge Store MCP server (knowledge-store-mcp/) that
exposes semantic search, document ingestion, regression suite retrieval,
and runbook lookup tools.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base_client import BaseMCPClient

_DEFAULT_URL = os.getenv("KNOWLEDGE_STORE_MCP_URL", "http://localhost:8007")


class KnowledgeStoreMCPClient(BaseMCPClient):
    """Client for the Knowledge Store MCP server."""

    SERVER_NAME = "knowledge_store"

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
            raise RuntimeError(str(data.get("content", "Knowledge Store MCP error")))
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

    async def search_documents(
        self,
        query: str,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> dict:
        return await self.call_tool(
            "search_documents",
            {"query": query, "top_k": top_k, "filters": filters or {}},
        )

    async def get_regression_suite(
        self,
        changed_files: list[str],
        max_cases: int = 50,
        priority_filter: str = "high",
    ) -> dict:
        return await self.call_tool(
            "get_regression_suite",
            {
                "changed_files": changed_files,
                "max_cases": max_cases,
                "priority_filter": priority_filter,
            },
        )

    async def ingest_document(self, content: str, doc_type: str, metadata: dict | None = None) -> dict:
        return await self.call_tool(
            "ingest_document",
            {"content": content, "doc_type": doc_type, "metadata": metadata or {}},
        )

    async def get_runbook(self, component: str) -> dict:
        return await self.call_tool("get_runbook", {"component": component})
