# -*- coding: utf-8 -*-
"""
pipeline/consensus.py
──────────────────────
Multi-LLM Consensus Gate — Phase 1 risk scoring across three models.

Architecture
────────────
Three LLMs score the PR risk in parallel:
  - GPT-4o          (OpenAI)
  - Claude claude-sonnet-4-6   (Anthropic)
  - Gemini 1.5 Pro  (Google)

Agreement rules
───────────────
  1. Bucket agreement: all models must place the risk score in the same
     risk bucket (LOW / MEDIUM / HIGH / CRITICAL).
  2. Variance check: standard deviation of the three scores must be < 0.20.

If EITHER condition fails → consensus_forced_hitl = True, which overrides
the normal HITL threshold (0.85) and forces human review regardless of the
individual risk scores.

If consensus is reached:
  - risk_score = median of the three scores
  - risk_factors = union of all factors, deduplicated
  - normal HITL logic applies

Bucket boundaries
─────────────────
  LOW      [0.00, 0.40)
  MEDIUM   [0.40, 0.70)
  HIGH     [0.70, 0.85)
  CRITICAL [0.85, 1.00]
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

VARIANCE_THRESHOLD = 0.20      # max allowed std-dev across model scores
BUCKET_BOUNDARIES  = [0.40, 0.70, 0.85]

RiskBucket = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

RISK_SYSTEM_PROMPT = """\
You are a senior security and quality risk analyst.
Analyse the pull request diff and return ONLY valid JSON with no markdown:
{
  "risk_score": <float 0.0-1.0>,
  "risk_factors": [<string>, ...],
  "reasoning": "<one sentence>"
}

Risk score guidance:
  0.00-0.39 = LOW    (cosmetic, docs, tests, minor refactor)
  0.40-0.69 = MEDIUM (new feature, non-critical logic change)
  0.70-0.84 = HIGH   (auth, payments, public API, data model)
  0.85-1.00 = CRITICAL (security patch, prod config, breaking change)
"""

RISK_USER_PROMPT = """\
PR DIFF (truncated to 4000 chars):
{pr_diff}

KNOWLEDGE CONTEXT:
{context}
"""


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ModelVote:
    model:        str
    risk_score:   float
    risk_factors: list[str]
    reasoning:    str
    bucket:       RiskBucket
    error:        str = ""

    @property
    def success(self) -> bool:
        return not self.error


@dataclass
class ConsensusResult:
    votes:              list[ModelVote]          = field(default_factory=list)
    consensus_reached:  bool                     = False
    forced_hitl:        bool                     = False
    forced_hitl_reason: str                      = ""
    final_score:        float                    = 0.5
    final_factors:      list[str]                = field(default_factory=list)
    score_std:          float                    = 0.0
    buckets:            list[RiskBucket]         = field(default_factory=list)


# ── Bucket helper ─────────────────────────────────────────────────────────────

def _score_to_bucket(score: float) -> RiskBucket:
    if score < BUCKET_BOUNDARIES[0]:
        return "LOW"
    if score < BUCKET_BOUNDARIES[1]:
        return "MEDIUM"
    if score < BUCKET_BOUNDARIES[2]:
        return "HIGH"
    return "CRITICAL"


# ── LLM callers ───────────────────────────────────────────────────────────────

async def _call_openai(pr_diff: str, context: str) -> ModelVote:
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        resp = await llm.ainvoke([
            {"role": "system", "content": RISK_SYSTEM_PROMPT},
            {"role": "user",   "content": RISK_USER_PROMPT.format(
                pr_diff=pr_diff, context=context)},
        ])
        data = _parse_json(resp.content)
        score = float(data["risk_score"])
        return ModelVote(
            model="gpt-4o",
            risk_score=score,
            risk_factors=data.get("risk_factors", []),
            reasoning=data.get("reasoning", ""),
            bucket=_score_to_bucket(score),
        )
    except Exception as exc:
        logger.warning("OpenAI vote failed: %s", exc)
        return ModelVote(model="gpt-4o", risk_score=0.5, risk_factors=[],
                         reasoning="", bucket="MEDIUM", error=str(exc))


async def _call_claude(pr_diff: str, context: str) -> ModelVote:
    try:
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)
        resp = await llm.ainvoke([
            {"role": "user", "content":
             RISK_SYSTEM_PROMPT + "\n\n" +
             RISK_USER_PROMPT.format(pr_diff=pr_diff, context=context)},
        ])
        data = _parse_json(resp.content)
        score = float(data["risk_score"])
        return ModelVote(
            model="claude-sonnet-4-6",
            risk_score=score,
            risk_factors=data.get("risk_factors", []),
            reasoning=data.get("reasoning", ""),
            bucket=_score_to_bucket(score),
        )
    except Exception as exc:
        logger.warning("Claude vote failed: %s", exc)
        return ModelVote(model="claude-sonnet-4-6", risk_score=0.5, risk_factors=[],
                         reasoning="", bucket="MEDIUM", error=str(exc))


async def _call_gemini(pr_diff: str, context: str) -> ModelVote:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0)
        resp = await llm.ainvoke([
            {"role": "user", "content":
             RISK_SYSTEM_PROMPT + "\n\n" +
             RISK_USER_PROMPT.format(pr_diff=pr_diff, context=context)},
        ])
        data = _parse_json(resp.content)
        score = float(data["risk_score"])
        return ModelVote(
            model="gemini-1.5-pro",
            risk_score=score,
            risk_factors=data.get("risk_factors", []),
            reasoning=data.get("reasoning", ""),
            bucket=_score_to_bucket(score),
        )
    except Exception as exc:
        logger.warning("Gemini vote failed: %s", exc)
        return ModelVote(model="gemini-1.5-pro", risk_score=0.5, risk_factors=[],
                         reasoning="", bucket="MEDIUM", error=str(exc))


# ── Core consensus logic ──────────────────────────────────────────────────────

async def run_consensus_scoring(pr_diff: str, context: str) -> ConsensusResult:
    """
    Query all three LLMs in parallel and compute consensus.
    Returns a ConsensusResult with final score and forced_hitl flag.
    """
    # Fan-out: all three models in parallel
    votes = list(await asyncio.gather(
        _call_openai(pr_diff, context),
        _call_claude(pr_diff, context),
        _call_gemini(pr_diff, context),
    ))

    result = ConsensusResult(votes=votes)
    result.buckets = [v.bucket for v in votes]

    # Scores from models that succeeded
    successful = [v for v in votes if v.success]
    if not successful:
        result.forced_hitl = True
        result.forced_hitl_reason = "All three LLM votes failed — cannot assess risk"
        result.final_score = 0.85    # fail-closed: treat as critical
        return result

    scores = [v.risk_score for v in successful]
    buckets = [v.bucket for v in successful]

    # Compute variance
    result.score_std = statistics.stdev(scores) if len(scores) > 1 else 0.0

    # ── Agreement check 1: bucket consensus ──────────────────────────────────
    bucket_set = set(buckets)
    if len(bucket_set) > 1:
        result.forced_hitl = True
        result.forced_hitl_reason = (
            f"Bucket disagreement: models returned {', '.join(sorted(bucket_set))} — "
            f"epistemic uncertainty requires human review"
        )

    # ── Agreement check 2: score variance ────────────────────────────────────
    elif result.score_std >= VARIANCE_THRESHOLD:
        result.forced_hitl = True
        result.forced_hitl_reason = (
            f"Score variance too high: std={result.score_std:.3f} "
            f"(threshold={VARIANCE_THRESHOLD}) — scores: "
            f"{[round(s,2) for s in scores]}"
        )

    else:
        result.consensus_reached = True

    # Final score: median of successful votes
    result.final_score = statistics.median(scores)

    # Deduplicated union of all risk factors
    seen: set[str] = set()
    merged: list[str] = []
    for v in votes:
        for f in v.risk_factors:
            key = f.lower().strip()
            if key not in seen:
                seen.add(key)
                merged.append(f)
    result.final_factors = merged

    if result.forced_hitl:
        logger.warning(
            "consensus: FORCED HITL — %s", result.forced_hitl_reason
        )
    else:
        logger.info(
            "consensus: REACHED — score=%.2f bucket=%s std=%.3f",
            result.final_score, result.buckets[0], result.score_std,
        )

    return result


# ── LangGraph node ─────────────────────────────────────────────────────────────

async def consensus_score_risk(state: dict) -> dict:
    """
    Replaces ``score_risk`` in Phase 1.
    Runs three LLMs in parallel and merges results into state.
    """
    pr_diff  = state.get("pr_diff", "")[:4000]
    context  = "\n".join(state.get("retrieval_context", [])[:3]) or "None"

    result = await run_consensus_scoring(pr_diff, context)

    # Build vote summary for report/audit trail
    vote_summary = [
        {
            "model":        v.model,
            "score":        v.risk_score,
            "bucket":       v.bucket,
            "factors":      v.risk_factors,
            "reasoning":    v.reasoning,
            "error":        v.error,
        }
        for v in result.votes
    ]

    return {
        "risk_score":               result.final_score,
        "risk_factors":             result.final_factors,
        # Consensus-specific fields
        "consensus_votes":          vote_summary,
        "consensus_reached":        result.consensus_reached,
        "consensus_forced_hitl":    result.forced_hitl,
        "consensus_forced_reason":  result.forced_hitl_reason,
        "consensus_score_std":      result.score_std,
        "consensus_buckets":        result.buckets,
    }


# ── HITL gate integration ─────────────────────────────────────────────────────

def consensus_risk_gate_check(state: dict) -> dict:
    """
    Updated risk_gate_check that also considers consensus_forced_hitl.
    If consensus forced HITL, override regardless of risk_score threshold.
    """
    threshold = 0.85
    score_triggered = state.get("risk_score", 0.0) >= threshold
    consensus_forced = state.get("consensus_forced_hitl", False)
    hitl_required = score_triggered or consensus_forced

    logger.info(
        "risk_gate: score=%.2f score_triggered=%s consensus_forced=%s hitl_required=%s",
        state.get("risk_score", 0.0),
        score_triggered, consensus_forced, hitl_required,
    )
    return {"hitl_required": hitl_required}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)
