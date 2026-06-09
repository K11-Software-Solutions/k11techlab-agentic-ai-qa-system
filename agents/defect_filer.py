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
"""Defect Filer Agent — Phase 3, Agent 14.

Files Jira tickets for every high/critical defect found by Phase 2
agents, using the Jira MCP server.  De-duplicates against open tickets
to avoid noise.
"""
from __future__ import annotations

import hashlib

from .base import AgentResult, BaseQAAgent

_SEVERITY_PRIORITY_MAP = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


class DefectFilerAgent(BaseQAAgent):
    """Creates Jira issues for actionable defects via the Jira MCP."""

    NAME = "defect_filer"
    TIMEOUT = 180

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        defects: list[dict] = state.get("defects", [])
        pr_number: int = state.get("pr_number", 0)
        repo: str = state.get("repo_name", "")
        project_key: str = suite.get("jira_project", "QA")

        # Filter to high/critical only
        actionable = [d for d in defects if d.get("severity") in ("critical", "high")]
        if not actionable:
            return AgentResult(
                agent=self.NAME,
                suite_type="defect_filing",
                priority="medium",
                passed=0,
                failed=0,
                total_cases=0,
                metadata={"skipped": "no high/critical defects to file"},
            )

        # Fetch existing open tickets to deduplicate
        existing_raw = await self.call_mcp(
            "jira",
            "search_issues",
            {
                "jql": f'project = {project_key} AND status != Done AND labels = "pr-{pr_number}"',
                "max_results": 100,
            },
        )
        existing_summaries: set[str] = {
            i.get("summary", "") for i in existing_raw.get("issues", [])
        }

        filed = 0
        skipped = 0
        filed_keys: list[str] = []

        for defect in actionable:
            title = defect.get("title", "QA Defect")

            # Skip if already filed
            if title in existing_summaries:
                skipped += 1
                continue

            description = self._build_description(defect, repo, pr_number)
            priority = _SEVERITY_PRIORITY_MAP.get(defect.get("severity", "medium"), "Medium")

            issue_raw = await self.call_mcp(
                "jira",
                "create_issue",
                {
                    "project_key": project_key,
                    "summary": title,
                    "description": description,
                    "issue_type": "Bug",
                    "priority": priority,
                    "labels": [f"pr-{pr_number}", "automated-qa", defect.get("suite_type", "qa")],
                },
            )

            key = issue_raw.get("key", "")
            if key:
                filed += 1
                filed_keys.append(key)

        return AgentResult(
            agent=self.NAME,
            suite_type="defect_filing",
            priority="high",
            passed=filed,
            failed=0,
            total_cases=len(actionable),
            metadata={
                "filed": filed,
                "skipped_duplicates": skipped,
                "jira_keys": filed_keys,
                "project": project_key,
            },
        )

    def _build_description(self, defect: dict, repo: str, pr_number: int) -> str:
        lines = [
            f"*Repo:* {repo}",
            f"*PR:* #{pr_number}",
            f"*Agent:* {defect.get('agent', 'automated')}",
            f"*Suite:* {defect.get('suite_type', 'unknown')}",
            "",
            "*Detail:*",
            defect.get("detail", "No detail provided"),
        ]
        extra = {k: v for k, v in defect.items() if k not in
                  {"title", "severity", "detail", "agent", "suite_type"}}
        if extra:
            lines += ["", "*Extra:*", str(extra)]
        return "\n".join(lines)
