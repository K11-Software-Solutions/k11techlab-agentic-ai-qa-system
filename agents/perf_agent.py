"""Performance Agent — Phase 2, Agent 7.

Executes load and performance tests using the k6 MCP server.
Derives target endpoints and thresholds from the test plan suite.
"""
from __future__ import annotations

import os

from .base import AgentResult, BaseQAAgent

# Default k6 thresholds
_DEFAULT_THRESHOLDS = {
    "http_req_duration": "p(95)<2000",   # 95th percentile < 2 s
    "http_req_failed": "rate<0.01",       # error rate < 1 %
}


class PerformanceAgent(BaseQAAgent):
    """Runs k6 load tests via the k6 MCP server."""

    NAME = "perf_agent"
    TIMEOUT = 300

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        base_url: str = os.getenv("TARGET_BASE_URL", "http://localhost:8000")
        focus_areas: list[str] = suite.get("focus_areas", [])
        thresholds: dict = suite.get("thresholds", _DEFAULT_THRESHOLDS)

        # Build a minimal k6 scenario
        scenarios = self._build_k6_scenarios(base_url, focus_areas)

        raw = await self.call_mcp(
            "k6",
            "run_load_test",
            {
                "scenarios": scenarios,
                "thresholds": thresholds,
                "vus": suite.get("vus", 10),
                "duration": suite.get("duration", "30s"),
            },
        )

        passed_checks: int = raw.get("checks_passed", 0)
        failed_checks: int = raw.get("checks_failed", 0)
        threshold_violations: list[dict] = raw.get("threshold_violations", [])

        defects = [
            {
                "title": f"Performance threshold violated: {v.get('metric')}",
                "severity": "high",
                "detail": f"Expected {v.get('threshold')}, got {v.get('actual')}",
                "metric": v.get("metric"),
            }
            for v in threshold_violations
        ]

        return AgentResult(
            agent=self.NAME,
            suite_type="performance",
            priority=suite.get("priority", "medium"),
            passed=passed_checks,
            failed=failed_checks + len(threshold_violations),
            total_cases=passed_checks + failed_checks,
            defects=defects,
            metadata={
                "p95_duration_ms": raw.get("http_req_duration_p95"),
                "error_rate": raw.get("http_req_failed_rate"),
                "rps": raw.get("http_reqs_per_second"),
                "vus": suite.get("vus", 10),
                "duration": suite.get("duration", "30s"),
            },
        )

    def _build_k6_scenarios(self, base_url: str, focus_areas: list[str]) -> list[dict]:
        paths = ["/api/v1/health"] + [f"/api/v1/{a.lower().replace(' ', '_')}" for a in focus_areas[:3]]
        return [{"name": f"load_{i}", "url": base_url + p, "method": "GET"} for i, p in enumerate(paths)]
