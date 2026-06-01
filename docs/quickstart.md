# Quick Start Guide

## Prerequisites

- Python 3.11+
- Docker (for MCP servers)
- OpenAI API key
- GitHub personal access token
- Jira API token (optional — skipped if not set)
- Slack bot token (optional)

## 1. Clone and Install

```bash
git clone https://github.com/kavitaj11/k11techlab-agentic-ai-qa-system.git
cd k11techlab-agentic-ai-qa-system
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Minimum required:

```env
OPENAI_API_KEY=sk-...
GITHUB_TOKEN=ghp_...
TARGET_BASE_URL=http://localhost:8000

# MCP server URLs (defaults shown — change if running on different ports)
GITHUB_MCP_URL=http://localhost:8001
PLAYWRIGHT_MCP_URL=http://localhost:8002
K6_MCP_URL=http://localhost:8003
JIRA_MCP_URL=http://localhost:8004
POSTGRES_MCP_URL=http://localhost:8005
SLACK_MCP_URL=http://localhost:8006
KNOWLEDGE_STORE_MCP_URL=http://localhost:8007
```

## 3. Start MCP Servers

Each MCP server lives in its own directory with a `Dockerfile`:

```bash
# Start all 7 MCP servers via Docker Compose (if compose file exists)
docker compose up -d

# Or start individually:
cd knowledge-store-mcp && uvicorn server:app --port 8007 &
# etc.
```

## 4. Run the Pipeline Manually

```python
import asyncio
from pipeline.runner import run_pipeline

result = asyncio.run(
    run_pipeline(
        pr_number=42,
        repo_name="myorg/myrepo",
        pr_diff="--- a/api.py\n+++ b/api.py\n...",
        run_id="test-run-001",
    )
)
print(result["verdict"])          # APPROVED / BLOCKED / NEEDS_REVIEW
print(result["total_defects"])
print(result["eval_passed"])
```

## 5. Run the Webhook Server

```bash
uvicorn api.webhook:app --host 0.0.0.0 --port 9000 --reload
```

Then configure your GitHub repository webhook:

- URL: `https://your-server/webhook/github`
- Content type: `application/json`
- Secret: value of `GITHUB_WEBHOOK_SECRET` env var
- Events: Pull requests

## 6. Run Tests

```bash
pytest tests/ -v
```

## 7. Approve/Reject via Slack

Install the Slack app with slash commands pointing to:
- `/qa-approve` → `POST https://your-server/api/slack/command`
- `/qa-reject`  → `POST https://your-server/api/slack/command`

Usage in Slack:
```
/qa-approve run-id=abc123 comment="Looks good"
/qa-reject  run-id=abc123 comment="Fix security issues first"
```

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for LLM agents |
| `GITHUB_TOKEN` | — | GitHub PAT for GitHub MCP |
| `GITHUB_WEBHOOK_SECRET` | — | HMAC secret for webhook |
| `TARGET_BASE_URL` | `http://localhost:8000` | System under test |
| `RISK_MODEL` | `gpt-4o-mini` | LLM for risk scoring |
| `PLANNER_MODEL` | `gpt-4o-mini` | LLM for test planning |
| `REPORT_MODEL` | `gpt-4o-mini` | LLM for report generation |
| `HITL_RISK_THRESHOLD` | `0.85` | Risk score that triggers HITL |
| `JIRA_PROJECT_KEY` | `QA` | Jira project for defect filing |
| `SLACK_QA_CHANNEL` | `#qa-reports` | Channel for QA report posts |
| `LANGCHAIN_TRACING_V2` | `false` | Enable LangSmith tracing |
| `LANGCHAIN_API_KEY` | — | LangSmith API key |
| `DB_URL` | `sqlite:///./qa.db` | Checkpointing database |
