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
"""
Phase 3 — Aggregation & Reporting Subgraph
Nodes: aggregate_results → (generate_report ∥ file_jira_tickets) → send_slack_report
"""

from __future__ import annotations
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, START, END

from .state import CIPipelineState
from .mcp_clients import jira_mcp, slack_mcp

logger = logging.getLogger(__name__)

_report_llm = ChatOpenAI(model="gpt-4o", temperature=0)

_REPORT_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a CI/CD QA reporting specialist. Write a concise, factual CI pipeline "
     "report in Markdown. Include: summary table, critical defects, agent errors, "
     "and a pass/fail verdict. Be factual — no speculation. Max 600 words."),
    ("human",
     "RUN ID: {run_id}\nREPO: {repo_name}\nPR: #{pr_number}\n\n"
     "SUMMARY:\n{summary}\n\nDEFECTS ({defect_count}):\n{defects}\n\n"
     "AGENT ERRORS:\n{errors}"),
])

MAX_JIRA_TICKETS = 10  # cap to avoid rate limit explosions


def _derive_verdict(
    *,
    total_cases: int,
    passed_cases: int,
    critical_count: int,
    high_count: int,
    risk_score: float,
    error_count: int,
) -> tuple[str, str]:
    """Derive a stable verdict, including a no-test fallback path."""
    if critical_count > 0:
        return "FAIL", "critical_defects_present"

    if total_cases > 0:
        pass_rate = passed_cases / total_cases
        if pass_rate >= 0.95 and high_count == 0:
            return "PASS", "meets_quality_threshold"
        if pass_rate >= 0.95 and high_count > 0:
            return "NEEDS_REVIEW", "high_severity_defects_present"
        return "FAIL", "test_pass_rate_below_threshold"

    if error_count > 0:
        # MCP/tooling outage: no test signal, but Phase 1 LLM risk score is available.
        # Use it as a proxy verdict rather than hard-failing every PR.
        if risk_score >= 0.7:
            return "FAIL", "agent_execution_failed_high_risk"
        if risk_score >= 0.4:
            return "NEEDS_REVIEW", "agent_execution_failed_medium_risk"
        return "PASS", "agent_execution_failed_low_risk"

    # No tests executed and no explicit errors recorded.
    if risk_score >= 0.7:
        return "NEEDS_REVIEW", "no_test_execution_high_risk"
    return "PASS", "no_test_execution_low_risk"


async def aggregate_results(state: CIPipelineState) -> dict:
    """Compute pass rates and severity breakdown from Phase 2 results."""
    results = state["test_results"]
    defects = state["defects"]

    total  = sum(r.get("total_cases", 0) for r in results)
    passed = sum(r.get("passed", 0) for r in results)
    failed = sum(r.get("failed", 0) for r in results)

    severity: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for d in defects:
        sev = d.get("severity", "medium").lower()
        severity[sev] = severity.get(sev, 0) + 1

    agents_run    = [r.get("agent") for r in results]
    agents_failed = [e.split()[0] for e in state["errors"]]

    verdict, verdict_reason = _derive_verdict(
        total_cases=total,
        passed_cases=passed,
        critical_count=severity.get("critical", 0),
        high_count=severity.get("high", 0),
        risk_score=float(state.get("risk_score", 0.0) or 0.0),
        error_count=len(state["errors"]),
    )

    summary = {
        "pass_rate":          round(passed / total, 3) if total else 0.0,
        "total_cases":        total,
        "passed":             passed,
        "failed":             failed,
        "defect_count":       len(defects),
        "severity":           severity,
        "agents_run":         agents_run,
        "agents_failed":      agents_failed,
        "error_count":        len(state["errors"]),
        "verdict":            verdict,
        "verdict_reason":     verdict_reason,
    }
    logger.info("Phase3: summary=%s", summary)
    return {"summary": summary}


async def generate_report(state: CIPipelineState) -> dict:
    """LLM node: produce a Markdown CI report from the summary and defects."""
    summary  = state["summary"] or {}
    defects  = state["defects"][:20]
    try:
        resp = await (_REPORT_PROMPT | _report_llm).ainvoke({
            "run_id":       state["run_id"],
            "repo_name":    state["repo_name"],
            "pr_number":    state["pr_number"],
            "summary":      _fmt_summary(summary),
            "defect_count": len(defects),
            "defects":      _fmt_defects(defects),
            "errors":       "\n".join(state["errors"]) or "None",
        })
        logger.info("Phase3: report generated (%d chars)", len(resp.content))
        return {"final_report": resp.content}
    except Exception as exc:
        logger.error("generate_report failed: %s", exc)
        fallback = _fallback_report(state)
        return {"final_report": fallback}


async def file_jira_tickets(state: CIPipelineState) -> dict:
    """Create Jira issues for critical defects (capped at MAX_JIRA_TICKETS)."""
    critical = [d for d in state["defects"] if d.get("severity") == "critical"]
    tickets: list[str] = []
    for defect in critical[:MAX_JIRA_TICKETS]:
        try:
            result = await jira_mcp.call_tool("create_issue", {
                "summary":     defect["title"][:255],
                "description": defect.get("detail", ""),
                "issue_type":  "Bug",
                "priority":    "Critical",
                "labels":      ["ci-pipeline", state["repo_name"].replace("/", "-")],
                "components":  [defect.get("agent", "qa-pipeline")],
            })
            tickets.append(result["issue_key"])
            logger.info("Jira ticket created: %s", result["issue_key"])
        except Exception as exc:
            logger.error("Failed to create Jira ticket for '%s': %s", defect["title"], exc)
    return {"jira_tickets": tickets}


async def send_slack_report(state: CIPipelineState) -> dict:
    """Post a summary notification to the #qa-reports Slack channel."""
    summary = state["summary"] or {}
    verdict = summary.get("verdict", "UNKNOWN")
    icon    = ":white_check_mark:" if verdict == "PASS" else ":x:"
    tickets = state.get("jira_tickets") or []

    text = (
        f"{icon} *CI Pipeline {verdict}* — `{state['repo_name']}` PR #{state['pr_number']}\n"
        f"Pass rate: {summary.get('pass_rate', 0):.1%} | "
        f"Defects: {summary.get('defect_count', 0)} | "
        f"Critical: {summary.get('severity', {}).get('critical', 0)}\n"
        f"Run ID: `{state['run_id']}`"
    )
    if tickets:
        text += f"\nJira tickets: {', '.join(tickets)}"
    if state.get("eval_passed") is False:
        text += "\n:warning: Quality gate FAILED — check LangSmith for eval scores."

    try:
        await slack_mcp.call_tool("post_message", {
            "channel": "#qa-reports",
            "text":    text,
            "mrkdwn":  True,
        })
        logger.info("Phase3: Slack notification sent")
        return {"slack_sent": True}
    except Exception as exc:
        logger.error("Slack notification failed: %s", exc)
        return {"slack_sent": False}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_summary(s: dict) -> str:
    lines = [
        f"Verdict: {s.get('verdict')}",
        f"Pass rate: {s.get('pass_rate', 0):.1%} ({s.get('passed')}/{s.get('total_cases')} cases)",
        f"Defects: {s.get('defect_count')} total — "
        f"critical={s['severity'].get('critical',0)}, high={s['severity'].get('high',0)}, "
        f"medium={s['severity'].get('medium',0)}, low={s['severity'].get('low',0)}",
        f"Agents: {s.get('agents_run')}",
    ]
    if s.get("agents_failed"):
        lines.append(f"Agent failures: {s['agents_failed']}")
    return "\n".join(lines)


def _fmt_defects(defects: list[dict]) -> str:
    if not defects:
        return "No defects found."
    lines = []
    for d in defects:
        lines.append(f"[{d.get('severity','?').upper()}] {d.get('agent','?')}: {d.get('title','?')}")
        if d.get("file"):
            lines.append(f"  File: {d['file']}:{d.get('line','')}")
    return "\n".join(lines)


def _fallback_report(state: CIPipelineState) -> str:
    s = state.get("summary") or {}
    return (
        f"# CI Report — {state['repo_name']} PR #{state['pr_number']}\n\n"
        f"**Run ID:** `{state['run_id']}`\n\n"
        f"**Verdict:** {s.get('verdict', 'UNKNOWN')}\n\n"
        f"**Pass rate:** {s.get('pass_rate', 0):.1%}\n\n"
        f"**Defects:** {s.get('defect_count', 0)}\n\n"
        f"*Report generation encountered an error — showing raw summary.*\n"
    )


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_phase3() -> Any:
    builder = StateGraph(CIPipelineState)
    builder.add_node("aggregate_results",  aggregate_results)
    builder.add_node("generate_report",    generate_report)
    builder.add_node("file_jira_tickets",  file_jira_tickets)
    builder.add_node("send_slack_report",  send_slack_report)

    builder.add_edge(START, "aggregate_results")
    # generate_report and file_jira_tickets run in parallel
    builder.add_edge("aggregate_results", "generate_report")
    builder.add_edge("aggregate_results", "file_jira_tickets")
    # both fan-in to send_slack_report
    builder.add_edge("generate_report",   "send_slack_report")
    builder.add_edge("file_jira_tickets", "send_slack_report")
    builder.add_edge("send_slack_report", END)

    return builder.compile()


phase3_app = build_phase3()
