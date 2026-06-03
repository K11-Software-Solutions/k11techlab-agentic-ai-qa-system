# I Built a QA System That Reviews Pull Requests So My Team Doesn't Have To

*How 14 AI agents, 7 MCP servers, and LangGraph turned our CI/CD pipeline into an autonomous quality gate*

---

Every engineering team I've worked with has the same problem.

A developer opens a pull request at 4pm on a Friday. The change touches authentication. The risk score is high. But the QA engineer is in a meeting, the test suite takes 45 minutes to run manually, and everyone wants to ship before the weekend.

So the PR gets merged. And at 9am Monday, production is on fire.

I've spent the last several months building a system to make that scenario impossible. Not by adding more process — but by removing humans from the parts of QA where they shouldn't need to be involved at all.

---

## What the System Does

The K11tech Agentic AI QA System is a LangGraph-orchestrated CI/CD pipeline that activates the moment a pull request is opened.

It does four things, fully automatically:

**1. Analyses the PR** — reads the diff, retrieves historical defect patterns from a knowledge store, scores the risk from 0 to 1, and generates a tailored test plan.

**2. Runs 8 specialist agents in parallel** — API probing, end-to-end browser tests, load testing, security scanning, database integrity checks, cross-browser validation, accessibility auditing, and regression replay. All simultaneously.

**3. Reports and files defects** — aggregates results into a human-readable QA report, files Jira tickets for every high/critical defect found, and posts a summary to Slack.

**4. Evaluates itself** — runs DeepEval and RAGAS quality checks on its own outputs, with a configurable quality gate. If the system's reasoning isn't trustworthy, it says so.

The entire pipeline runs in under 10 minutes for most PRs.

---

## The Architecture That Makes It Work

The core insight was treating a CI/CD pipeline not as a script — but as a graph.

LangGraph lets you define AI workflows as stateful directed graphs. Each node is a function. Edges route based on state. The Send API fans out to multiple agents simultaneously. Interrupt pauses execution for human review when risk crosses a threshold.

```
GitHub Webhook
      │
      ▼
  Phase 1: Analysis
  ┌─────────────────────────────┐
  │ fetch PR context            │
  │ retrieve knowledge    ──►  score risk ──► generate test plan
  └─────────────────────────────┘
                │
         HITL Gate (risk ≥ 0.85 → pause for human)
                │ approve
  Phase 2: Parallel Execution
  ┌─────────────────────────────────────────────┐
  │ api  playwright  perf  security             │
  │ data  browser   a11y   regression           │
  └──────────────────────┬──────────────────────┘
                         │
  Phase 3: Reporting
  generate report ──► file Jira ──► send Slack
                         │
  Evaluation: DeepEval + RAGAS ──► quality gate
```

The key design decision: **one shared state object flows through the entire pipeline.** Every agent reads from it and writes back to it. Reducers handle concurrent writes from parallel agents without race conditions. The state is checkpointed to SQLite (or Postgres in production), so a failed run can be resumed exactly where it left off.

---

## The 14 Agents

Each of the 14 agents extends a `BaseQAAgent` abstract class with a consistent contract:

- A `run()` method that wraps execution with a configurable timeout and automatic retry with exponential back-off
- A `call_mcp()` helper for communicating with external services
- A standard `AgentResult` dataclass that every agent returns

This means adding a new agent is just implementing one method: `execute(state, suite) -> AgentResult`.

The agents break down by phase:

**Phase 1 — Analysis (4 agents)**
The PR Context Fetcher talks to GitHub. The Knowledge Retriever does semantic search over historical defects. The Risk Assessor uses an LLM to score the change from 0–1. The Test Planner uses an LLM to generate a structured JSON test plan that drives everything downstream.

**Phase 2 — Execution (8 agents)**
These run in parallel via LangGraph's Send API. Each agent connects to a dedicated MCP server — Playwright for browser tests, k6 for load tests, Jira for defect history, Postgres for database integrity. The Security Agent layers three checks: regex patterns for secrets in the diff, GitHub's secret scanning alerts, and flagging changed dependency files.

**Phase 3 — Reporting (2 agents)**
The Report Generator uses an LLM to turn raw test results into a readable Markdown report with an APPROVE / BLOCK / NEEDS_REVIEW recommendation. The Defect Filer creates Jira tickets for actionable issues, with deduplication so re-runs don't create noise.

---

## The MCP Layer

Model Context Protocol is what makes the agents tool-agnostic.

Instead of each agent importing a Jira SDK, a Playwright library, and a k6 client directly, every external service is wrapped in a dedicated MCP server that speaks a standard JSON interface. The agents call `call_mcp("jira", "create_issue", {...})` — they don't know or care how the underlying service works.

The seven MCP servers are:

- **GitHub** — PR data, file diffs, secret scanning alerts
- **Playwright** — browser automation, accessibility audits, visual diffing
- **k6** — load test execution and threshold evaluation
- **Jira** — issue creation, JQL search, status transitions
- **Postgres** — read-only and read-write SQL execution
- **Slack** — report delivery and slash command handling
- **Knowledge Store** — semantic search over historical defects and runbooks

This architecture means swapping Jira for Linear, or k6 for Gatling, requires changing one MCP server — not rewriting agents.

---

## The Human-in-the-Loop Gate

Not every PR should run through full automation unreviewed.

When the risk score hits 0.85 or above — auth changes, schema migrations, security config — the pipeline calls `interrupt()`. Execution pauses. LangGraph serialises the entire graph state to the checkpoint database.

A Slack message goes out: *"PR #142 scored 0.91 risk. Review required before testing proceeds."*

The reviewer responds with `/qa-approve run-id=abc123` or `/qa-reject run-id=abc123 comment="security issue"`. A FastAPI endpoint calls `aupdate_state()` to resume the graph from exactly where it stopped.

This is the detail I'm most proud of. HITL isn't bolted on — it's a first-class primitive in the workflow. The graph literally cannot proceed until a human makes a decision.

---

## What I Learned Building This

**LangGraph changes how you think about workflows.** Once you model a pipeline as a graph, conditionals, parallelism, and error recovery all become structural rather than procedural. The orchestrator is pure routing — all the logic lives in nodes.

**The abstraction layer matters more than the agents.** The 14 agents are relatively straightforward. The hard work was designing `CIPipelineState` — the shared TypedDict that flows through the entire system. Get that wrong and every agent fights the state schema.

**Evaluation is not optional.** Running DeepEval and RAGAS on the pipeline's own outputs sounds like overkill until the first time an LLM hallucinates a risk score or generates a test plan that doesn't match the actual changes. The quality gate caught real issues during development.

**MCP is the right abstraction for agent tooling.** I was sceptical at first — it feels like extra indirection. But the benefit becomes obvious when you need to run tests in CI with mocked services and in production with real ones. The agents never change. Only the server URLs do.

---

## The Open Source Repository

The full system — all 14 agents, 7 MCP servers, LangGraph pipeline, FastAPI webhook, Docker Compose setup, and CI workflow — is available at:

**github.com/kavitaj11/k11techlab-agentic-ai-qa-system**

It includes a companion 11-module LangGraph course (Module 0 through Module 10) that teaches every concept used in the system by building it piece by piece:

**github.com/kavitaj11/k11techlab-agentic-ai-autonomous-qa-system**

Both are free and open source.

---

## What's Next

The system currently handles the "run tests and report" problem well. What it doesn't do yet:

- **Auto-remediation** — if an API test fails because an endpoint contract changed, can an agent propose the fix?
- **Learning from outcomes** — when a HITL reviewer approves a PR that later causes an incident, that signal should feed back into risk scoring
- **Multi-repo awareness** — microservice changes that break downstream consumers aren't visible at the PR level

These are the next problems I'm thinking about. If you're working on any of them, I'd love to talk.

---

*Kavita Jain · K11 TechLab · kavitaj11@gmail.com*

*Senior QA Engineer | Agentic AI | LangGraph | MCP | CI/CD Automation*
