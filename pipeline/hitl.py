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
HITL Gate — Human-in-the-Loop approval for high-risk PRs.
Pauses execution via interrupt() and resumes via update_state().
"""

from __future__ import annotations
import logging

from langgraph.types import interrupt

from .state import CIPipelineState
from .mcp_clients import slack_mcp

logger = logging.getLogger(__name__)

RISK_THRESHOLD = 0.85  # PRs above this score require human review


async def risk_gate_check(state: CIPipelineState) -> dict:
    """Decide whether human review is needed and notify via Slack."""
    requires_review = state["risk_score"] >= RISK_THRESHOLD
    if requires_review:
        logger.warning(
            "HITL required for PR #%d — risk_score=%.2f factors=%s",
            state["pr_number"], state["risk_score"], state["risk_factors"],
        )
        try:
            await slack_mcp.call_tool("post_message", {
                "channel": "#qa-alerts",
                "text": (
                    f":rotating_light: *High-risk PR requires review*\n"
                    f"Repo: `{state['repo_name']}` | PR: #{state['pr_number']}\n"
                    f"Risk score: `{state['risk_score']:.2f}` (threshold: {RISK_THRESHOLD})\n"
                    f"Risk factors: {', '.join(state['risk_factors'])}\n"
                    f"Run ID: `{state['run_id']}`\n"
                    f"Reply with: `/qa-approve {state['run_id']}` or `/qa-reject {state['run_id']} <reason>`"
                ),
                "mrkdwn": True,
            })
        except Exception as exc:
            logger.error("Slack HITL notification failed: %s", exc)
    else:
        logger.info(
            "HITL not required for PR #%d — risk_score=%.2f",
            state["pr_number"], state["risk_score"],
        )
    return {"hitl_required": requires_review}


async def human_review_gate(state: CIPipelineState) -> dict:
    """
    Pause execution and wait for human decision.
    Execution resumes when graph.update_state() is called externally
    (e.g., via the /qa-approve Slack command or webhook endpoint).
    """
    logger.info("Waiting for human review — run_id=%s", state["run_id"])
    decision = interrupt({
        "type":       "human_review",
        "run_id":     state["run_id"],
        "risk_score": state["risk_score"],
        "factors":    state["risk_factors"],
        "repo_name":  state["repo_name"],
        "pr_number":  state["pr_number"],
        "message":    "High-risk PR requires QA lead approval before testing proceeds.",
    })
    logger.info(
        "HITL decision received: decision=%s reviewer=%s",
        decision.get("decision"), decision.get("reviewer"),
    )
    return {
        "hitl_decision": decision["decision"],
        "hitl_reviewer": decision.get("reviewer", "unknown"),
        "hitl_comment":  decision.get("comment", ""),
    }


def route_after_hitl(state: CIPipelineState) -> str:
    """Routing function: proceed to Phase 2 or terminate the pipeline."""
    if not state["hitl_required"]:
        return "proceed"  # risk was low — skip gate entirely
    decision = state.get("hitl_decision")
    if decision == "approve":
        return "proceed"
    return "reject"  # rejected or no decision


async def pipeline_rejected(state: CIPipelineState) -> dict:
    """Terminal node for human-rejected pipelines."""
    reason = state.get("hitl_comment") or "No reason provided."
    reviewer = state.get("hitl_reviewer", "unknown")
    report = (
        f"# Pipeline Rejected\n\n"
        f"**Repo:** {state['repo_name']} | **PR:** #{state['pr_number']}\n\n"
        f"**Rejected by:** {reviewer}\n\n"
        f"**Reason:** {reason}\n\n"
        f"**Run ID:** `{state['run_id']}`\n"
    )
    logger.info("Pipeline rejected by %s: %s", reviewer, reason)
    try:
        await slack_mcp.call_tool("post_message", {
            "channel": "#qa-alerts",
            "text": (
                f":no_entry: *Pipeline rejected by {reviewer}*\n"
                f"PR #{state['pr_number']} in `{state['repo_name']}`\n"
                f"Reason: {reason}"
            ),
        })
    except Exception:
        pass
    return {"final_report": report}
