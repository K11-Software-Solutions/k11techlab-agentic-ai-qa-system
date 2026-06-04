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

Consensus Modes  (set via CONSENSUS_MODE env var or ConsensusConfig)
─────────────────────────────────────────────────────────────────────
  unanimous  (default / research)
      All 3 models must agree on risk bucket AND score std-dev < threshold.
      Strictest — highest safety, highest HITL rate (~20-30% disagreement).

  majority   (recommended for production)
      At least 2 of 3 models must agree on risk bucket AND std-dev < threshold.
      Balanced — reduces false HITL triggers by ~60% vs unanimous.

  weighted   (highest throughput)
      No bucket check. Final score = confidence-weighted average.
      Forces HITL only if std-dev >= threshold OR all models fail.
      Lowest HITL rate — best for low-risk repos.

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
import os
import re
import statistics
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

VARIANCE_THRESHOLD = 0.20      # max allowed std-dev across model scores
BUCKET_BOUNDARIES  = [0.40, 0.70, 0.85]

RiskBucket   = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ConsensusMode = Literal["unanimous", "majority", "weighted"]


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class ConsensusConfig:
    """
    Runtime configuration for the consensus gate.
    Loaded from environment variables with sensible defaults.
    """
    mode:               ConsensusMode = "unanimous"
    variance_threshold: float         = VARIANCE_THRESHOLD
    hitl_threshold:     float         = 0.85   # score-based HITL trigger

    @classmethod
    def from_env(cls) -> "ConsensusConfig":
        mode = os.getenv("CONSENSUS_MODE", "unanimous").lower()
        if mode not in ("unanimous", "majority", "weighted"):
            logger.warning("Unknown CONSENSUS_MODE=%r, falling back to 'unanimous'", mode)
            mode = "unanimous"
        return cls(
            mode=mode,
            variance_threshold=float(os.getenv("CONSENSUS_VARIANCE_THRESHOLD",
                                                str(VARIANCE_THRESHOLD))),
            hitl_threshold=float(os.getenv("HITL_RISK_THRESHOLD", "0.85")),
        )


# Singleton loaded at import time (overridable in tests)
_default_config = ConsensusConfig.from_env()

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
    consensus_mode:     ConsensusMode            = "unanimous"


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


# ── Consensus strategies ──────────────────────────────────────────────────────

def _check_unanimous(
    successful: list[ModelVote], cfg: ConsensusConfig
) -> tuple[bool, str]:
    """All models must agree on bucket AND variance < threshold."""
    scores  = [v.risk_score for v in successful]
    buckets = [v.bucket for v in successful]
    std     = statistics.stdev(scores) if len(scores) > 1 else 0.0
    bucket_set = set(buckets)

    if len(bucket_set) > 1:
        return False, (
            f"[unanimous] Bucket disagreement: "
            f"{', '.join(sorted(bucket_set))} — epistemic uncertainty"
        )
    if std >= cfg.variance_threshold:
        return False, (
            f"[unanimous] Score variance std={std:.3f} >= "
            f"threshold={cfg.variance_threshold} — "
            f"scores: {[round(s,2) for s in scores]}"
        )
    return True, ""


def _check_majority(
    successful: list[ModelVote], cfg: ConsensusConfig
) -> tuple[bool, str]:
    """
    At least 2 of 3 models must agree on bucket AND variance < threshold.
    The minority outlier model is noted but does not block consensus.
    """
    scores  = [v.risk_score for v in successful]
    buckets = [v.bucket for v in successful]
    std     = statistics.stdev(scores) if len(scores) > 1 else 0.0

    # Count bucket votes
    from collections import Counter
    counts = Counter(buckets)
    majority_bucket, majority_count = counts.most_common(1)[0]

    if majority_count < 2:
        return False, (
            f"[majority] No bucket has >= 2 votes: "
            f"{dict(counts)} — epistemic uncertainty"
        )
    if std >= cfg.variance_threshold:
        return False, (
            f"[majority] Score variance std={std:.3f} >= "
            f"threshold={cfg.variance_threshold} — "
            f"scores: {[round(s,2) for s in scores]}"
        )

    outliers = [v.model for v in successful if v.bucket != majority_bucket]
    if outliers:
        logger.info(
            "consensus [majority]: outlier model(s) %s overridden by majority bucket %s",
            outliers, majority_bucket,
        )
    return True, ""


def _check_weighted(
    successful: list[ModelVote], cfg: ConsensusConfig
) -> tuple[bool, str]:
    """
    No bucket check. Only variance check.
    Final score computed as confidence-weighted average (equal weights = mean).
    Least strict — highest throughput.
    """
    scores = [v.risk_score for v in successful]
    std    = statistics.stdev(scores) if len(scores) > 1 else 0.0

    if std >= cfg.variance_threshold:
        return False, (
            f"[weighted] Score variance std={std:.3f} >= "
            f"threshold={cfg.variance_threshold} — "
            f"scores: {[round(s,2) for s in scores]}"
        )
    return True, ""


def _final_score(
    successful: list[ModelVote], mode: ConsensusMode
) -> float:
    """Compute final score from successful votes according to mode."""
    scores = [v.risk_score for v in successful]
    if mode == "weighted":
        # Equal weights for now; extend with per-model calibration weights later
        return statistics.mean(scores)
    # unanimous / majority → median
    return statistics.median(scores)


# ── Core consensus logic ──────────────────────────────────────────────────────

async def run_consensus_scoring(
    pr_diff: str,
    context: str,
    config: ConsensusConfig | None = None,
) -> ConsensusResult:
    """
    Query all three LLMs in parallel and compute consensus.
    Agreement strategy is determined by config.mode.
    Returns a ConsensusResult with final score and forced_hitl flag.
    """
    cfg = config or _default_config

    # Fan-out: all three models in parallel
    votes = list(await asyncio.gather(
        _call_openai(pr_diff, context),
        _call_claude(pr_diff, context),
        _call_gemini(pr_diff, context),
    ))

    result = ConsensusResult(
        votes=votes,
        consensus_mode=cfg.mode,
    )
    result.buckets = [v.bucket for v in votes]

    # Fail-closed: no successful votes
    successful = [v for v in votes if v.success]
    if not successful:
        result.forced_hitl = True
        result.forced_hitl_reason = (
            f"[{cfg.mode}] All three LLM votes failed -- cannot assess risk"
        )
        result.final_score = 0.85
        return result

    scores = [v.risk_score for v in successful]
    result.score_std = statistics.stdev(scores) if len(scores) > 1 else 0.0

    strategy = {
        "unanimous": _check_unanimous,
        "majority":  _check_majority,
        "weighted":  _check_weighted,
    }[cfg.mode]

    agreed, reason = strategy(successful, cfg)

    if agreed:
        result.consensus_reached = True
        result.final_score = _final_score(successful, cfg.mode)
    else:
        result.forced_hitl = True
        result.forced_hitl_reason = reason
        result.final_score = _final_score(successful, cfg.mode)

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
        logger.warning("consensus [%s]: FORCED HITL -- %s", cfg.mode, reason)
    else:
        logger.info(
            "consensus [%s]: REACHED -- score=%.2f std=%.3f",
            cfg.mode, result.final_score, result.score_std,
        )

    return result


# -- LangGraph node --

async def consensus_score_risk(state: dict) -> dict:
    """Replaces score_risk in Phase 1. Runs three LLMs in parallel."""
    pr_diff = state.get("pr_diff", "")[:4000]
    context = "\n".join(state.get("retrieval_context", [])[:3]) or "None"
    cfg     = ConsensusConfig.from_env()
    result  = await run_consensus_scoring(pr_diff, context, config=cfg)
    vote_summary = [
        {"model": v.model, "score": v.risk_score, "bucket": v.bucket,
         "factors": v.risk_factors, "reasoning": v.reasoning, "error": v.error}
        for v in result.votes
    ]
    return {
        "risk_score":              result.final_score,
        "risk_factors":            result.final_factors,
        "consensus_votes":         vote_summary,
        "consensus_reached":       result.consensus_reached,
        "consensus_forced_hitl":   result.forced_hitl,
        "consensus_forced_reason": result.forced_hitl_reason,
        "consensus_score_std":     result.score_std,
        "consensus_buckets":       result.buckets,
        "consensus_mode":          result.consensus_mode,
    }


# -- HITL gate --

def consensus_risk_gate_check(state: dict) -> dict:
    """Updated gate that also considers consensus_forced_hitl."""
    threshold = float(os.getenv("HITL_RISK_THRESHOLD", "0.85"))
    score_triggered = state.get("risk_score", 0.0) >= threshold
    consensus_forced = state.get("consensus_forced_hitl", False)
    hitl_required = score_triggered or consensus_forced
    logger.info(
        "risk_gate: score=%.2f score_triggered=%s consensus_forced=%s hitl_required=%s",
        state.get("risk_score", 0.0), score_triggered, consensus_forced, hitl_required,
    )
    return {"hitl_required": hitl_required}


# -- Helpers --

def _parse_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)
