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
"""Report Generator Agent — Phase 3, Agent 13.

Aggregates all Phase 2 test results and uses an LLM to produce a
human-readable Markdown QA report that is stored in pipeline state.
"""
from __future__ import annotations

import json
import os
from collections import Counter

from langchain_openai import ChatOpenAI

from .base import AgentResult, BaseQAAgent

_SYSTEM = """You are a senior QA engineer writing an executive QA report.
Given a JSON summary of test results, produce a professional Markdown report with:
1. Executive Summary (2-3 sentences)
2. Test Results table (suite | passed | failed | defects)
3. Critical Defects list (title, severity, detail)
4. Risk Assessment (one paragraph)
5. Recommendation (APPROVE / BLOCK / NEEDS_REVIEW)

Be concise. Use Markdown headings. No JSON in output."""


class ReportGeneratorAgent(BaseQAAgent):
    """LLM-powered QA report generation from aggregated results."""

    NAME = "report_generator"
    TIMEOUT = 120

    def __init__(self, mcp_clients=None) -> None:
        super().__init__(mcp_clients)
        self._llm = ChatOpenAI(
            model=os.getenv("REPORT_MODEL", "gpt-4o-mini"),
            temperature=0,
        )

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        test_results: list[dict] = state.get("test_results", [])
        defects: list[dict] = state.get("defects", [])
        risk_score: float = state.get("risk_score", 0.0)
        pr_number: int = state.get("pr_number", 0)
        repo: str = state.get("repo_name", "")

        # Build compact summary for LLM
        suite_summary = []
        for r in test_results:
            suite_summary.append({
                "suite": r.get("suite_type"),
                "agent": r.get("agent"),
                "passed": r.get("passed", 0),
                "failed": r.get("failed", 0),
                "total": r.get("total_cases", 0),
                "error": r.get("error"),
            })

        severity_counts = Counter(d.get("severity", "medium") for d in defects)
        critical_defects = [d for d in defects if d.get("severity") in ("critical", "high")][:10]

        payload = {
            "pr": f"{repo}#{pr_number}",
            "risk_score": risk_score,
            "suite_results": suite_summary,
            "defect_severity_breakdown": dict(severity_counts),
            "critical_defects": critical_defects,
            "total_passed": sum(r.get("passed", 0) for r in test_results),
            "total_failed": sum(r.get("failed", 0) for r in test_results),
        }

        response = await self._llm.ainvoke(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps(payload, indent=2)},
            ]
        )

        report_md: str = response.content

        return AgentResult(
            agent=self.NAME,
            suite_type="reporting",
            priority="high",
            passed=1,
            failed=0,
            total_cases=1,
            metadata={
                "final_report": report_md,
                "total_defects": len(defects),
                "critical_count": severity_counts.get("critical", 0),
                "high_count": severity_counts.get("high", 0),
            },
        )
