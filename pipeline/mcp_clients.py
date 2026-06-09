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
