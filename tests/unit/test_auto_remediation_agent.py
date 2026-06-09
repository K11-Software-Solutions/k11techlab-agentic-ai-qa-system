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
# -*- coding: utf-8 -*-
"""
tests/unit/test_auto_remediation_agent.py
──────────────────────────────────────────
Unit tests for AutoRemediationAgent.

All MCP calls and LLM calls are mocked — no external dependencies required.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.auto_remediation_agent import (
    AutoRemediationAgent,
    SAFE_CLASSES,
    CONFIDENCE_THRESHOLD,
    RemediationPatch,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAFE_DEFECT = {
    "id": "d-001",
    "defect_class": "missing_docstring",
    "file_path": "agents/risk_assessor.py",
    "description": "Public function score_risk() missing docstring",
    "context": "def score_risk(state: dict) -> float:\n    pass",
}

UNSAFE_DEFECT = {
    "id": "d-002",
    "defect_class": "sql_injection_pattern",
    "file_path": "api/webhook.py",
    "description": "Unsanitised SQL query in webhook handler",
}

MOCK_PATCH_OUTPUT = """\
--- a/agents/risk_assessor.py
+++ b/agents/risk_assessor.py
@@ -1,2 +1,5 @@
+\"\"\"Score the risk of a pull request.\"\"\"
 def score_risk(state: dict) -> float:
     pass
CONFIDENCE: 0.92
"""


@pytest.fixture
def mcp_clients():
    github = AsyncMock()
    github.call_tool = AsyncMock(return_value={
        "content": "def score_risk(state: dict) -> float:\n    pass",
    })
    return {"github": github}


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=MOCK_PATCH_OUTPUT))
    return llm


@pytest.fixture
def agent(mcp_clients, mock_llm):
    return AutoRemediationAgent(mcp_clients=mcp_clients, llm=mock_llm)


@pytest.fixture
def base_state():
    return {
        "run_id":           "run-test-0001",
        "pr_number":        42,
        "repo_name":        "K11-Software-Solutions/test-repo",
        "pr_diff":          "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x=1\n+x=2",
        "base_branch":      "main",
        "pipeline_version": "2.0.0",
        "defects":          [SAFE_DEFECT],
        "errors":           [],
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFilterRemediable:
    def test_safe_defect_included(self, agent):
        result = agent._filter_remediable([SAFE_DEFECT])
        assert len(result) == 1

    def test_unsafe_defect_excluded(self, agent):
        result = agent._filter_remediable([UNSAFE_DEFECT])
        assert len(result) == 0

    def test_mixed_defects(self, agent):
        result = agent._filter_remediable([SAFE_DEFECT, UNSAFE_DEFECT])
        assert len(result) == 1
        assert result[0]["defect_class"] == "missing_docstring"

    def test_all_safe_classes_accepted(self, agent):
        defects = [
            {"id": f"d-{i}", "defect_class": cls,
             "file_path": "x.py", "description": "test"}
            for i, cls in enumerate(SAFE_CLASSES)
        ]
        result = agent._filter_remediable(defects)
        assert len(result) == len(SAFE_CLASSES)


class TestParseLLMOutput:
    def test_parses_patch_and_confidence(self):
        patch_text, confidence = AutoRemediationAgent._parse_llm_output(MOCK_PATCH_OUTPUT)
        assert "score_risk" in patch_text
        assert confidence == pytest.approx(0.92)

    def test_missing_confidence_returns_zero(self):
        raw = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n+# comment"
        _, confidence = AutoRemediationAgent._parse_llm_output(raw)
        assert confidence == 0.0

    def test_confidence_not_in_patch(self):
        patch_text, _ = AutoRemediationAgent._parse_llm_output(MOCK_PATCH_OUTPUT)
        assert "CONFIDENCE" not in patch_text


class TestGeneratePatch:
    @pytest.mark.asyncio
    async def test_generates_patch_above_threshold(self, agent):
        patch = await agent._generate_patch(SAFE_DEFECT, "K11/repo")
        assert not patch.skipped
        assert patch.confidence >= CONFIDENCE_THRESHOLD
        assert patch.defect_class == "missing_docstring"

    @pytest.mark.asyncio
    async def test_skips_patch_below_threshold(self, agent, mock_llm):
        low_conf_output = MOCK_PATCH_OUTPUT.replace("0.92", "0.50")
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=low_conf_output))
        patch = await agent._generate_patch(SAFE_DEFECT, "K11/repo")
        assert patch.skipped
        assert "below threshold" in patch.skip_reason

    @pytest.mark.asyncio
    async def test_handles_llm_failure_gracefully(self, agent, mock_llm):
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM unavailable"))
        patch = await agent._generate_patch(SAFE_DEFECT, "K11/repo")
        assert patch.skipped
        assert "LLM call failed" in patch.skip_reason


class TestExecute:
    @pytest.mark.asyncio
    async def test_skips_when_no_remediable_defects(self, agent, base_state):
        base_state["defects"] = [UNSAFE_DEFECT]
        result = await agent.run(base_state, {"suite_type": "remediation"})
        assert result.metadata.get("skipped_reason") == "no_remediable_defects"
        assert result.passed == 0

    @pytest.mark.asyncio
    async def test_creates_pr_for_safe_defects(self, agent, mcp_clients, base_state):
        mcp_clients["github"].call_tool = AsyncMock(side_effect=[
            {"content": "def score_risk(): pass"},   # get_file_content
            {},                                        # create_branch
            {},                                        # apply_patch
            {"html_url": "https://github.com/K11/repo/pull/99", "number": 99},  # create_pr
        ])
        result = await agent.run(base_state, {"suite_type": "remediation"})
        assert result.passed >= 1
        assert result.metadata.get("remediation_pr_url") == \
               "https://github.com/K11/repo/pull/99"

    @pytest.mark.asyncio
    async def test_handles_github_mcp_failure(self, agent, mcp_clients, base_state):
        mcp_clients["github"].call_tool = AsyncMock(side_effect=[
            {"content": "def score_risk(): pass"},
            Exception("GitHub API rate limit"),
        ])
        result = await agent.run(base_state, {"suite_type": "remediation"})
        # Should not raise — error captured in metadata
        assert result.error or result.metadata.get("error")


class TestShouldRemediate:
    def test_returns_remediate_when_safe_defects_present(self):
        from pipeline.remediation import should_remediate
        state = {"defects": [SAFE_DEFECT]}
        assert should_remediate(state) == "remediate"

    def test_returns_skip_when_no_safe_defects(self):
        from pipeline.remediation import should_remediate
        state = {"defects": [UNSAFE_DEFECT]}
        assert should_remediate(state) == "skip_remediation"

    def test_returns_skip_when_defects_empty(self):
        from pipeline.remediation import should_remediate
        assert should_remediate({"defects": []}) == "skip_remediation"
