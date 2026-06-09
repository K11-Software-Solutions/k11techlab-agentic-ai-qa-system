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
"""Knowledge Retriever Agent — Phase 1, Agent 2.

Fetches relevant past-defect patterns and runbooks from the Knowledge
Store MCP server given the PR's changed files and diff summary.
"""
from __future__ import annotations

from .base import AgentResult, BaseQAAgent


class KnowledgeRetrieverAgent(BaseQAAgent):
    """Retrieves historical QA context from the Knowledge Store MCP."""

    NAME = "knowledge_retriever"
    TIMEOUT = 60

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        changed_files: list[str] = state.get("changed_files", [])
        pr_diff: str = state.get("pr_diff", "")

        # Build a concise query from the changed file paths
        query_terms = " ".join(
            f.split("/")[-1].replace(".py", "").replace("_", " ")
            for f in changed_files[:10]
        )
        query = f"{query_terms} {pr_diff[:200]}".strip()

        raw = await self.call_mcp(
            "knowledge_store",
            "search_documents",
            {"query": query, "top_k": 10, "filters": {"doc_type": ["defect", "runbook"]}},
        )

        documents: list[dict] = raw.get("documents", [])
        snippets = [d.get("content", "") for d in documents if d.get("content")]

        return AgentResult(
            agent=self.NAME,
            suite_type=suite.get("suite_type", "knowledge_retrieval"),
            priority="high",
            passed=len(snippets),
            failed=0,
            total_cases=len(snippets),
            metadata={
                "retrieval_context": snippets,
                "query": query,
                "doc_count": len(documents),
            },
        )
