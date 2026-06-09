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
Main Orchestrator — composes all four phases and the HITL gate into one StateGraph.
Pure routing: all business logic lives in the subgraphs.
"""

from __future__ import annotations
import logging
from typing import Any

from langgraph.graph import StateGraph, START, END

from .state import CIPipelineState
from .phase1 import phase1_app
from .phase2 import phase2_app
from .phase3 import phase3_app
from .evaluation import eval_app
from .hitl import (
    human_review_gate,
    pipeline_rejected, route_after_hitl,
)
from .consensus import consensus_risk_gate_check
from .remediation import run_remediation, should_remediate

logger = logging.getLogger(__name__)


def build_orchestrator() -> Any:
    """
    Assemble the main CI pipeline StateGraph.
    Returns an uncompiled builder — compile at runtime to inject a checkpointer.
    """
    builder = StateGraph(CIPipelineState)

    # ── Subgraph nodes ────────────────────────────────────────────────
    builder.add_node("phase1",       phase1_app)
    builder.add_node("phase2",       phase2_app)
    builder.add_node("remediation",  run_remediation)   # Phase 2.5
    builder.add_node("phase3",       phase3_app)
    builder.add_node("evaluation",   eval_app)

    # ── HITL gate nodes ───────────────────────────────────────────────
    builder.add_node("risk_gate_check",   consensus_risk_gate_check)
    builder.add_node("human_review_gate", human_review_gate)
    builder.add_node("pipeline_rejected", pipeline_rejected)

    # ── Edges ─────────────────────────────────────────────────────────
    builder.add_edge(START, "phase1")
    builder.add_edge("phase1", "risk_gate_check")

    # risk_gate_check → human review gate or directly to phase2
    builder.add_conditional_edges(
        "risk_gate_check",
        lambda s: "review" if s["hitl_required"] else "proceed",
        {"review": "human_review_gate", "proceed": "phase2"},
    )

    # human_review_gate → phase2 (approved) or pipeline_rejected
    builder.add_conditional_edges(
        "human_review_gate",
        route_after_hitl,
        {"proceed": "phase2", "reject": "pipeline_rejected"},
    )

    # phase2 → remediation (if remediable defects) or directly to phase3
    builder.add_conditional_edges(
        "phase2",
        should_remediate,
        {"remediate": "remediation", "skip_remediation": "phase3"},
    )
    builder.add_edge("remediation", "phase3")
    builder.add_edge("phase3",      "evaluation")
    builder.add_edge("evaluation",  END)
    builder.add_edge("pipeline_rejected", END)

    return builder


# Module-level builder
ci_builder = build_orchestrator()
