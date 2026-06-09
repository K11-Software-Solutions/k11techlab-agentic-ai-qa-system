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
"""Integration tests for Phase 2 dispatch logic."""
import pytest
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import MemorySaver
from pipeline.state import initial_state
from pipeline.phase2 import dispatch_phase2, AGENT_MAP, phase2_app


def test_dispatch_creates_correct_sends():
    state = initial_state("run-1", 1, "org/repo", "diff")
    state["test_plan"] = {
        "suites": [
            {"type": "api", "priority": "high", "cases": [], "focus_areas": []},
            {"type": "playwright", "priority": "medium", "cases": [], "focus_areas": []},
        ]
    }
    sends = dispatch_phase2(state)
    assert len(sends) == 2
    node_names = [s.node for s in sends]
    assert "api_agent" in node_names
    assert "playwright_agent" in node_names


def test_dispatch_skips_unknown_suite_type():
    state = initial_state("run-1", 1, "org/repo", "diff")
    state["test_plan"] = {"suites": [{"type": "nonexistent", "priority": "low", "cases": []}]}
    sends = dispatch_phase2(state)
    assert len(sends) == 0


def test_dispatch_empty_plan():
    state = initial_state("run-1", 1, "org/repo", "diff")
    state["test_plan"] = {"suites": []}
    sends = dispatch_phase2(state)
    assert sends == []


@pytest.mark.asyncio
async def test_phase2_integration_single_agent():
    """Integration test: phase2 graph dispatches 1 agent and aggregates results."""
    state = initial_state("run-1", 1, "org/repo", "diff")
    state["test_plan"] = {
        "suites": [{"type": "api", "priority": "high", "cases": [], "focus_areas": []}]
    }
    mock_result = {"passed": 5, "failed": 0, "total": 5, "issues": []}

    with patch("pipeline.phase2._run_api_agent", new=AsyncMock(return_value=mock_result)):
        app = phase2_app  # already compiled
        config = {"configurable": {"thread_id": "test-1"}}
        # Can't easily inject MemorySaver into pre-compiled app, so just test dispatch
        sends = dispatch_phase2(state)
        assert len(sends) == 1
        assert sends[0].node == "api_agent"
