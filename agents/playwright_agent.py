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
"""Playwright Agent — Phase 2, Agent 6.

Drives browser-based end-to-end tests through the Playwright MCP server.
Test scripts are generated from the test plan's focus areas and executed
remotely; results are normalised into an AgentResult.
"""
from __future__ import annotations

import os

from .base import AgentResult, BaseQAAgent


class PlaywrightAgent(BaseQAAgent):
    """Runs E2E browser tests via the Playwright MCP server."""

    NAME = "playwright_agent"
    TIMEOUT = 300

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        base_url: str = os.getenv("TARGET_BASE_URL", "http://localhost:3000")
        focus_areas: list[str] = suite.get("focus_areas", ["smoke"])

        # Build a list of scenarios from focus areas
        scenarios = self._build_scenarios(focus_areas, base_url)

        passed = 0
        failed = 0
        defects: list[dict] = []

        for scenario in scenarios:
            raw = await self.call_mcp(
                "playwright",
                "run_scenario",
                {
                    "url": base_url,
                    "steps": scenario["steps"],
                    "timeout_ms": 30_000,
                    "screenshot_on_failure": True,
                },
            )

            if raw.get("status") == "passed":
                passed += 1
            else:
                failed += 1
                defects.append({
                    "title": f"E2E failure: {scenario['name']}",
                    "severity": "high",
                    "detail": raw.get("error", "Unknown failure"),
                    "screenshot": raw.get("screenshot_url"),
                    "scenario": scenario["name"],
                })

        return AgentResult(
            agent=self.NAME,
            suite_type="playwright",
            priority=suite.get("priority", "high"),
            passed=passed,
            failed=failed,
            total_cases=passed + failed,
            defects=defects,
            metadata={"base_url": base_url, "scenarios": [s["name"] for s in scenarios]},
        )

    # ------------------------------------------------------------------ #
    def _build_scenarios(self, focus_areas: list[str], base_url: str) -> list[dict]:
        """Map focus areas to Playwright step sequences."""
        scenarios = []
        for area in focus_areas:
            key = area.lower().replace(" ", "_")
            steps = _SCENARIO_LIBRARY.get(key, _DEFAULT_STEPS(base_url))
            scenarios.append({"name": area, "steps": steps})
        if not scenarios:
            scenarios.append({"name": "smoke", "steps": _DEFAULT_STEPS(base_url)})
        return scenarios


def _DEFAULT_STEPS(base_url: str) -> list[dict]:
    return [
        {"action": "goto", "url": base_url},
        {"action": "waitForLoadState", "state": "networkidle"},
        {"action": "screenshot"},
    ]


_SCENARIO_LIBRARY: dict[str, list[dict]] = {
    "login": [
        {"action": "goto", "url": "/login"},
        {"action": "fill", "selector": "#username", "value": "testuser"},
        {"action": "fill", "selector": "#password", "value": "Test@1234"},
        {"action": "click", "selector": "button[type=submit]"},
        {"action": "waitForURL", "url": "/dashboard"},
    ],
    "checkout": [
        {"action": "goto", "url": "/cart"},
        {"action": "click", "selector": "#checkout-btn"},
        {"action": "waitForSelector", "selector": "#order-confirmation"},
    ],
}
