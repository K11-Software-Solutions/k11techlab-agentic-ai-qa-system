# ─────────────────────────────────────────────────────────────────────────────
# K11tech Agentic QA System  |  Developer Makefile
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: help install lint test test-unit test-integration test-e2e \
        run-webhook run-all stop clean docker-build docker-up docker-down \
        check-syntax

PYTHON   ?= python
PIP      ?= pip
PYTEST   ?= pytest
UVICORN  ?= uvicorn

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  K11tech Agentic QA System — available targets"
	@echo ""
	@echo "  Setup"
	@echo "    install          Install Python dependencies"
	@echo "    install-dev      Install dev tools (ruff, bandit, mypy)"
	@echo ""
	@echo "  Code quality"
	@echo "    lint             Run ruff linter"
	@echo "    check-syntax     py_compile all source files"
	@echo "    security-scan    Run bandit security scanner"
	@echo ""
	@echo "  Tests"
	@echo "    test             Run all tests"
	@echo "    test-unit        Unit tests only"
	@echo "    test-integration Integration tests only"
	@echo "    test-e2e         E2E smoke tests only"
	@echo ""
	@echo "  Run locally"
	@echo "    run-webhook      Start FastAPI webhook on :9000"
	@echo ""
	@echo "  Docker"
	@echo "    docker-build     Build webhook image"
	@echo "    docker-up        Start all services (docker compose up -d)"
	@echo "    docker-down      Stop all services"
	@echo "    docker-logs      Tail all service logs"
	@echo ""
	@echo "  Misc"
	@echo "    clean            Remove __pycache__ and .pyc files"
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	$(PIP) install -r requirements.txt

install-dev: install
	$(PIP) install ruff bandit mypy pytest-cov

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	ruff check agents/ mcps/ pipeline/ api/ --select E,F,W,I

check-syntax:
	$(PYTHON) -m py_compile \
		agents/base.py agents/risk_assessor.py agents/knowledge_retriever.py \
		agents/pr_context_fetcher.py agents/test_planner.py agents/api_probe.py \
		agents/playwright_agent.py agents/perf_agent.py agents/security_agent.py \
		agents/data_agent.py agents/browser_agent.py agents/a11y_agent.py \
		agents/regression_agent.py agents/report_generator.py agents/defect_filer.py \
		mcps/base_client.py mcps/github_client.py mcps/playwright_client.py \
		mcps/k6_client.py mcps/jira_client.py mcps/postgres_client.py \
		mcps/slack_client.py mcps/knowledge_store_client.py \
		pipeline/state.py pipeline/phase1.py pipeline/phase2.py pipeline/phase3.py \
		pipeline/evaluation.py pipeline/hitl.py pipeline/orchestrator.py pipeline/runner.py \
		api/webhook.py
	@echo "All files pass syntax check."

security-scan:
	bandit -r agents/ mcps/ pipeline/ api/ -ll --exclude tests/

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	$(PYTEST) tests/ -v --tb=short --asyncio-mode=auto

test-unit:
	$(PYTEST) tests/unit/ -v --tb=short --asyncio-mode=auto

test-integration:
	$(PYTEST) tests/integration/ -v --tb=short --asyncio-mode=auto

test-e2e:
	$(PYTEST) tests/e2e/ -v --tb=short --asyncio-mode=auto

test-cov:
	$(PYTEST) tests/ --cov=agents --cov=mcps --cov=pipeline \
	          --cov-report=term-missing --asyncio-mode=auto

# ── Run locally ───────────────────────────────────────────────────────────────
run-webhook:
	$(UVICORN) api.webhook:app --host 0.0.0.0 --port 9000 --reload

# ── Docker ────────────────────────────────────────────────────────────────────
docker-build:
	docker build -t k11techlab-qa-webhook:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

docker-restart:
	docker compose down && docker compose up -d

# ── Misc ──────────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	find . -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.db" -delete
	@echo "Clean done."
