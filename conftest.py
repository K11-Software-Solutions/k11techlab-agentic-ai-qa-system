"""Shared pytest configuration."""
import os
import pytest

# Ensure no real external calls during tests
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")


@pytest.fixture
def low_risk_state():
    from pipeline.state import initial_state
    s = initial_state("run-test-001", 42, "org/repo", "+ def helper(): pass")
    s["risk_score"] = 0.2
    s["risk_factors"] = ["minor utility change"]
    s["test_plan"] = {"suites": [{"type": "api", "priority": "low", "cases": [], "focus_areas": []}]}
    s["test_plan_text"] = "API testing only."
    s["retrieval_context"] = ["Utility functions require basic unit testing."]
    s["changed_files"] = ["src/utils.py"]
    return s


@pytest.fixture
def high_risk_state():
    from pipeline.state import initial_state
    s = initial_state("run-test-002", 43, "org/repo", "+ def authenticate(u,p): return db.exec(f'SELECT * FROM users WHERE u={u}')")
    s["risk_score"] = 0.92
    s["risk_factors"] = ["auth change", "sql injection risk", "security config"]
    s["test_plan"] = {
        "suites": [
            {"type": "api",      "priority": "high",   "cases": [], "focus_areas": ["auth"]},
            {"type": "security", "priority": "critical","cases": [], "focus_areas": ["sql-injection"]},
        ]
    }
    s["hitl_required"] = True
    return s
