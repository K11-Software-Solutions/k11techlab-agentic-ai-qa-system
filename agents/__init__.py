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
"""K11tech Agentic AI QA Agents — all 14 specialist agents."""

from .base import AgentResult, BaseQAAgent, MCPError

# Phase 1 — Analysis
from .pr_context_fetcher import PRContextFetcherAgent
from .knowledge_retriever import KnowledgeRetrieverAgent
from .risk_assessor import RiskAssessorAgent
from .test_planner import TestPlannerAgent

# Phase 2 — Parallel test execution
from .api_probe import APIProbeAgent
from .playwright_agent import PlaywrightAgent
from .perf_agent import PerformanceAgent
from .security_agent import SecurityAgent
from .data_agent import DataValidationAgent
from .browser_agent import CrossBrowserAgent
from .a11y_agent import AccessibilityAgent
from .regression_agent import RegressionAgent

# Phase 3 — Reporting
from .report_generator import ReportGeneratorAgent
from .defect_filer import DefectFilerAgent

__all__ = [
    "AgentResult",
    "BaseQAAgent",
    "MCPError",
    # Phase 1
    "PRContextFetcherAgent",
    "KnowledgeRetrieverAgent",
    "RiskAssessorAgent",
    "TestPlannerAgent",
    # Phase 2
    "APIProbeAgent",
    "PlaywrightAgent",
    "PerformanceAgent",
    "SecurityAgent",
    "DataValidationAgent",
    "CrossBrowserAgent",
    "AccessibilityAgent",
    "RegressionAgent",
    # Phase 3
    "ReportGeneratorAgent",
    "DefectFilerAgent",
]
