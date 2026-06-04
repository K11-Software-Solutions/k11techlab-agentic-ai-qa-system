"""Risk Assessor Agent — Phase 1, Agent 1.

Scores PR risk (0-1) using an LLM that analyses the diff, changed files,
and historical defect patterns retrieved from the Knowledge Store MCP.
"""
from __future__ import annotations

import json
import os

from langchain_openai import ChatOpenAI

from .base import AgentResult, BaseQAAgent

_SYSTEM = """You are a senior software quality engineer.
Given a pull-request diff and a list of changed files, output a JSON object:
{
  "risk_score": <float 0-1>,
  "risk_factors": [<string>, ...]
}
risk_score 0 = trivial change, 1 = extremely high risk.
risk_factors lists concrete reasons (max 8).
Respond with ONLY the JSON — no markdown, no explanation."""


class RiskAssessorAgent(BaseQAAgent):
    """LLM-based risk scoring for a PR diff."""

    NAME = "risk_assessor"
    TIMEOUT = 120

    def __init__(self, mcp_clients=None) -> None:
        super().__init__(mcp_clients)
        self._llm = ChatOpenAI(
            model=os.getenv("RISK_MODEL", "gpt-4o-mini"),
            temperature=0,
        )

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        pr_diff: str = state.get("pr_diff", "")
        changed_files: list[str] = state.get("changed_files", [])
        retrieval_context: list[str] = state.get("retrieval_context", [])

        context_block = "\n".join(retrieval_context[:5]) if retrieval_context else "none"

        user_msg = (
            f"PR diff (first 4000 chars):\n{pr_diff[:4000]}\n\n"
            f"Changed files:\n{json.dumps(changed_files)}\n\n"
            f"Historical defect context:\n{context_block}"
        )

        response = await self._llm.ainvoke(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )

        try:
            data = json.loads(response.content)
            risk_score: float = float(data.get("risk_score", 0.5))
            risk_factors: list[str] = data.get("risk_factors", [])
        except (json.JSONDecodeError, ValueError):
            risk_score = 0.5
            risk_factors = ["LLM response parse error — defaulting to medium risk"]

        return AgentResult(
            agent=self.NAME,
            suite_type=suite.get("suite_type", "risk_assessment"),
            priority="high",
            passed=1,
            failed=0,
            total_cases=1,
            metadata={
                "risk_score": risk_score,
                "risk_factors": risk_factors,
            },
        )
