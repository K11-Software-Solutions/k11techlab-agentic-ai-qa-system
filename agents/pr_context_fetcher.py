"""PR Context Fetcher Agent — Phase 1, Agent 3.

Calls the GitHub MCP server to retrieve the PR diff, list of changed
files, PR metadata (author, base branch, labels) and stores them in the
pipeline state for downstream agents.
"""
from __future__ import annotations

from .base import AgentResult, BaseQAAgent


class PRContextFetcherAgent(BaseQAAgent):
    """Fetches pull-request context from GitHub via MCP."""

    NAME = "pr_context_fetcher"
    TIMEOUT = 60

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        repo: str = state.get("repo_name", "")
        pr_number: int = state.get("pr_number", 0)

        # Fetch PR metadata
        pr_meta = await self.call_mcp(
            "github",
            "get_pull_request",
            {"repo": repo, "pull_number": pr_number},
        )

        # Fetch diff
        diff_raw = await self.call_mcp(
            "github",
            "get_pull_request_diff",
            {"repo": repo, "pull_number": pr_number},
        )

        # Fetch file list
        files_raw = await self.call_mcp(
            "github",
            "list_pull_request_files",
            {"repo": repo, "pull_number": pr_number},
        )

        changed_files = [f.get("filename", "") for f in files_raw.get("files", [])]
        diff_text: str = diff_raw.get("diff", "")

        return AgentResult(
            agent=self.NAME,
            suite_type=suite.get("suite_type", "pr_context"),
            priority="high",
            passed=1,
            failed=0,
            total_cases=1,
            metadata={
                "pr_diff": diff_text,
                "changed_files": changed_files,
                "author": pr_meta.get("user", {}).get("login", "unknown"),
                "base_branch": pr_meta.get("base", {}).get("ref", "main"),
                "labels": [lb.get("name") for lb in pr_meta.get("labels", [])],
                "title": pr_meta.get("title", ""),
            },
        )
