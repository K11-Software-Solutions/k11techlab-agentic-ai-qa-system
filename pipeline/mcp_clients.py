"""
MCP client registry for the pipeline layer.

Delegates to the typed clients in mcps/ so there is a single HTTP
implementation.  The module also exports a plain name→client dict
that phase nodes pass into agent constructors.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from mcps import (
    GitHubMCPClient,
    PlaywrightMCPClient,
    K6MCPClient,
    JiraMCPClient,
    PostgresMCPClient,
    SlackMCPClient,
    KnowledgeStoreMCPClient,
    build_mcp_clients,
)

logger = logging.getLogger(__name__)

# ── Singleton instances (module-level, re-used across pipeline runs) ──────────

github_mcp           = GitHubMCPClient()
playwright_mcp       = PlaywrightMCPClient()
k6_mcp               = K6MCPClient()
jira_mcp             = JiraMCPClient()
postgres_mcp         = PostgresMCPClient()
slack_mcp            = SlackMCPClient()
knowledge_store_mcp  = KnowledgeStoreMCPClient()

# Dict passed to agent constructors:  agent = MyAgent(mcp_clients=ALL_CLIENTS)
ALL_CLIENTS: dict[str, Any] = build_mcp_clients()


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
