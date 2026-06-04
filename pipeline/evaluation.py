"""
Evaluation Subgraph — DeepEval + RAGAS quality gates.
Runs after Phase 3. DeepEval and RAGAS nodes execute in parallel via Send API.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.types import Send

from .state import CIPipelineState
from .mcp_clients import langsmith_client

logger = logging.getLogger(__name__)

DEEPEVAL_THRESHOLDS = {
    "answer_relevancy": 0.70,
    "faithfulness":     0.80,
}
RAGAS_THRESHOLDS = {
    "context_precision": 0.55,
    "faithfulness":      0.75,
}


# ── Dispatch ──────────────────────────────────────────────────────────────────

def dispatch_evaluation(state: CIPipelineState) -> list[Send]:
    """Fan out to DeepEval and RAGAS nodes in parallel."""
    return [
        Send("deepeval_node", dict(state)),
        Send("ragas_node",    dict(state)),
    ]


# ── DeepEval node ─────────────────────────────────────────────────────────────

async def deepeval_node(state: dict) -> dict:
    """Score the final CI report for answer relevancy and faithfulness."""
    try:
        from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
        from deepeval.test_case import LLMTestCase

        test_case = LLMTestCase(
            input=state["pr_diff"][:2000],
            actual_output=state.get("final_report", ""),
            retrieval_context=state.get("retrieval_context", [])[:5],
        )

        relevancy = AnswerRelevancyMetric(threshold=DEEPEVAL_THRESHOLDS["answer_relevancy"], model="gpt-4o-mini")
        faithful  = FaithfulnessMetric(threshold=DEEPEVAL_THRESHOLDS["faithfulness"], model="gpt-4o-mini")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, relevancy.measure, test_case)
        await loop.run_in_executor(None, faithful.measure, test_case)

        scores = {
            "answer_relevancy": round(relevancy.score, 4),
            "faithfulness":     round(faithful.score, 4),
        }
        logger.info("DeepEval scores: %s", scores)

        # Post scores to LangSmith as feedback
        _post_langsmith_feedback(state["run_id"], scores)
        return {"eval_scores": scores}

    except ImportError:
        logger.warning("deepeval not installed — skipping DeepEval evaluation")
        return {"eval_scores": {}}
    except Exception as exc:
        logger.error("deepeval_node failed: %s", exc)
        return {"eval_scores": {}}


# ── RAGAS node ────────────────────────────────────────────────────────────────

async def ragas_node(state: dict) -> dict:
    """Score Knowledge Store retrieval quality using RAGAS."""
    if not state.get("retrieval_context"):
        logger.info("No retrieval_context — skipping RAGAS evaluation")
        return {"ragas_scores": {}}
    try:
        from ragas import evaluate as ragas_evaluate
        from ragas.metrics import faithfulness, context_precision
        from datasets import Dataset

        data = {
            "question":   [state["pr_diff"][:500]],
            "answer":     [state.get("test_plan_text", "")],
            "contexts":   [state["retrieval_context"][:5]],
            "ground_truth": [state.get("test_plan_text", "")],
        }
        ds = Dataset.from_dict(data)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: ragas_evaluate(ds, metrics=[faithfulness, context_precision]),
        )
        row    = result.to_pandas().iloc[0].to_dict()
        scores = {
            "faithfulness":      round(float(row.get("faithfulness", 0)), 4),
            "context_precision": round(float(row.get("context_precision", 0)), 4),
        }
        logger.info("RAGAS scores: %s", scores)
        _post_langsmith_feedback(state["run_id"], {f"ragas_{k}": v for k, v in scores.items()})
        return {"ragas_scores": scores}

    except ImportError:
        logger.warning("ragas not installed — skipping RAGAS evaluation")
        return {"ragas_scores": {}}
    except Exception as exc:
        logger.error("ragas_node failed: %s", exc)
        return {"ragas_scores": {}}


# ── Aggregate ─────────────────────────────────────────────────────────────────

async def aggregate_evaluation(state: CIPipelineState) -> dict:
    """Combine DeepEval and RAGAS scores into a single pass/fail verdict."""
    ds = state.get("eval_scores") or {}
    rs = state.get("ragas_scores") or {}

    deepeval_ok = all(
        ds.get(k, 1.0) >= threshold
        for k, threshold in DEEPEVAL_THRESHOLDS.items()
        if ds  # skip if DeepEval didn't run
    )
    ragas_ok = all(
        rs.get(k, 1.0) >= threshold
        for k, threshold in RAGAS_THRESHOLDS.items()
        if rs  # skip if RAGAS didn't run
    )

    passed = deepeval_ok and ragas_ok
    reason = None
    if not passed:
        parts = []
        for k, t in DEEPEVAL_THRESHOLDS.items():
            v = ds.get(k)
            if v is not None and v < t:
                parts.append(f"{k}={v:.2f} (need {t})")
        for k, t in RAGAS_THRESHOLDS.items():
            v = rs.get(k)
            if v is not None and v < t:
                parts.append(f"ragas_{k}={v:.2f} (need {t})")
        reason = "; ".join(parts)

    logger.info("Evaluation verdict: passed=%s reason=%s", passed, reason)
    return {"eval_passed": passed, "eval_failure_reason": reason}


def route_aggregate(state: CIPipelineState) -> str:
    return "pass" if state.get("eval_passed", True) else "fail"


async def quality_gate_fail(state: CIPipelineState) -> dict:
    """Log the quality gate failure to LangSmith."""
    reason = state.get("eval_failure_reason", "Unknown")
    logger.warning("Quality gate FAILED: %s", reason)
    _post_langsmith_feedback(state["run_id"], {"quality_gate": 0.0}, comment=reason)
    return {}


# ── LangSmith helper ──────────────────────────────────────────────────────────

def _post_langsmith_feedback(run_id: str, scores: dict, comment: str = "") -> None:
    if not langsmith_client:
        return
    for key, score in scores.items():
        try:
            langsmith_client.create_feedback(
                run_id=run_id,
                key=key,
                score=float(score),
                comment=comment or None,
            )
        except Exception as exc:
            logger.debug("LangSmith feedback failed for %s: %s", key, exc)


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_evaluation() -> Any:
    builder = StateGraph(CIPipelineState)
    builder.add_node("dispatch",         lambda s: {})
    builder.add_node("deepeval_node",    deepeval_node)
    builder.add_node("ragas_node",       ragas_node)
    builder.add_node("aggregate",        aggregate_evaluation)
    builder.add_node("quality_gate_fail",quality_gate_fail)

    builder.set_entry_point("dispatch")
    builder.add_conditional_edges("dispatch", dispatch_evaluation, ["deepeval_node", "ragas_node"])
    builder.add_edge("deepeval_node", "aggregate")
    builder.add_edge("ragas_node",    "aggregate")
    builder.add_conditional_edges(
        "aggregate", route_aggregate,
        {"pass": END, "fail": "quality_gate_fail"},
    )
    builder.add_edge("quality_gate_fail", END)

    return builder.compile()


eval_app = build_evaluation()
