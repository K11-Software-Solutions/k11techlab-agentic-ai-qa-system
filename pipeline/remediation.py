# -*- coding: utf-8 -*-
"""
pipeline/remediation.py
────────────────────────
Phase 2.5 — Auto-Remediation node.

Sits between Phase 2 (parallel test execution) and Phase 3 (reporting).
Runs AutoRemediationAgent and writes results back to CIPipelineState.

Routing logic:
  - If no defects detected in Phase 2  → skip (pass through)
  - If all defects are non-remediable   → skip (pass through)
  - Otherwise                           → attempt remediation
"""

from __future__ import annotations

import logging

from agents.auto_remediation_agent import AutoRemediationAgent, SAFE_CLASSES

logger = logging.getLogger(__name__)


async def run_remediation(state: dict) -> dict:
    """
    LangGraph node function for Phase 2.5.

    Returns a state-update dict (only the keys that change).
    """
    defects: list[dict] = state.get("defects", [])

    # Fast-path: nothing to remediate
    remediable = [d for d in defects if d.get("defect_class") in SAFE_CLASSES]
    if not remediable:
        logger.info("remediation: no remediable defects — skipping")
        return {
            "remediation_pr_url":    None,
            "remediation_pr_number": None,
            "remediation_branch":    None,
            "remediation_patches":   0,
            "remediation_skipped":   0,
            "remediation_error":     None,
        }

    logger.info("remediation: %d remediable defect(s) found", len(remediable))

    # Build MCP clients (reuse pattern from phase2)
    from pipeline.mcp_clients import build_mcp_clients
    mcp = build_mcp_clients()

    agent = AutoRemediationAgent(mcp_clients=mcp)
    result = await agent.run(state, suite={"suite_type": "remediation", "priority": "low"})

    meta = result.metadata or {}
    return {
        "remediation_pr_url":    meta.get("remediation_pr_url"),
        "remediation_pr_number": meta.get("remediation_pr_number"),
        "remediation_branch":    meta.get("branch"),
        "remediation_patches":   meta.get("patches_applied", 0),
        "remediation_skipped":   meta.get("patches_skipped", 0),
        "remediation_error":     meta.get("error") or result.error,
    }


def should_remediate(state: dict) -> str:
    """
    Conditional edge after Phase 2.

    Returns "remediate" if any remediable defects exist, else "skip_remediation".
    """
    defects: list[dict] = state.get("defects", [])
    has_remediable = any(
        d.get("defect_class") in SAFE_CLASSES for d in defects
    )
    return "remediate" if has_remediable else "skip_remediation"
