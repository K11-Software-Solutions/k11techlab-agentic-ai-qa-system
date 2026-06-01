"""
CIPipelineState — shared TypedDict for the entire K11 TechLab QA pipeline.
All four phases (analysis, execution, reporting, evaluation) read/write this state.
"""

from __future__ import annotations
from typing import TypedDict, Optional, Annotated
import operator


class CIPipelineState(TypedDict):
    # ── Trigger inputs ───────────────────────────────────────────────
    run_id:      str          # unique per PR run, e.g. "run-abc123"
    pr_number:   int          # GitHub PR number
    repo_name:   str          # "org/repo"
    pr_diff:     str          # full unified diff text
    base_branch: str          # "main"
    author:      str          # PR author login

    # ── Phase 1 outputs ──────────────────────────────────────────────
    risk_score:         float          # 0.0–1.0
    risk_factors:       list[str]      # e.g. ["auth change", "sql query"]
    test_plan:          dict           # {suites: [{type, priority, cases}]}
    test_plan_text:     str            # human-readable summary
    retrieval_context:  list[str]      # chunks from Knowledge Store MCP
    changed_files:      list[str]      # list of changed file paths

    # ── HITL gate ────────────────────────────────────────────────────
    hitl_required:  bool              # True if risk_score >= 0.85
    hitl_decision:  Optional[str]     # "approve" | "reject" | None
    hitl_reviewer:  Optional[str]     # reviewer login
    hitl_comment:   Optional[str]     # reviewer note

    # ── Phase 2 outputs (concurrent writes — reducers) ───────────────
    test_results: Annotated[list[dict], operator.add]
    defects:      Annotated[list[dict], operator.add]
    errors:       Annotated[list[str],  operator.add]

    # ── Phase 3 outputs ──────────────────────────────────────────────
    summary:        Optional[dict]    # {pass_rate, severity_breakdown, ...}
    final_report:   Optional[str]     # markdown CI report
    jira_tickets:   Optional[list]    # created Jira issue IDs
    slack_sent:     Optional[bool]

    # ── Evaluation outputs ───────────────────────────────────────────
    eval_scores:         Optional[dict]  # DeepEval metrics
    ragas_scores:        Optional[dict]  # RAGAS metrics
    eval_passed:         Optional[bool]
    eval_failure_reason: Optional[str]

    # ── Pipeline metadata ────────────────────────────────────────────
    pipeline_version: str     # "2.0.0"
    triggered_by:     str     # "github_webhook" | "manual" | "schedule"
    started_at:       str     # ISO timestamp
    completed_at:     Optional[str]


def initial_state(
    run_id: str,
    pr_number: int,
    repo_name: str,
    pr_diff: str,
    base_branch: str = "main",
    author: str = "",
    triggered_by: str = "github_webhook",
) -> CIPipelineState:
    """Build a fully-initialised CIPipelineState for a new pipeline run."""
    from datetime import datetime, timezone
    return CIPipelineState(
        run_id=run_id,
        pr_number=pr_number,
        repo_name=repo_name,
        pr_diff=pr_diff,
        base_branch=base_branch,
        author=author,
        risk_score=0.0,
        risk_factors=[],
        test_plan={},
        test_plan_text="",
        retrieval_context=[],
        changed_files=[],
        hitl_required=False,
        hitl_decision=None,
        hitl_reviewer=None,
        hitl_comment=None,
        test_results=[],
        defects=[],
        errors=[],
        summary=None,
        final_report=None,
        jira_tickets=None,
        slack_sent=None,
        eval_scores=None,
        ragas_scores=None,
        eval_passed=None,
        eval_failure_reason=None,
        pipeline_version="2.0.0",
        triggered_by=triggered_by,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=None,
    )
