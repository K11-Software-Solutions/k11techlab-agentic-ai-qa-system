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
