# Agent Reference

All agents extend `BaseQAAgent` from `agents/base.py`.

## BaseQAAgent Contract

```python
class BaseQAAgent(ABC):
    NAME: str            # unique identifier
    TIMEOUT: int = 300   # asyncio timeout in seconds
    RETRIES: int = 3     # tenacity retry count

    async def run(state: dict, suite: dict) -> AgentResult
    async def execute(state: dict, suite: dict) -> AgentResult  # implement this
    async def call_mcp(server: str, tool: str, args: dict) -> dict
    def result_from_mcp(suite: dict, raw: dict) -> AgentResult
```

`run()` wraps `execute()` with:
1. `asyncio.wait_for(timeout=TIMEOUT)` — returns error AgentResult on timeout
2. `tenacity.retry(stop_after_attempt(3), wait_exponential(...))` — retries on `MCPError`

## AgentResult Fields

| Field | Type | Description |
|-------|------|-------------|
| `agent` | str | Agent NAME |
| `suite_type` | str | Test suite category |
| `priority` | str | high / medium / low |
| `passed` | int | Cases passed |
| `failed` | int | Cases failed |
| `total_cases` | int | Total cases run |
| `duration_s` | float | Wall-clock time (set by `run()`) |
| `defects` | list[dict] | Defect records |
| `metadata` | dict | Agent-specific metrics |
| `error` | str \| None | Top-level error (None = success) |

---

## Phase 1 Agents

### PRContextFetcherAgent
**File:** `agents/pr_context_fetcher.py`
**MCP:** GitHub

Fetches PR diff, list of changed files, and PR metadata (author, labels, base branch) from the GitHub MCP server. Stores results in `metadata` for use by downstream Phase 1 agents.

### KnowledgeRetrieverAgent
**File:** `agents/knowledge_retriever.py`
**MCP:** Knowledge Store

Performs semantic search on historical defect records and runbooks. Builds a query from changed file names and the first 200 chars of the diff. Returns `retrieval_context` — a list of relevant text snippets.

### RiskAssessorAgent
**File:** `agents/risk_assessor.py`
**LLM:** `RISK_MODEL` (default: `gpt-4o-mini`)

Scores PR risk from 0–1. Inputs: PR diff (first 4000 chars), changed files, retrieval context. Output JSON: `{"risk_score": float, "risk_factors": [str]}`. Risk score drives the HITL gate.

### TestPlannerAgent
**File:** `agents/test_planner.py`
**LLM:** `PLANNER_MODEL` (default: `gpt-4o-mini`)

Generates a JSON test plan with a list of suites. Each suite has `suite_type`, `priority`, `focus_areas`, and `estimated_duration_min`. The plan drives Phase 2 dispatch via the LangGraph Send API.

---

## Phase 2 Agents

### APIProbeAgent
**File:** `agents/api_probe.py`
**Transport:** httpx direct

Probes REST endpoints with httpx. Infers endpoints from changed router files or uses suite metadata. Runs all endpoint checks concurrently with `asyncio.gather`.

### PlaywrightAgent
**File:** `agents/playwright_agent.py`
**MCP:** Playwright

Executes E2E browser scenarios via the Playwright MCP server. Maps focus areas to step sequences. Built-in scenario library includes `login` and `checkout` flows.

### PerformanceAgent
**File:** `agents/perf_agent.py`
**MCP:** k6

Runs k6 load tests. Default thresholds: p95 < 2000 ms, error rate < 1%. Reports threshold violations as high-severity defects.

### SecurityAgent
**File:** `agents/security_agent.py`
**MCP:** GitHub (secret scanning)

Three-layer scan: (1) regex patterns for AWS keys, API keys, bearer tokens, password literals in the diff; (2) GitHub secret scanning alerts via MCP; (3) flag changed dependency files for manual CVE review.

### DataValidationAgent
**File:** `agents/data_agent.py`
**MCP:** Postgres

Only activates when migration files are detected (`alembic`, `.sql`, `migration` in path). Runs SQL integrity checks via the Postgres MCP's `execute_query` tool in read-only mode.

### CrossBrowserAgent
**File:** `agents/browser_agent.py`
**MCP:** Playwright

Runs the same scenario across Chromium, Firefox, and WebKit. Optionally compares screenshots for visual regressions using the `compare_screenshots` tool.

### AccessibilityAgent
**File:** `agents/a11y_agent.py`
**MCP:** Playwright (axe-core)

Audits pages against WCAG 2.1 AA. Reports each axe-core violation as a separate defect with severity mapped from impact level (critical/serious/moderate/minor).

### RegressionAgent
**File:** `agents/regression_agent.py`
**MCP:** Knowledge Store + httpx

Fetches historical test cases relevant to changed files from the Knowledge Store, then re-runs them via httpx. Skips gracefully if no matching cases exist.

---

## Phase 3 Agents

### ReportGeneratorAgent
**File:** `agents/report_generator.py`
**LLM:** `REPORT_MODEL` (default: `gpt-4o-mini`)

Aggregates all Phase 2 results into a compact JSON payload and asks the LLM to produce a professional Markdown QA report with executive summary, results table, critical defects, risk assessment, and a APPROVE/BLOCK/NEEDS_REVIEW recommendation.

### DefectFilerAgent
**File:** `agents/defect_filer.py`
**MCP:** Jira

Files Jira Bug tickets for high/critical defects. De-duplicates by checking existing open tickets with matching labels before creating. Attaches the PR number as a Jira label (`pr-{number}`) for easy tracking.

---

## Adding a New Agent

1. Create `agents/my_agent.py` extending `BaseQAAgent`
2. Set `NAME`, `TIMEOUT`, and implement `execute()`
3. Register in `agents/__init__.py`
4. Add the suite type to `AGENT_MAP` in `pipeline/phase2.py`
