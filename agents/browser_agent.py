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
"""Cross-Browser Agent — Phase 2, Agent 10.

Runs the same Playwright scenarios across multiple browser engines
(Chromium, Firefox, WebKit) and flags cross-browser inconsistencies.
"""
from __future__ import annotations

import os

from .base import AgentResult, BaseQAAgent

_BROWSERS = ["chromium", "firefox", "webkit"]


class CrossBrowserAgent(BaseQAAgent):
    """Validates UI consistency across Chromium, Firefox, and WebKit."""

    NAME = "browser_agent"
    TIMEOUT = 300

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        base_url: str = os.getenv("TARGET_BASE_URL", "http://localhost:3000")
        focus_areas: list[str] = suite.get("focus_areas", ["homepage"])
        browsers: list[str] = suite.get("browsers", _BROWSERS)

        passed = 0
        failed = 0
        defects: list[dict] = []
        browser_results: dict[str, dict] = {}

        for browser in browsers:
            raw = await self.call_mcp(
                "playwright",
                "run_cross_browser",
                {
                    "browser": browser,
                    "url": base_url,
                    "focus_areas": focus_areas,
                    "screenshot": True,
                },
            )
            browser_results[browser] = raw
            if raw.get("status") == "passed":
                passed += 1
            else:
                failed += 1
                defects.append({
                    "title": f"Cross-browser failure on {browser}",
                    "severity": "medium",
                    "detail": raw.get("error", ""),
                    "browser": browser,
                    "screenshot": raw.get("screenshot_url"),
                })

        # Check for visual regressions between browsers
        screenshots = {b: r.get("screenshot_url") for b, r in browser_results.items() if r.get("screenshot_url")}
        if len(screenshots) >= 2:
            compare_raw = await self.call_mcp(
                "playwright",
                "compare_screenshots",
                {"screenshots": screenshots, "threshold": 0.05},
            )
            diffs = compare_raw.get("differences", [])
            for diff in diffs:
                defects.append({
                    "title": f"Visual diff: {diff.get('browser_a')} vs {diff.get('browser_b')}",
                    "severity": "low",
                    "detail": f"Pixel diff ratio: {diff.get('diff_ratio', 0):.2%}",
                })

        return AgentResult(
            agent=self.NAME,
            suite_type="browser",
            priority=suite.get("priority", "medium"),
            passed=passed,
            failed=failed,
            total_cases=len(browsers),
            defects=defects,
            metadata={"browsers_tested": browsers, "base_url": base_url},
        )
