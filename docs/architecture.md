# System Architecture

## Overview

The K11tech Agentic QA System is a LangGraph-orchestrated CI/CD quality gate that
automatically analyses pull requests, dispatches specialist AI agents, and files defects —
all without human intervention unless the risk score exceeds the configured threshold.

```
GitHub Webhook (PR opened / synchronize)
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  PHASE 1 — Analysis (parallel fan-out)                        │
│                                                               │
│  pr_context_fetcher ──┐                                       │
│                       ├──► score_risk ──► generate_test_plan  │
│  retrieve_knowledge  ─┘                                       │
└──────────────────────────────────┬────────────────────────────┘
                                   │
                       ┌───────────▼───────────┐
                       │  HITL Gate            │
                       │  interrupt() if       │
                       │  risk_score >= 0.85   │
                       └───────────┬───────────┘
                                   │ approve
┌──────────────────────────────────▼────────────────────────────┐
│  PHASE 2 — Parallel Agent Execution (Send API)                │
│                                                               │
│  api_probe    playwright   perf_agent    security_agent       │
│  data_agent   browser      a11y_agent    regression_agent     │
└──────────────────────────────────┬────────────────────────────┘
                                   │
┌──────────────────────────────────▼────────────────────────────┐
│  PHASE 3 — Reporting                                          │
│                                                               │
│  aggregate_results ──► generate_report ──► file_jira         │
│                    └──► send_slack                            │
└──────────────────────────────────┬────────────────────────────┘
                                   │
┌──────────────────────────────────▼────────────────────────────┐
│  EVALUATION — DeepEval + RAGAS (parallel)                     │
│                                                               │
│  deepeval_node ──┐                                            │
│                  ├──► aggregate_eval ──► quality_gate         │
│  ragas_node    ──┘                                            │
└───────────────────────────────────────────────────────────────┘
```

## Components

### Pipeline (`pipeline/`)

| File | Responsibility |
|------|----------------|
| `state.py` | `CIPipelineState` TypedDict — single source of truth across all phases |
| `phase1.py` | Analysis subgraph: parallel PR fetch + knowledge retrieval → risk scoring → test planning |
| `phase2.py` | 8-agent parallel dispatch using LangGraph Send API |
| `phase3.py` | Reporting subgraph: aggregate → report + Jira + Slack |
| `evaluation.py` | DeepEval + RAGAS eval subgraph with quality gate |
| `hitl.py` | HITL interrupt/resume nodes |
| `orchestrator.py` | Main `ci_builder` StateGraph that wires all subgraphs |
| `runner.py` | Public API: `run_pipeline()`, `submit_hitl_decision()`, `get_pipeline_state()` |

### Agents (`agents/`)

14 specialist agents extend `BaseQAAgent`.  Each agent wraps its `execute()` with
`asyncio.wait_for` (300 s default) and `tenacity` retry (3 attempts, exponential back-off).

| Agent | Phase | MCP Server Used |
|-------|-------|-----------------|
| `PRContextFetcherAgent` | 1 | GitHub |
| `KnowledgeRetrieverAgent` | 1 | Knowledge Store |
| `RiskAssessorAgent` | 1 | LLM (OpenAI) |
| `TestPlannerAgent` | 1 | LLM (OpenAI) |
| `APIProbeAgent` | 2 | HTTP direct |
| `PlaywrightAgent` | 2 | Playwright |
| `PerformanceAgent` | 2 | k6 |
| `SecurityAgent` | 2 | GitHub + diff scan |
| `DataValidationAgent` | 2 | Postgres |
| `CrossBrowserAgent` | 2 | Playwright |
| `AccessibilityAgent` | 2 | Playwright (axe) |
| `RegressionAgent` | 2 | Knowledge Store + HTTP |
| `ReportGeneratorAgent` | 3 | LLM (OpenAI) |
| `DefectFilerAgent` | 3 | Jira |

### MCP Clients (`mcps/`)

Thin async HTTP wrappers over each MCP server.  All clients extend `BaseMCPClient`
and expose convenience methods.  Use `mcps.build_mcp_clients()` to instantiate all 7 at once.

| Client | Default Port | Env Var |
|--------|-------------|---------|
| `GitHubMCPClient` | 8001 | `GITHUB_MCP_URL` |
| `PlaywrightMCPClient` | 8002 | `PLAYWRIGHT_MCP_URL` |
| `K6MCPClient` | 8003 | `K6_MCP_URL` |
| `JiraMCPClient` | 8004 | `JIRA_MCP_URL` |
| `PostgresMCPClient` | 8005 | `POSTGRES_MCP_URL` |
| `SlackMCPClient` | 8006 | `SLACK_MCP_URL` |
| `KnowledgeStoreMCPClient` | 8007 | `KNOWLEDGE_STORE_MCP_URL` |

### API (`api/`)

FastAPI webhook server:

- `POST /webhook/github` — receives PR events, verifies HMAC, triggers background pipeline
- `POST /api/hitl/decision` — resumes a paused (HITL) pipeline
- `POST /api/slack/command` — handles `/qa-approve` and `/qa-reject` slash commands
- `GET /api/pipeline/{run_id}/status` — returns pipeline verdict and metrics
- `GET /health`

## State Management

`CIPipelineState` is a `TypedDict` with fields owned by each phase.
Reducers (`Annotated[list, operator.add]`) on `test_results`, `defects`, and `errors`
allow concurrent Phase 2 agents to append results without race conditions.

Checkpointing uses `SqliteSaver` (local) or `PostgresSaver` (production).
Each run is identified by a `run_id` (UUID) used as the LangGraph `thread_id`.

## HITL Flow

1. `risk_gate_check` evaluates `risk_score >= 0.85`
2. If true, `human_review_gate` calls `interrupt()` — pipeline pauses
3. Reviewer calls `POST /api/hitl/decision` or Slack `/qa-approve`
4. `submit_hitl_decision()` calls `aupdate_state()` to resume
5. Graph routes to `phase2` (approved) or `pipeline_rejected` (rejected)
