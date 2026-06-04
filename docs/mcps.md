# MCP Server Reference

The system communicates with 7 MCP servers.  Each has a Python client wrapper in `mcps/`.

## Overview

| Server | Client Class | Default Port | Role |
|--------|-------------|-------------|------|
| GitHub | `GitHubMCPClient` | 8001 | PR data, secret scanning |
| Playwright | `PlaywrightMCPClient` | 8002 | E2E, a11y, cross-browser |
| k6 | `K6MCPClient` | 8003 | Load & performance testing |
| Jira | `JiraMCPClient` | 8004 | Defect filing, search |
| Postgres | `PostgresMCPClient` | 8005 | DB integrity checks |
| Slack | `SlackMCPClient` | 8006 | QA report delivery |
| Knowledge Store | `KnowledgeStoreMCPClient` | 8007 | RAG retrieval, regression suite |

## Instantiating Clients

```python
from mcps import build_mcp_clients

clients = build_mcp_clients()   # uses env vars for URLs

# Or with explicit URLs:
clients = build_mcp_clients(
    github_url="http://github-mcp:8001",
    playwright_url="http://playwright-mcp:8002",
)

# Pass to agent constructor:
agent = PlaywrightAgent(mcp_clients=clients)

# Or use call_mcp inside an agent:
raw = await self.call_mcp("playwright", "run_scenario", {...})
```

## MCP Wire Format

All clients POST to `{server_url}/tools/call`:

```json
{
  "name": "tool_name",
  "arguments": { ... }
}
```

Response:

```json
{
  "content": [{"type": "text", "text": "{...json...}"}],
  "isError": false
}
```

The base client unwraps the first content block and JSON-parses it automatically.

## Tool Reference

### GitHub MCP

| Tool | Arguments | Returns |
|------|-----------|---------|
| `get_pull_request` | `repo`, `pull_number` | PR metadata dict |
| `get_pull_request_diff` | `repo`, `pull_number` | `{diff: str}` |
| `list_pull_request_files` | `repo`, `pull_number` | `{files: [{filename, status, additions, deletions}]}` |
| `list_secret_scanning_alerts` | `repo`, `state` | `{alerts: [{secret_type, html_url}]}` |

### Playwright MCP

| Tool | Arguments | Returns |
|------|-----------|---------|
| `run_scenario` | `url`, `steps`, `timeout_ms` | `{status, error, screenshot_url}` |
| `run_accessibility_scan` | `url`, `tags`, `include_passes` | `{violations: [{id, impact, description, nodes}]}` |
| `run_cross_browser` | `browser`, `url`, `focus_areas` | `{status, error, screenshot_url}` |
| `compare_screenshots` | `screenshots`, `threshold` | `{differences: [{browser_a, browser_b, diff_ratio}]}` |

### k6 MCP

| Tool | Arguments | Returns |
|------|-----------|---------|
| `run_load_test` | `scenarios`, `thresholds`, `vus`, `duration` | `{checks_passed, checks_failed, threshold_violations, http_req_duration_p95, http_req_failed_rate}` |
| `get_test_results` | `test_id` | Full metrics dict |

### Jira MCP

| Tool | Arguments | Returns |
|------|-----------|---------|
| `create_issue` | `project_key`, `summary`, `description`, `issue_type`, `priority`, `labels` | `{key, id, url}` |
| `search_issues` | `jql`, `max_results` | `{issues: [{key, summary, status}]}` |
| `add_comment` | `issue_key`, `body` | `{id}` |
| `transition_issue` | `issue_key`, `transition_name` | `{status}` |

### Postgres MCP

| Tool | Arguments | Returns |
|------|-----------|---------|
| `execute_query` | `sql`, `read_only`, `params` | `{rows: [[...]], columns: [...]}` |
| `list_tables` | `schema` | `{tables: [str]}` |
| `describe_table` | `table_name`, `schema` | `{columns: [{name, type, nullable}]}` |
| `run_migration` | `sql` | `{status, rows_affected}` |

### Slack MCP

| Tool | Arguments | Returns |
|------|-----------|---------|
| `post_message` | `channel`, `text`, `blocks` | `{ts, channel}` |
| `list_channels` | — | `{channels: [{id, name}]}` |

### Knowledge Store MCP

| Tool | Arguments | Returns |
|------|-----------|---------|
| `search_documents` | `query`, `top_k`, `filters` | `{documents: [{id, content, score, metadata}]}` |
| `get_regression_suite` | `changed_files`, `max_cases`, `priority_filter` | `{cases: [{id, name, method, path, expected_status}]}` |
| `ingest_document` | `content`, `doc_type`, `metadata` | `{id, status}` |
| `get_runbook` | `component` | `{content, component, version}` |
