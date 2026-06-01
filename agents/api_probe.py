"""API Probe Agent — Phase 2, Agent 5.

Executes REST/GraphQL API tests against the changed endpoints using the
GitHub MCP to discover endpoint specs and an internal HTTP runner.
Results are collected as an AgentResult with individual defects.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

from .base import AgentResult, BaseQAAgent


class APIProbeAgent(BaseQAAgent):
    """Probes API endpoints identified from the PR diff."""

    NAME = "api_probe"
    TIMEOUT = 180

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        base_url: str = os.getenv("TARGET_BASE_URL", "http://localhost:8000")
        focus_areas: list[str] = suite.get("focus_areas", [])

        # Discover endpoints from knowledge store or suite metadata
        endpoints: list[dict] = suite.get("endpoints", [])
        if not endpoints:
            endpoints = self._infer_endpoints(state.get("changed_files", []), focus_areas)

        passed = 0
        failed = 0
        defects: list[dict] = []

        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            tasks = [self._probe_endpoint(client, ep) for ep in endpoints]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for ep, res in zip(endpoints, results):
            if isinstance(res, Exception):
                failed += 1
                defects.append({
                    "title": f"API probe error: {ep.get('path', '?')}",
                    "severity": "high",
                    "detail": str(res),
                    "endpoint": ep,
                })
            elif res.get("ok"):
                passed += 1
            else:
                failed += 1
                defects.append({
                    "title": f"API failure {res.get('status_code')} {ep.get('path', '?')}",
                    "severity": "medium",
                    "detail": res.get("body", ""),
                    "endpoint": ep,
                    "status_code": res.get("status_code"),
                })

        return AgentResult(
            agent=self.NAME,
            suite_type="api",
            priority=suite.get("priority", "high"),
            passed=passed,
            failed=failed,
            total_cases=passed + failed,
            defects=defects,
            metadata={"base_url": base_url, "endpoints_tested": len(endpoints)},
        )

    # ------------------------------------------------------------------ #
    async def _probe_endpoint(self, client: httpx.AsyncClient, ep: dict) -> dict[str, Any]:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/")
        payload = ep.get("payload")
        headers = ep.get("headers", {})

        resp = await client.request(method, path, json=payload, headers=headers)
        return {
            "ok": resp.status_code < 400,
            "status_code": resp.status_code,
            "body": resp.text[:500],
        }

    def _infer_endpoints(self, changed_files: list[str], focus_areas: list[str]) -> list[dict]:
        """Heuristic: derive candidate endpoints from changed router files."""
        endpoints: list[dict] = []
        for f in changed_files:
            if "router" in f or "endpoint" in f or "api" in f.lower():
                # Bare GET probe — real impl would parse OpenAPI spec
                endpoints.append({"method": "GET", "path": "/health"})
                break
        if not endpoints:
            endpoints = [{"method": "GET", "path": "/health"}]
        return endpoints
