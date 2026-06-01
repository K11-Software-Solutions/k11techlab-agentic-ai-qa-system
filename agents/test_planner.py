"""Test Planner Agent — Phase 1, Agent 4.

Generates a structured test plan (JSON) from the risk score, risk
factors, and PR diff using an LLM.  The plan drives Phase 2 dispatch.
"""
from __future__ import annotations

import json
import os

from langchain_openai import ChatOpenAI

from .base import AgentResult, BaseQAAgent

_SYSTEM = """You are a senior QA architect.
Given a PR diff, risk score, risk factors, and changed files, produce a
JSON test plan:
{
  "suites": [
    {
      "suite_type": "<api|playwright|performance|security|data|browser|accessibility|regression>",
      "priority": "<high|medium|low>",
      "focus_areas": ["<string>", ...],
      "estimated_duration_min": <int>
    },
    ...
  ],
  "summary": "<one-sentence description>"
}
Include only suites that are relevant given the changes.
Respond with ONLY the JSON."""


class TestPlannerAgent(BaseQAAgent):
    """LLM-based test plan generation from PR analysis."""

    NAME = "test_planner"
    TIMEOUT = 120

    def __init__(self, mcp_clients=None) -> None:
        super().__init__(mcp_clients)
        self._llm = ChatOpenAI(
            model=os.getenv("PLANNER_MODEL", "gpt-4o-mini"),
            temperature=0,
        )

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        pr_diff: str = state.get("pr_diff", "")
        risk_score: float = state.get("risk_score", 0.5)
        risk_factors: list[str] = state.get("risk_factors", [])
        changed_files: list[str] = state.get("changed_files", [])

        user_msg = (
            f"PR diff (first 3000 chars):\n{pr_diff[:3000]}\n\n"
            f"Risk score: {risk_score:.2f}\n"
            f"Risk factors:\n{json.dumps(risk_factors, indent=2)}\n\n"
            f"Changed files:\n{json.dumps(changed_files)}"
        )

        response = await self._llm.ainvoke(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )

        try:
            plan = json.loads(response.content)
        except json.JSONDecodeError:
            plan = {
                "suites": [{"suite_type": "api", "priority": "medium", "focus_areas": [], "estimated_duration_min": 10}],
                "summary": "Default plan (LLM parse error)",
            }

        return AgentResult(
            agent=self.NAME,
            suite_type=suite.get("suite_type", "test_planning"),
            priority="high",
            passed=1,
            failed=0,
            total_cases=1,
            metadata={
                "test_plan": plan,
                "suite_count": len(plan.get("suites", [])),
            },
        )
