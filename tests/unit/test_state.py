"""Unit tests for state helpers."""
import pytest
from pipeline.state import initial_state, CIPipelineState


def test_initial_state_defaults():
    s = initial_state("run-1", 10, "org/repo", "diff text")
    assert s["run_id"] == "run-1"
    assert s["pr_number"] == 10
    assert s["risk_score"] == 0.0
    assert s["test_results"] == []
    assert s["defects"] == []
    assert s["errors"] == []
    assert s["hitl_required"] is False
    assert s["hitl_decision"] is None
    assert s["eval_passed"] is None
    assert s["pipeline_version"] == "2.0.0"
    assert s["completed_at"] is None


def test_initial_state_started_at_is_iso():
    from datetime import datetime
    s = initial_state("run-2", 1, "org/repo", "diff")
    dt = datetime.fromisoformat(s["started_at"])
    assert dt is not None
