"""Regression Agent — Phase 2, Agent 12.

Re-runs the historical regression suite stored in the Knowledge Store
MCP and flags any test cases that now fail due to the PR's changes.
"""
from __future__ import annotations

import asyncio
import os

import httpx

from .base import AgentResult, BaseQAAgent


class RegressionAgent(BaseQAAgent):
    """Executes the regression test suite against the deployed build."""

    NAME = "regression_agent"
    TIMEOUT = 300

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        base_url: str = os.getenv("TARGET_BASE_URL", "http://localhost:8000")
        pr_number: int = state.get("pr_number", 0)
        changed_files: list[str] = state.get("changed_files", [])

        # Fetch relevant regression cases from Knowledge Store
        raw_cases = await self.call_mcp(
            "knowledge_store",
            "get_regression_suite",
            {
                "changed_files": changed_files,
                "max_cases": suite.get("max_cases", 50),
                "priority_filter": suite.get("priority", "high"),
            },
        )

        test_cases: list[dict] = raw_cases.get("cases", [])
        if not test_cases:
            return AgentResult(
                agent=self.NAME,
                suite_type="regression",
                priority=suite.get("priority", "medium"),
                passed=0,
                failed=0,
                total_cases=0,
                metadata={"skipped": "no regression cases matched changed files"},
            )

        passed = 0
        failed = 0
        defects: list[dict] = []

        async with httpx.AsyncClient(base_url=base_url, timeout=20.0) as client:
            tasks = [self._run_case(client, tc) for tc in test_cases]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for tc, result in zip(test_cases, results):
            if isinstance(result, Exception):
                failed += 1
                defects.append({
                    "title": f"Regression error: {tc.get('name', '?')}",
                    "severity": "high",
                    "detail": str(result),
                    "case_id": tc.get("id"),
                })
            elif result.get("ok"):
                passed += 1
            else:
                failed += 1
                defects.append({
                    "title": f"Regression failure: {tc.get('name', '?')}",
                    "severity": "high",
                    "detail": f"Expected {tc.get('expected_status')} got {result.get('status')}",
                    "case_id": tc.get("id"),
                    "status_code": result.get("status"),
                })

        return AgentResult(
            agent=self.NAME,
            suite_type="regression",
            priority=suite.get("priority", "high"),
            passed=passed,
            failed=failed,
            total_cases=len(test_cases),
            defects=defects,
            metadata={
                "cases_fetched": len(test_cases),
                "pr_number": pr_number,
            },
        )

    async def _run_case(self, client: httpx.AsyncClient, tc: dict) -> dict:
        method = tc.get("method", "GET").upper()
        path = tc.get("path", "/")
        payload = tc.get("payload")
        expected = tc.get("expected_status", 200)

        resp = await client.request(method, path, json=payload)
        return {"ok": resp.status_code == expected, "status": resp.status_code}
