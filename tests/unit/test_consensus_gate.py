# -*- coding: utf-8 -*-
"""
tests/unit/test_consensus_gate.py
───────────────────────────────────
Unit tests for Multi-LLM Consensus Gate.
All LLM calls are mocked — no API keys required.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from pipeline.consensus import (
    ModelVote,
    ConsensusResult,
    run_consensus_scoring,
    consensus_score_risk,
    consensus_risk_gate_check,
    _score_to_bucket,
    VARIANCE_THRESHOLD,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

PR_DIFF   = "--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@\n-x=1\n+x=2"
CONTEXT   = "Historical: auth module has 3 past incidents."

AGREE_HIGH = [
    ModelVote("gpt-4o",           0.78, ["auth change"], "auth modified", "HIGH"),
    ModelVote("claude-sonnet-4-6",0.80, ["auth change"], "auth modified", "HIGH"),
    ModelVote("gemini-1.5-pro",   0.75, ["auth change"], "auth modified", "HIGH"),
]

DISAGREE_BUCKET = [
    ModelVote("gpt-4o",           0.80, ["auth change"], "HIGH risk", "HIGH"),
    ModelVote("claude-sonnet-4-6",0.45, ["minor edit"],  "MEDIUM risk", "MEDIUM"),
    ModelVote("gemini-1.5-pro",   0.75, ["auth change"], "HIGH risk", "HIGH"),
]

DISAGREE_VARIANCE = [
    ModelVote("gpt-4o",           0.90, ["auth change"], "CRITICAL", "CRITICAL"),
    ModelVote("claude-sonnet-4-6",0.91, ["auth change"], "CRITICAL", "CRITICAL"),
    ModelVote("gemini-1.5-pro",   0.30, ["minor edit"],  "LOW",      "LOW"),
]

ALL_FAILED = [
    ModelVote("gpt-4o",           0.5, [], "", "MEDIUM", error="timeout"),
    ModelVote("claude-sonnet-4-6",0.5, [], "", "MEDIUM", error="auth_error"),
    ModelVote("gemini-1.5-pro",   0.5, [], "", "MEDIUM", error="quota"),
]


# ── Bucket tests ──────────────────────────────────────────────────────────────

class TestScoreToBucket:
    def test_low(self):       assert _score_to_bucket(0.10) == "LOW"
    def test_low_boundary(self):   assert _score_to_bucket(0.39) == "LOW"
    def test_medium(self):    assert _score_to_bucket(0.55) == "MEDIUM"
    def test_high(self):      assert _score_to_bucket(0.75) == "HIGH"
    def test_critical(self):  assert _score_to_bucket(0.90) == "CRITICAL"
    def test_exact_boundaries(self):
        assert _score_to_bucket(0.40) == "MEDIUM"
        assert _score_to_bucket(0.70) == "HIGH"
        assert _score_to_bucket(0.85) == "CRITICAL"


# ── Consensus logic tests ─────────────────────────────────────────────────────

class TestConsensusLogic:

    @pytest.mark.asyncio
    async def test_agreement_reached_when_same_bucket_low_variance(self):
        with patch("pipeline.consensus._call_openai",  AsyncMock(return_value=AGREE_HIGH[0])), \
             patch("pipeline.consensus._call_claude",  AsyncMock(return_value=AGREE_HIGH[1])), \
             patch("pipeline.consensus._call_gemini",  AsyncMock(return_value=AGREE_HIGH[2])):
            result = await run_consensus_scoring(PR_DIFF, CONTEXT)
        assert result.consensus_reached is True
        assert result.forced_hitl is False
        assert result.score_std < VARIANCE_THRESHOLD

    @pytest.mark.asyncio
    async def test_forced_hitl_on_bucket_disagreement(self):
        with patch("pipeline.consensus._call_openai",  AsyncMock(return_value=DISAGREE_BUCKET[0])), \
             patch("pipeline.consensus._call_claude",  AsyncMock(return_value=DISAGREE_BUCKET[1])), \
             patch("pipeline.consensus._call_gemini",  AsyncMock(return_value=DISAGREE_BUCKET[2])):
            result = await run_consensus_scoring(PR_DIFF, CONTEXT)
        assert result.forced_hitl is True
        assert "Bucket disagreement" in result.forced_hitl_reason
        assert result.consensus_reached is False

    @pytest.mark.asyncio
    async def test_forced_hitl_on_high_variance(self):
        with patch("pipeline.consensus._call_openai",  AsyncMock(return_value=DISAGREE_VARIANCE[0])), \
             patch("pipeline.consensus._call_claude",  AsyncMock(return_value=DISAGREE_VARIANCE[1])), \
             patch("pipeline.consensus._call_gemini",  AsyncMock(return_value=DISAGREE_VARIANCE[2])):
            result = await run_consensus_scoring(PR_DIFF, CONTEXT)
        assert result.forced_hitl is True
        assert "variance" in result.forced_hitl_reason.lower()

    @pytest.mark.asyncio
    async def test_forced_hitl_when_all_models_fail(self):
        with patch("pipeline.consensus._call_openai",  AsyncMock(return_value=ALL_FAILED[0])), \
             patch("pipeline.consensus._call_claude",  AsyncMock(return_value=ALL_FAILED[1])), \
             patch("pipeline.consensus._call_gemini",  AsyncMock(return_value=ALL_FAILED[2])):
            result = await run_consensus_scoring(PR_DIFF, CONTEXT)
        assert result.forced_hitl is True
        assert result.final_score == 0.85   # fail-closed

    @pytest.mark.asyncio
    async def test_final_score_is_median(self):
        with patch("pipeline.consensus._call_openai",  AsyncMock(return_value=AGREE_HIGH[0])), \
             patch("pipeline.consensus._call_claude",  AsyncMock(return_value=AGREE_HIGH[1])), \
             patch("pipeline.consensus._call_gemini",  AsyncMock(return_value=AGREE_HIGH[2])):
            result = await run_consensus_scoring(PR_DIFF, CONTEXT)
        # Median of [0.78, 0.80, 0.75] = 0.78
        assert result.final_score == pytest.approx(0.78)

    @pytest.mark.asyncio
    async def test_risk_factors_deduplicated(self):
        votes = [
            ModelVote("gpt-4o",           0.78, ["auth change", "sql query"], "", "HIGH"),
            ModelVote("claude-sonnet-4-6",0.80, ["auth change", "api change"], "", "HIGH"),
            ModelVote("gemini-1.5-pro",   0.75, ["sql query",   "api change"], "", "HIGH"),
        ]
        with patch("pipeline.consensus._call_openai",  AsyncMock(return_value=votes[0])), \
             patch("pipeline.consensus._call_claude",  AsyncMock(return_value=votes[1])), \
             patch("pipeline.consensus._call_gemini",  AsyncMock(return_value=votes[2])):
            result = await run_consensus_scoring(PR_DIFF, CONTEXT)
        # Should have 3 unique factors, not 6
        assert len(result.final_factors) == 3


# ── State node tests ──────────────────────────────────────────────────────────

class TestConsensusScoreRiskNode:

    @pytest.mark.asyncio
    async def test_returns_all_state_fields(self):
        mock_result = ConsensusResult(
            votes=AGREE_HIGH,
            consensus_reached=True,
            forced_hitl=False,
            forced_hitl_reason="",
            final_score=0.78,
            final_factors=["auth change"],
            score_std=0.025,
            buckets=["HIGH", "HIGH", "HIGH"],
        )
        with patch("pipeline.consensus.run_consensus_scoring",
                   AsyncMock(return_value=mock_result)):
            state_update = await consensus_score_risk({
                "pr_diff": PR_DIFF,
                "retrieval_context": [CONTEXT],
            })

        assert state_update["risk_score"] == pytest.approx(0.78)
        assert state_update["consensus_reached"] is True
        assert state_update["consensus_forced_hitl"] is False
        assert len(state_update["consensus_votes"]) == 3
        assert "auth change" in state_update["risk_factors"]

    @pytest.mark.asyncio
    async def test_forced_hitl_propagated_to_state(self):
        mock_result = ConsensusResult(
            votes=DISAGREE_BUCKET,
            consensus_reached=False,
            forced_hitl=True,
            forced_hitl_reason="Bucket disagreement: HIGH vs MEDIUM",
            final_score=0.75,
            final_factors=["auth change"],
            score_std=0.18,
            buckets=["HIGH", "MEDIUM", "HIGH"],
        )
        with patch("pipeline.consensus.run_consensus_scoring",
                   AsyncMock(return_value=mock_result)):
            state_update = await consensus_score_risk({
                "pr_diff": PR_DIFF,
                "retrieval_context": [],
            })

        assert state_update["consensus_forced_hitl"] is True
        assert "Bucket disagreement" in state_update["consensus_forced_reason"]


# ── HITL gate check tests ─────────────────────────────────────────────────────

class TestConsensusRiskGateCheck:

    def test_triggers_on_high_score(self):
        state = {"risk_score": 0.90, "consensus_forced_hitl": False}
        result = consensus_risk_gate_check(state)
        assert result["hitl_required"] is True

    def test_triggers_on_forced_hitl_even_with_low_score(self):
        state = {"risk_score": 0.40, "consensus_forced_hitl": True}
        result = consensus_risk_gate_check(state)
        assert result["hitl_required"] is True

    def test_no_hitl_when_consensus_low_score(self):
        state = {"risk_score": 0.30, "consensus_forced_hitl": False}
        result = consensus_risk_gate_check(state)
        assert result["hitl_required"] is False

    def test_triggers_when_both_conditions_true(self):
        state = {"risk_score": 0.92, "consensus_forced_hitl": True}
        result = consensus_risk_gate_check(state)
        assert result["hitl_required"] is True

    def test_defaults_safely_without_consensus_field(self):
        state = {"risk_score": 0.50}
        result = consensus_risk_gate_check(state)
        assert result["hitl_required"] is False


# ── Consensus mode tests ──────────────────────────────────────────────────────

from pipeline.consensus import ConsensusConfig, _check_unanimous, _check_majority, _check_weighted

CFG_UNANIMOUS = ConsensusConfig(mode="unanimous", variance_threshold=0.20)
CFG_MAJORITY  = ConsensusConfig(mode="majority",  variance_threshold=0.20)
CFG_WEIGHTED  = ConsensusConfig(mode="weighted",  variance_threshold=0.20)

# Votes: 2 HIGH, 1 MEDIUM — majority agrees HIGH
TWO_HIGH_ONE_MEDIUM = [
    ModelVote("gpt-4o",           0.78, [], "", "HIGH"),
    ModelVote("claude-sonnet-4-6",0.80, [], "", "HIGH"),
    ModelVote("gemini-1.5-pro",   0.55, [], "", "MEDIUM"),
]


class TestUnanimousMode:
    def test_fails_on_two_high_one_medium(self):
        agreed, reason = _check_unanimous(TWO_HIGH_ONE_MEDIUM, CFG_UNANIMOUS)
        assert not agreed
        assert "Bucket disagreement" in reason

    def test_passes_when_all_same_bucket_low_std(self):
        votes = [
            ModelVote("a", 0.78, [], "", "HIGH"),
            ModelVote("b", 0.79, [], "", "HIGH"),
            ModelVote("c", 0.77, [], "", "HIGH"),
        ]
        agreed, _ = _check_unanimous(votes, CFG_UNANIMOUS)
        assert agreed


class TestMajorityMode:
    def test_passes_on_two_high_one_medium(self):
        agreed, reason = _check_majority(TWO_HIGH_ONE_MEDIUM, CFG_MAJORITY)
        assert agreed
        assert reason == ""

    def test_fails_when_all_different_buckets(self):
        votes = [
            ModelVote("a", 0.30, [], "", "LOW"),
            ModelVote("b", 0.55, [], "", "MEDIUM"),
            ModelVote("c", 0.78, [], "", "HIGH"),
        ]
        agreed, reason = _check_majority(votes, CFG_MAJORITY)
        assert not agreed
        assert "No bucket has >= 2 votes" in reason

    def test_fails_on_high_variance_even_with_majority_bucket(self):
        votes = [
            ModelVote("a", 0.78, [], "", "HIGH"),
            ModelVote("b", 0.79, [], "", "HIGH"),
            ModelVote("c", 0.20, [], "", "LOW"),   # outlier pulls variance up
        ]
        agreed, reason = _check_majority(votes, CFG_MAJORITY)
        assert not agreed
        assert "variance" in reason.lower()


class TestWeightedMode:
    def test_passes_regardless_of_buckets_if_low_variance(self):
        votes = [
            ModelVote("a", 0.78, [], "", "HIGH"),
            ModelVote("b", 0.80, [], "", "HIGH"),
            ModelVote("c", 0.55, [], "", "MEDIUM"),  # different bucket — OK in weighted
        ]
        agreed, _ = _check_weighted(votes, CFG_WEIGHTED)
        # std([0.78,0.80,0.55]) ≈ 0.136 < 0.20 → should pass
        assert agreed

    def test_fails_on_high_variance(self):
        votes = [
            ModelVote("a", 0.90, [], "", "CRITICAL"),
            ModelVote("b", 0.91, [], "", "CRITICAL"),
            ModelVote("c", 0.20, [], "", "LOW"),
        ]
        agreed, reason = _check_weighted(votes, CFG_WEIGHTED)
        assert not agreed
        assert "variance" in reason.lower()


class TestConsensusConfigFromEnv:
    def test_defaults_to_unanimous(self, monkeypatch):
        monkeypatch.delenv("CONSENSUS_MODE", raising=False)
        cfg = ConsensusConfig.from_env()
        assert cfg.mode == "unanimous"

    def test_reads_majority_from_env(self, monkeypatch):
        monkeypatch.setenv("CONSENSUS_MODE", "majority")
        cfg = ConsensusConfig.from_env()
        assert cfg.mode == "majority"

    def test_reads_weighted_from_env(self, monkeypatch):
        monkeypatch.setenv("CONSENSUS_MODE", "weighted")
        cfg = ConsensusConfig.from_env()
        assert cfg.mode == "weighted"

    def test_falls_back_on_unknown_mode(self, monkeypatch):
        monkeypatch.setenv("CONSENSUS_MODE", "banana")
        cfg = ConsensusConfig.from_env()
        assert cfg.mode == "unanimous"

    def test_reads_variance_threshold_from_env(self, monkeypatch):
        monkeypatch.setenv("CONSENSUS_VARIANCE_THRESHOLD", "0.15")
        cfg = ConsensusConfig.from_env()
        assert cfg.variance_threshold == pytest.approx(0.15)


class TestModeEndToEnd:
    @pytest.mark.asyncio
    async def test_majority_mode_passes_two_high_one_medium(self):
        cfg = ConsensusConfig(mode="majority", variance_threshold=0.20)
        with patch("pipeline.consensus._call_openai",  AsyncMock(return_value=TWO_HIGH_ONE_MEDIUM[0])), \
             patch("pipeline.consensus._call_claude",  AsyncMock(return_value=TWO_HIGH_ONE_MEDIUM[1])), \
             patch("pipeline.consensus._call_gemini",  AsyncMock(return_value=TWO_HIGH_ONE_MEDIUM[2])):
            result = await run_consensus_scoring(PR_DIFF, CONTEXT, config=cfg)
        assert result.consensus_reached is True
        assert result.forced_hitl is False
        assert result.consensus_mode == "majority"

    @pytest.mark.asyncio
    async def test_unanimous_mode_fails_two_high_one_medium(self):
        cfg = ConsensusConfig(mode="unanimous", variance_threshold=0.20)
        with patch("pipeline.consensus._call_openai",  AsyncMock(return_value=TWO_HIGH_ONE_MEDIUM[0])), \
             patch("pipeline.consensus._call_claude",  AsyncMock(return_value=TWO_HIGH_ONE_MEDIUM[1])), \
             patch("pipeline.consensus._call_gemini",  AsyncMock(return_value=TWO_HIGH_ONE_MEDIUM[2])):
            result = await run_consensus_scoring(PR_DIFF, CONTEXT, config=cfg)
        assert result.forced_hitl is True
        assert result.consensus_mode == "unanimous"
