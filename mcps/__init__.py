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
"""K11 TechLab MCP client wrappers — one per MCP server."""

from .base_client import BaseMCPClient, MCPClientError
from .github_client import GitHubMCPClient
from .playwright_client import PlaywrightMCPClient
from .k6_client import K6MCPClient
from .jira_client import JiraMCPClient
from .postgres_client import PostgresMCPClient
from .slack_client import SlackMCPClient
from .knowledge_store_client import KnowledgeStoreMCPClient


def build_mcp_clients(
    github_url: str | None = None,
    playwright_url: str | None = None,
    k6_url: str | None = None,
    jira_url: str | None = None,
    postgres_url: str | None = None,
    slack_url: str | None = None,
    knowledge_store_url: str | None = None,
) -> dict[str, BaseMCPClient]:
    """
    Instantiate all 7 MCP clients.

    Pass explicit URLs to override the environment variable defaults.
    Returns a dict keyed by the server name used in agent call_mcp() calls.
    """
    return {
        "github": GitHubMCPClient(github_url),
        "playwright": PlaywrightMCPClient(playwright_url),
        "k6": K6MCPClient(k6_url),
        "jira": JiraMCPClient(jira_url),
        "postgres": PostgresMCPClient(postgres_url),
        "slack": SlackMCPClient(slack_url),
        "knowledge_store": KnowledgeStoreMCPClient(knowledge_store_url),
    }


__all__ = [
    "BaseMCPClient",
    "MCPClientError",
    "GitHubMCPClient",
    "PlaywrightMCPClient",
    "K6MCPClient",
    "JiraMCPClient",
    "PostgresMCPClient",
    "SlackMCPClient",
    "KnowledgeStoreMCPClient",
    "build_mcp_clients",
]
