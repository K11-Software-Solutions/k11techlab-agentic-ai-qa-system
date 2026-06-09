# Copyright 2026 Kavita Jadhav / K11 Software Solutions LLC
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
End-to-end smoke tests for the full pipeline.
Uses MemorySaver and mocked MCP clients — no real external services.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from pipeline.state import initial_state
from pipeline.runner import run_pipeline

FIXTURE_DIFF = """
diff --git a/src/utils.py b/src/utils.py
index abc123..def456 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -10,4 +10,6 @@
 def format_date(dt):
     return dt.strftime("%Y-%m-%d")
+
+def truncate_string(s, max_len=100):
+    return s[:max_len] if len(s) > max_len else s
"""

MOCK_RISK_RESPONSE = MagicMock(
    content='{"risk_score": 0.3, "risk_factors": ["utility change"]}'
)
MOCK_PLAN_RESPONSE = MagicMock(
    content='{"suites": [{"type": "api", "priority": "low", "cases": ["test truncate"], "focus_areas": []}], "rationale": "low-risk utility"}'
)
MOCK_REPORT_RESPONSE = MagicMock(
    content="# CI Report\n\n**Verdict:** PASS\n\nAll tests passed."
)


@pytest.mark.asyncio
async def test_happy_path_low_risk():
    """Full pipeline with low-risk PR — should skip HITL gate and reach evaluation."""
    mock_api_result = {
        "passed": 3, "failed": 0, "total": 3,
        "issues": [], "duration_s": 1.2,
    }

    with (
        patch("pipeline.phase1.github_mcp.call_tool", new=AsyncMock(return_value={"files": [{"filename": "src/utils.py"}]})),
        patch("pipeline.phase1.knowledge_store_mcp.call_tool", new=AsyncMock(return_value={"results": []})),
        patch("pipeline.phase1._RISK_PROMPT") as mock_rp,
        patch("pipeline.phase1._PLAN_PROMPT") as mock_pp,
        patch("pipeline.phase2._run_api_agent", new=AsyncMock(return_value=mock_api_result)),
        patch("pipeline.phase3.jira_mcp.call_tool", new=AsyncMock(return_value={"issue_key": "QA-1"})),
        patch("pipeline.phase3.slack_mcp.call_tool", new=AsyncMock(return_value={})),
        patch("pipeline.phase3._report_llm") as mock_rl,
        patch("pipeline.hitl.slack_mcp.call_tool", new=AsyncMock(return_value={})),
    ):
        # Wire up LLM chain mocks
        for mock_prompt, mock_resp in [(mock_rp, MOCK_RISK_RESPONSE), (mock_pp, MOCK_PLAN_RESPONSE)]:
            chain = MagicMock()
            chain.ainvoke = AsyncMock(return_value=mock_resp)
            mock_prompt.__or__ = MagicMock(return_value=chain)

        report_chain = MagicMock()
        report_chain.ainvoke = AsyncMock(return_value=MOCK_REPORT_RESPONSE)
        mock_rl.__ror__ = MagicMock(return_value=report_chain)

        result = await run_pipeline(
            pr_number=999,
            repo_name="org/test-repo",
            pr_diff=FIXTURE_DIFF,
            use_memory=True,
        )

    assert result is not None
    assert result["hitl_required"] is False
    assert result["hitl_decision"] is None
    assert result.get("final_report") is not None
    assert result.get("summary") is not None
    # eval may be None if deepeval/ragas not installed in test env
    assert "eval_passed" in result
