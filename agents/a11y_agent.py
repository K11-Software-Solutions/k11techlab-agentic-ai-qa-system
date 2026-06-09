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
"""Accessibility Agent — Phase 2, Agent 11.

Audits UI pages against WCAG 2.1 AA using axe-core via the Playwright
MCP server's accessibility scan tool.
"""
from __future__ import annotations

import os

from .base import AgentResult, BaseQAAgent

# axe-core impact levels → our severity mapping
_IMPACT_MAP = {
    "critical": "critical",
    "serious": "high",
    "moderate": "medium",
    "minor": "low",
}


class AccessibilityAgent(BaseQAAgent):
    """WCAG 2.1 AA accessibility audit via Playwright / axe-core."""

    NAME = "a11y_agent"
    TIMEOUT = 180

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        base_url: str = os.getenv("TARGET_BASE_URL", "http://localhost:3000")
        pages: list[str] = suite.get("pages", ["/", "/login", "/dashboard"])
        wcag_level: str = suite.get("wcag_level", "wcag2aa")

        passed = 0
        failed = 0
        defects: list[dict] = []

        for page_path in pages:
            raw = await self.call_mcp(
                "playwright",
                "run_accessibility_scan",
                {
                    "url": base_url + page_path,
                    "tags": [wcag_level],
                    "include_passes": False,
                },
            )

            violations: list[dict] = raw.get("violations", [])
            if not violations:
                passed += 1
            else:
                failed += 1
                for v in violations:
                    defects.append({
                        "title": f"A11y: {v.get('id', 'unknown')} on {page_path}",
                        "severity": _IMPACT_MAP.get(v.get("impact", "minor"), "low"),
                        "detail": v.get("description", ""),
                        "wcag_tags": v.get("tags", []),
                        "nodes_affected": len(v.get("nodes", [])),
                        "help_url": v.get("helpUrl", ""),
                        "page": page_path,
                    })

        return AgentResult(
            agent=self.NAME,
            suite_type="accessibility",
            priority=suite.get("priority", "medium"),
            passed=passed,
            failed=failed,
            total_cases=len(pages),
            defects=defects,
            metadata={
                "wcag_level": wcag_level,
                "pages_audited": pages,
                "total_violations": len(defects),
            },
        )
