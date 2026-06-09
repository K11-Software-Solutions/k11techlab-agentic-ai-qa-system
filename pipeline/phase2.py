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
"""
Phase 2 — Parallel Agent Execution Subgraph
Dispatches up to 8 specialist test agents in parallel via LangGraph Send API.
Each agent calls its designated MCP server, runs tests, writes results via reducers.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.types import Send

from .state import CIPipelineState
from .mcp_clients import (
    github_mcp, playwright_mcp, k6_mcp,
    postgres_mcp, knowledge_store_mcp,
)

logger = logging.getLogger(__name__)

# ── Agent-to-MCP mapping ─────────────────────────────────────────────────────

AGENT_MAP: dict[str, tuple[str, str]] = {
    "api":          ("api_agent",          "github_mcp"),
    "playwright":   ("playwright_agent",   "playwright_mcp"),
    "performance":  ("perf_agent",         "k6_mcp"),
    "security":     ("security_agent",     "github_mcp"),
    "data":         ("data_agent",         "postgres_mcp"),
    "cross_browser":("browser_agent",      "playwright_mcp"),
    "a11y":         ("a11y_agent",         "playwright_mcp"),
    "regression":   ("regression_agent",   "github_mcp"),
}

MCP_CLIENTS = {
    "github_mcp":         github_mcp,
    "playwright_mcp":     playwright_mcp,
    "k6_mcp":             k6_mcp,
    "postgres_mcp":       postgres_mcp,
    "knowledge_store_mcp":knowledge_store_mcp,
}

AGENT_TIMEOUT = 300  # seconds per agent


# ── Dispatch function ─────────────────────────────────────────────────────────

def dispatch_phase2(state: CIPipelineState) -> list[Send]:
    """
    Route function: returns one Send per test suite in the test_plan.
    Each Send targets the appropriate agent node with a copy of relevant state.
    """
    sends: list[Send] = []
    for suite in state["test_plan"].get("suites", []):
        suite_type = suite.get("type")
        mapping = AGENT_MAP.get(suite_type)
        if not mapping:
            logger.warning("No agent for suite type '%s' — skipping", suite_type)
            continue
        node_name, _ = mapping
        sends.append(Send(
            node=node_name,
            arg={
                "run_id":    state["run_id"],
                "repo_name": state["repo_name"],
                "pr_number": state["pr_number"],
                "pr_diff":   state["pr_diff"],
                "suite":     suite,
                # pass reduced state to agents (avoid large diffs in every branch)
                "changed_files": state.get("changed_files", []),
                "risk_score":    state.get("risk_score", 0.5),
            },
        ))
    logger.info("Phase2: dispatching %d agents", len(sends))
    return sends


# ── Agent factory ─────────────────────────────────────────────────────────────

def _make_agent(agent_type: str, mcp_name: str):
    """
    Factory: returns an async node function for a specific test agent.
    The node function receives a per-agent dict (not full CIPipelineState)
    and returns partial state updates (test_results, defects, errors).
    """
    mcp_client = MCP_CLIENTS[mcp_name]

    async def _agent_node(state: dict) -> dict:
        suite = state["suite"]
        run_id = state["run_id"]
        try:
            result = await asyncio.wait_for(
                _run_agent(agent_type, mcp_client, state, suite),
                timeout=AGENT_TIMEOUT,
            )
            defects = result.pop("defects", [])
            return {
                "test_results": [result],
                "defects":      defects,
                "errors":       [],
            }
        except asyncio.TimeoutError:
            msg = f"{agent_type} timed out after {AGENT_TIMEOUT}s"
            logger.error(msg)
            return {"test_results": [], "defects": [], "errors": [msg]}
        except Exception as exc:
            msg = f"{agent_type} failed: {exc}"
            logger.error(msg)
            return {"test_results": [], "defects": [], "errors": [msg]}

    _agent_node.__name__ = f"{agent_type}_node"
    return _agent_node


async def _run_agent(agent_type: str, mcp_client, state: dict, suite: dict) -> dict:
    """Dispatch to the agent-specific runner."""
    runners = {
        "api":          _run_api_agent,
        "playwright":   _run_playwright_agent,
        "performance":  _run_perf_agent,
        "security":     _run_security_agent,
        "data":         _run_data_agent,
        "cross_browser":_run_browser_agent,
        "a11y":         _run_a11y_agent,
        "regression":   _run_regression_agent,
    }
    runner = runners.get(agent_type, _run_generic_agent)
    return await runner(mcp_client, state, suite)


# ── Per-agent runners ─────────────────────────────────────────────────────────

async def _run_api_agent(mcp, state, suite) -> dict:
    result = await mcp.call_tool("run_api_tests", {
        "repo":       state["repo_name"],
        "pr_number":  state["pr_number"],
        "focus_areas":suite.get("focus_areas", []),
        "cases":      suite.get("cases", []),
    })
    return _normalise_result("api", suite, result)


async def _run_playwright_agent(mcp, state, suite) -> dict:
    result = await mcp.call_tool("run_e2e_tests", {
        "repo":      state["repo_name"],
        "pr_diff":   state["pr_diff"][:1000],
        "focus_areas":suite.get("focus_areas", []),
        "headless":  True,
        "browsers":  ["chromium"],
    })
    return _normalise_result("playwright", suite, result)


async def _run_perf_agent(mcp, state, suite) -> dict:
    result = await mcp.call_tool("run_load_test", {
        "repo":          state["repo_name"],
        "vus":           10,
        "duration":      "30s",
        "focus_areas":   suite.get("focus_areas", []),
        "thresholds":    {"http_req_duration": ["p95<500"], "http_req_failed": ["rate<0.01"]},
    })
    return _normalise_result("performance", suite, result)


async def _run_security_agent(mcp, state, suite) -> dict:
    result = await mcp.call_tool("run_code_scanning", {
        "repo":      state["repo_name"],
        "pr_number": state["pr_number"],
        "rules":     ["sql-injection", "xss", "auth-bypass", "secret-leak"],
    })
    return _normalise_result("security", suite, result)


async def _run_data_agent(mcp, state, suite) -> dict:
    result = await mcp.call_tool("run_data_validation", {
        "repo":        state["repo_name"],
        "focus_areas": suite.get("focus_areas", []),
        "pr_diff":     state["pr_diff"][:1000],
    })
    return _normalise_result("data", suite, result)


async def _run_browser_agent(mcp, state, suite) -> dict:
    result = await mcp.call_tool("run_e2e_tests", {
        "repo":       state["repo_name"],
        "pr_diff":    state["pr_diff"][:1000],
        "focus_areas":suite.get("focus_areas", []),
        "headless":   True,
        "browsers":   ["chromium", "firefox", "webkit"],
    })
    return _normalise_result("cross_browser", suite, result)


async def _run_a11y_agent(mcp, state, suite) -> dict:
    result = await mcp.call_tool("run_accessibility_audit", {
        "repo":        state["repo_name"],
        "wcag_level":  "AA",
        "focus_areas": suite.get("focus_areas", []),
    })
    return _normalise_result("a11y", suite, result)


async def _run_regression_agent(mcp, state, suite) -> dict:
    result = await mcp.call_tool("run_regression_suite", {
        "repo":        state["repo_name"],
        "pr_number":   state["pr_number"],
        "base_branch": "main",
        "focus_areas": suite.get("focus_areas", []),
    })
    return _normalise_result("regression", suite, result)


async def _run_generic_agent(mcp, state, suite) -> dict:
    return _normalise_result(suite.get("type", "unknown"), suite, {})


def _normalise_result(agent_type: str, suite: dict, raw: dict) -> dict:
    """Normalise MCP result into a consistent test result shape."""
    defects = []
    for issue in raw.get("issues", []) + raw.get("findings", []):
        defects.append({
            "agent":       agent_type,
            "title":       issue.get("title", issue.get("message", "Unknown issue")),
            "detail":      issue.get("detail", issue.get("description", "")),
            "severity":    issue.get("severity", "medium").lower(),
            "file":        issue.get("file", ""),
            "line":        issue.get("line"),
        })
    return {
        "agent":       agent_type,
        "suite_type":  suite.get("type"),
        "priority":    suite.get("priority", "medium"),
        "passed":      int(raw.get("passed", raw.get("tests_passed", 0))),
        "failed":      int(raw.get("failed", raw.get("tests_failed", 0))),
        "total_cases": int(raw.get("total", raw.get("total_cases", 0))),
        "duration_s":  float(raw.get("duration_s", 0)),
        "defects":     defects,
        "raw":         raw,
    }


# ── Aggregate node ────────────────────────────────────────────────────────────

async def aggregate_phase2_results(state: CIPipelineState) -> dict:
    """
    Fan-in node: all agent nodes converge here.
    Reducers have already merged test_results, defects, errors via operator.add.
    This node just logs a summary and returns unchanged state (no writes needed).
    """
    total   = sum(r.get("total_cases", 0) for r in state["test_results"])
    passed  = sum(r.get("passed", 0) for r in state["test_results"])
    n_defects = len(state["defects"])
    n_errors  = len(state["errors"])
    logger.info(
        "Phase2 complete: %d/%d tests passed, %d defects, %d agent errors",
        passed, total, n_defects, n_errors,
    )
    return {}


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_phase2() -> Any:
    builder = StateGraph(CIPipelineState)

    # Dispatch pass-through node (required as source for add_conditional_edges)
    builder.add_node("dispatch", lambda s: {})
    builder.add_node("aggregate", aggregate_phase2_results)

    # Register all 8 agent nodes
    for suite_type, (node_name, mcp_name) in AGENT_MAP.items():
        builder.add_node(node_name, _make_agent(suite_type, mcp_name))
        builder.add_edge(node_name, "aggregate")

    builder.set_entry_point("dispatch")
    builder.add_conditional_edges(
        "dispatch",
        dispatch_phase2,
        [node_name for node_name, _ in AGENT_MAP.values()],
    )
    builder.add_edge("aggregate", END)

    return builder.compile()


phase2_app = build_phase2()
