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
"""Base class for all K11tech Agentic AI QA agents."""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Uniform result container returned by every QA agent."""

    agent: str
    suite_type: str
    priority: str = "medium"
    passed: int = 0
    failed: int = 0
    total_cases: int = 0
    duration_s: float = 0.0
    defects: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    error: str | None = None

    # ------------------------------------------------------------------ #
    @property
    def success(self) -> bool:
        return self.error is None and self.failed == 0

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "suite_type": self.suite_type,
            "priority": self.priority,
            "passed": self.passed,
            "failed": self.failed,
            "total_cases": self.total_cases,
            "duration_s": self.duration_s,
            "defects": self.defects,
            "metadata": self.metadata,
            "error": self.error,
            "success": self.success,
        }


class MCPError(Exception):
    """Raised when an MCP tool call fails."""


class BaseQAAgent(ABC):
    """
    Abstract base for all 14 K11 QA agents.

    Sub-classes implement ``execute(state, suite) -> AgentResult``.
    The public ``run()`` method wraps execute with:
      - asyncio timeout (TIMEOUT seconds)
      - tenacity retry (RETRIES attempts, exponential back-off)
    """

    NAME: str = "base_agent"
    TIMEOUT: int = 300   # seconds per run attempt
    RETRIES: int = 3

    def __init__(self, mcp_clients: dict[str, Any] | None = None) -> None:
        self._mcp: dict[str, Any] = mcp_clients or {}
        self._log = logging.getLogger(f"agents.{self.NAME}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def run(self, state: dict, suite: dict) -> AgentResult:
        """Execute with timeout + retry; always returns AgentResult."""
        t0 = time.monotonic()

        @retry(
            stop=stop_after_attempt(self.RETRIES),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type(MCPError),
            reraise=True,
        )
        async def _attempt() -> AgentResult:
            return await asyncio.wait_for(
                self.execute(state, suite),
                timeout=self.TIMEOUT,
            )

        try:
            result = await _attempt()
        except asyncio.TimeoutError:
            result = AgentResult(
                agent=self.NAME,
                suite_type=suite.get("suite_type", "unknown"),
                error=f"Timed out after {self.TIMEOUT}s",
            )
        except Exception as exc:  # noqa: BLE001
            self._log.exception("Agent %s failed", self.NAME)
            result = AgentResult(
                agent=self.NAME,
                suite_type=suite.get("suite_type", "unknown"),
                error=str(exc),
            )

        result.duration_s = time.monotonic() - t0
        return result

    # ------------------------------------------------------------------ #
    # Abstract method
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def execute(self, state: dict, suite: dict) -> AgentResult:
        """Agent-specific logic.  Must be implemented by every sub-class."""

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    async def call_mcp(self, server: str, tool: str, args: dict) -> dict:
        """
        Call ``tool`` on the named MCP server.

        Raises MCPError on failure so tenacity can retry.
        """
        client = self._mcp.get(server)
        if client is None:
            raise MCPError(f"MCP server '{server}' not registered")
        try:
            return await client.call_tool(tool, args)
        except Exception as exc:
            raise MCPError(f"{server}.{tool} failed: {exc}") from exc

    def result_from_mcp(
        self,
        suite: dict,
        raw: dict,
        *,
        defect_key: str = "failures",
    ) -> AgentResult:
        """
        Convert a raw MCP response dict into an AgentResult.

        Expects the MCP response to have keys:
          passed, failed, total (or total_cases), defects (list)
        """
        defects = raw.get("defects") or raw.get(defect_key) or []
        total = raw.get("total") or raw.get("total_cases") or (
            raw.get("passed", 0) + raw.get("failed", 0)
        )
        return AgentResult(
            agent=self.NAME,
            suite_type=suite.get("suite_type", self.NAME),
            priority=suite.get("priority", "medium"),
            passed=raw.get("passed", 0),
            failed=raw.get("failed", 0),
            total_cases=total,
            defects=defects,
            metadata={k: v for k, v in raw.items() if k not in
                       {"passed", "failed", "total", "total_cases", "defects", defect_key}},
        )
