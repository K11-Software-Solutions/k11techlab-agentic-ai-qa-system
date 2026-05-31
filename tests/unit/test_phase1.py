"""Unit tests for Phase 1 nodes."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pipeline.state import initial_state
from pipeline.phase1 import score_risk, generate_test_plan, _parse_json, _parse_files_from_diff


def _make_state(**overrides):
    s = initial_state("run-test", 42, "org/repo", "+ def login(): pass")
    s.update(overrides)
    return s


class TestParseJson:
    def test_plain_json(self):
        result = _parse_json('{"risk_score": 0.8, "risk_factors": ["auth"]}')
        assert result["risk_score"] == 0.8

    def test_json_in_code_fence(self):
        text = '```json\n{"risk_score": 0.5}\n```'
        assert _parse_json(text)["risk_score"] == 0.5

    def test_invalid_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json("not json")


class TestParseFilesFromDiff:
    def test_extracts_files(self):
        diff = "+++ b/src/auth.py\n--- a/src/auth.py\n+++ b/src/login.py"
        files = _parse_files_from_diff(diff)
        assert "src/auth.py" in files
        assert "src/login.py" in files


@pytest.mark.asyncio
class TestScoreRisk:
    async def test_auth_change_high_risk(self):
        state = _make_state(
            pr_diff="+ def authenticate(user, pwd): return db.query(...)",
            retrieval_context=["Auth modules require security testing"],
        )
        mock_resp = MagicMock(content='{"risk_score": 0.9, "risk_factors": ["auth change", "sql injection risk"]}')
        with patch("pipeline.phase1._risk_llm") as mock_llm:
            chain_mock = AsyncMock(return_value=mock_resp)
            mock_llm.__ror__ = MagicMock(return_value=chain_mock)
            with patch("pipeline.phase1._RISK_PROMPT.__or__", return_value=AsyncMock(return_value=mock_resp)):
                # Direct invocation test
                with patch("pipeline.phase1._RISK_PROMPT") as mock_prompt:
                    mock_chain = MagicMock()
                    mock_chain.ainvoke = AsyncMock(return_value=mock_resp)
                    mock_prompt.__or__ = MagicMock(return_value=mock_chain)
                    result = await score_risk(state)
        assert result["risk_score"] == pytest.approx(0.9)
        assert "auth change" in result["risk_factors"]

    async def test_fallback_on_error(self):
        state = _make_state()
        with patch("pipeline.phase1._RISK_PROMPT") as mock_prompt:
            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            result = await score_risk(state)
        assert result["risk_score"] == 0.5
        assert "risk assessment failed" in result["risk_factors"]


@pytest.mark.asyncio
class TestGenerateTestPlan:
    async def test_produces_valid_plan(self):
        state = _make_state(
            risk_score=0.8,
            risk_factors=["auth change"],
            retrieval_context=[],
        )
        plan_json = '{"suites": [{"type": "api", "priority": "high", "cases": ["test login"], "focus_areas": ["auth"]}], "rationale": "auth change detected"}'
        mock_resp = MagicMock(content=plan_json)
        with patch("pipeline.phase1._PLAN_PROMPT") as mock_prompt:
            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(return_value=mock_resp)
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            result = await generate_test_plan(state)
        assert len(result["test_plan"]["suites"]) == 1
        assert result["test_plan"]["suites"][0]["type"] == "api"
        assert "api" in result["test_plan_text"]
