"""Unit tests for HITL routing."""
import pytest
from pipeline.state import initial_state
from pipeline.hitl import route_after_hitl, RISK_THRESHOLD


def _state(**overrides):
    s = initial_state("run-1", 1, "org/repo", "diff")
    s.update(overrides)
    return s


def test_low_risk_proceeds_without_review():
    s = _state(risk_score=0.5, hitl_required=False)
    assert route_after_hitl(s) == "proceed"


def test_approved_proceeds():
    s = _state(risk_score=0.9, hitl_required=True, hitl_decision="approve")
    assert route_after_hitl(s) == "proceed"


def test_rejected_terminates():
    s = _state(risk_score=0.9, hitl_required=True, hitl_decision="reject")
    assert route_after_hitl(s) == "reject"


def test_threshold_boundary():
    assert RISK_THRESHOLD == 0.85
