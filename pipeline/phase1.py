"""
Phase 1 — Repository Analysis Subgraph
Nodes: fetch_pr_context, retrieve_knowledge (parallel) → score_risk → generate_test_plan
"""

from __future__ import annotations
import json
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, START, END

from .state import CIPipelineState
from .mcp_clients import github_mcp, knowledge_store_mcp

logger = logging.getLogger(__name__)

# ── LLM instances ────────────────────────────────────────────────────────────

_risk_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
_plan_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

_RISK_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a senior QA risk assessment expert. Analyse the PR diff and return "
    "valid JSON only: {{\"risk_score\": <float 0.0-1.0>, \"risk_factors\": [<str>]}}.\n"
     "risk_score guidance: 0.0-0.3=low, 0.4-0.6=medium, 0.7-0.84=high, 0.85+=critical.\n"
     "Risk factors to look for: auth changes, SQL queries, payment logic, "
     "security config, public API changes, database migrations, dependency updates."),
    ("human", "PR DIFF:\n{pr_diff}\n\nKNOWLEDGE CONTEXT:\n{context}"),
])

_PLAN_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a test planning expert. Given risk factors and changed files, "
    "return valid JSON: {{\"suites\": [{{\"type\": <str>, \"priority\": <high|medium|low>, "
    "\"cases\": [<str>], \"focus_areas\": [<str>]}}], \"rationale\": <str>}}.\n"
     "Available suite types: api, playwright, performance, security, data, "
     "cross_browser, a11y, regression.\n"
     "Select only relevant suites. High-risk PRs should include security and api suites."),
    ("human",
     "RISK SCORE: {risk_score}\nRISK FACTORS: {risk_factors}\n"
     "CHANGED FILES: {changed_files}\nKNOWLEDGE CONTEXT: {context}"),
])


# ── Node functions ────────────────────────────────────────────────────────────

async def fetch_pr_context(state: CIPipelineState) -> dict:
    """Call GitHub MCP to get file metadata and commit history."""
    try:
        result = await github_mcp.call_tool("get_pr_files", {
            "repo": state["repo_name"],
            "pr_number": state["pr_number"],
        })
        changed_files = [f["filename"] for f in result.get("files", [])]
        logger.info("Phase1: fetched %d changed files", len(changed_files))
        return {"changed_files": changed_files}
    except Exception as exc:
        logger.warning("fetch_pr_context failed: %s — using diff-parsed files", exc)
        # Fallback: parse changed files from the diff
        changed_files = _parse_files_from_diff(state["pr_diff"])
        return {"changed_files": changed_files}


async def retrieve_knowledge(state: CIPipelineState) -> dict:
    """Call Knowledge Store MCP to retrieve relevant documentation chunks."""
    try:
        result = await knowledge_store_mcp.call_tool("search_knowledge", {
            "query": state["pr_diff"][:2000],
            "top_k": 5,
        })
        chunks = [item["content"] for item in result.get("results", [])]
        logger.info("Phase1: retrieved %d knowledge chunks", len(chunks))
        return {"retrieval_context": chunks}
    except Exception as exc:
        logger.warning("retrieve_knowledge failed: %s", exc)
        return {"retrieval_context": []}


async def score_risk(state: CIPipelineState) -> dict:
    """LLM node: assess risk of the PR and produce a risk_score + risk_factors."""
    context = "\n".join(state.get("retrieval_context", [])[:3])
    try:
        resp = await (
            _RISK_PROMPT | _risk_llm
        ).ainvoke({
            "pr_diff": state["pr_diff"][:4000],
            "context": context or "No additional context available.",
        })
        data = _parse_json(resp.content)
        risk_score = float(data.get("risk_score", 0.5))
        risk_factors = data.get("risk_factors", [])
        logger.info("Phase1: risk_score=%.2f factors=%s", risk_score, risk_factors)
        return {"risk_score": risk_score, "risk_factors": risk_factors}
    except Exception as exc:
        logger.error("score_risk failed: %s", exc)
        return {"risk_score": 0.5, "risk_factors": ["risk assessment failed"]}


async def generate_test_plan(state: CIPipelineState) -> dict:
    """LLM node: convert risk factors into a structured test plan."""
    context = "\n".join(state.get("retrieval_context", [])[:3])
    try:
        resp = await (
            _PLAN_PROMPT | _plan_llm
        ).ainvoke({
            "risk_score": state["risk_score"],
            "risk_factors": state["risk_factors"],
            "changed_files": state.get("changed_files", [])[:20],
            "context": context or "No additional context available.",
        })
        plan = _parse_json(resp.content)
        plan_text = _format_plan_text(plan)
        logger.info("Phase1: generated %d test suites", len(plan.get("suites", [])))
        return {"test_plan": plan, "test_plan_text": plan_text}
    except Exception as exc:
        logger.error("generate_test_plan failed: %s", exc)
        default_plan = {"suites": [{"type": "api", "priority": "high", "cases": [], "focus_areas": []}]}
        return {"test_plan": default_plan, "test_plan_text": "Fallback: API testing only."}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    """Extract JSON from LLM response (may contain markdown code fences)."""
    import re
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def _parse_files_from_diff(diff: str) -> list[str]:
    """Fallback: extract changed file paths from a unified diff."""
    import re
    return re.findall(r"^(?:\+\+\+|---) (?:a/|b/)(.+)$", diff, re.MULTILINE)


def _format_plan_text(plan: dict) -> str:
    suites = plan.get("suites", [])
    lines = [f"Test plan: {len(suites)} suite(s)"]
    for s in suites:
        lines.append(f"  [{s.get('priority','?').upper()}] {s.get('type','?')} — {len(s.get('cases',[]))} cases")
    if plan.get("rationale"):
        lines.append(f"Rationale: {plan['rationale']}")
    return "\n".join(lines)


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_phase1() -> Any:
    builder = StateGraph(CIPipelineState)
    builder.add_node("fetch_pr_context",  fetch_pr_context)
    builder.add_node("retrieve_knowledge", retrieve_knowledge)
    builder.add_node("score_risk",         score_risk)
    builder.add_node("generate_test_plan", generate_test_plan)

    # fetch_pr_context and retrieve_knowledge run in parallel from START
    builder.add_edge(START, "fetch_pr_context")
    builder.add_edge(START, "retrieve_knowledge")
    # both fan-in to score_risk
    builder.add_edge("fetch_pr_context",   "score_risk")
    builder.add_edge("retrieve_knowledge", "score_risk")
    builder.add_edge("score_risk",         "generate_test_plan")
    builder.add_edge("generate_test_plan", END)

    return builder.compile()


phase1_app = build_phase1()
