"""
MCP client wrappers for all 7 external services.
Each client exposes a .call_tool(tool_name, args) coroutine.
Configure via environment variables (see .env.example).
"""

from __future__ import annotations
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    """Lightweight async wrapper around an MCP server."""

    def __init__(self, name: str, base_url: str | None, api_key: str | None = None):
        self.name     = name
        self.base_url = base_url
        self.api_key  = api_key
        self._session = None

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        import aiohttp
        if not self.base_url:
            raise RuntimeError(f"MCP '{self.name}' has no base_url configured. "
                               f"Set {self.name.upper()}_MCP_URL in .env")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"tool": tool_name, "arguments": args}
        url = f"{self.base_url}/call"
        logger.debug("MCP %s: calling %s with %s", self.name, tool_name, list(args.keys()))
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                resp.raise_for_status()
                return await resp.json()


# ── Client instances (configured from environment) ────────────────────────────

github_mcp = MCPClient(
    name="github",
    base_url=os.getenv("GITHUB_MCP_URL", "http://localhost:3001"),
    api_key=os.getenv("GITHUB_TOKEN"),
)

playwright_mcp = MCPClient(
    name="playwright",
    base_url=os.getenv("PLAYWRIGHT_MCP_URL", "http://localhost:3002"),
)

k6_mcp = MCPClient(
    name="k6",
    base_url=os.getenv("K6_MCP_URL", "http://localhost:3003"),
)

jira_mcp = MCPClient(
    name="jira",
    base_url=os.getenv("JIRA_MCP_URL", "http://localhost:3004"),
    api_key=os.getenv("JIRA_TOKEN"),
)

postgres_mcp = MCPClient(
    name="postgres",
    base_url=os.getenv("POSTGRES_MCP_URL", "http://localhost:3005"),
    api_key=os.getenv("POSTGRES_URL"),
)

slack_mcp = MCPClient(
    name="slack",
    base_url=os.getenv("SLACK_MCP_URL", "http://localhost:3006"),
    api_key=os.getenv("SLACK_BOT_TOKEN"),
)

knowledge_store_mcp = MCPClient(
    name="knowledge_store",
    base_url=os.getenv("KNOWLEDGE_STORE_MCP_URL", "http://localhost:3007"),
)


# ── LangSmith client (optional) ───────────────────────────────────────────────
def _build_langsmith_client():
    if not os.getenv("LANGSMITH_API_KEY"):
        logger.info("LANGSMITH_API_KEY not set — LangSmith integration disabled")
        return None
    try:
        from langsmith import Client
        return Client()
    except ImportError:
        logger.warning("langsmith package not installed")
        return None

langsmith_client = _build_langsmith_client()
