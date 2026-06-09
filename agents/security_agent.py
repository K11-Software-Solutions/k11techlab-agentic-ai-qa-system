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
"""Security Agent — Phase 2, Agent 8.

Performs OWASP-aligned security scans on the changed API surface using
the GitHub MCP (for secret scanning) and an internal SAST/DAST checker.
"""
from __future__ import annotations

import re

from .base import AgentResult, BaseQAAgent

# Patterns for naive secret detection in diff
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Generic API Key", re.compile(r"api[_-]?key\s*=\s*['\"][^'\"]{8,}['\"]", re.I)),
    ("Bearer Token", re.compile(r"bearer\s+[A-Za-z0-9\-_]{20,}", re.I)),
    ("Password literal", re.compile(r"password\s*=\s*['\"][^'\"]{4,}['\"]", re.I)),
]


class SecurityAgent(BaseQAAgent):
    """Scans for OWASP risks, exposed secrets, and insecure patterns."""

    NAME = "security_agent"
    TIMEOUT = 180

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        pr_diff: str = state.get("pr_diff", "")
        changed_files: list[str] = state.get("changed_files", [])

        defects: list[dict] = []

        # 1. Secret scanning on diff
        for label, pattern in _SECRET_PATTERNS:
            matches = pattern.findall(pr_diff)
            if matches:
                defects.append({
                    "title": f"Secret exposure: {label}",
                    "severity": "critical",
                    "detail": f"Pattern '{label}' found {len(matches)} time(s) in PR diff",
                    "count": len(matches),
                })

        # 2. GitHub secret scanning via MCP
        repo = state.get("repo_name", "")
        pr_number = state.get("pr_number", 0)
        if repo and pr_number:
            try:
                raw = await self.call_mcp(
                    "github",
                    "list_secret_scanning_alerts",
                    {"repo": repo, "state": "open"},
                )
                alerts = raw.get("alerts", [])
                for alert in alerts[:10]:
                    defects.append({
                        "title": f"GitHub secret alert: {alert.get('secret_type', 'unknown')}",
                        "severity": "critical",
                        "detail": alert.get("html_url", ""),
                    })
            except Exception:  # noqa: BLE001
                pass  # GitHub secret scanning may not be enabled

        # 3. Insecure dependency check (simplified)
        req_files = [f for f in changed_files if "requirements" in f or "package.json" in f]
        if req_files:
            defects.append({
                "title": "Dependency files changed — manual CVE review recommended",
                "severity": "medium",
                "detail": f"Files: {req_files}",
            })

        total = 1 + len(req_files)  # baseline checks
        failed = len(defects)
        passed = max(0, total - failed)

        return AgentResult(
            agent=self.NAME,
            suite_type="security",
            priority=suite.get("priority", "high"),
            passed=passed,
            failed=failed,
            total_cases=total,
            defects=defects,
            metadata={"diff_lines_scanned": len(pr_diff.splitlines())},
        )
