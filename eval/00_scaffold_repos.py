# Copyright 2026 Kavita Jadhav / K11 Software Solutions LLC
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
"""
eval/00_scaffold_repos.py
─────────────────────────
Creates 3 GitHub repos and generates a realistic PR history for the
K11tech Agentic AI QA System empirical evaluation.

Repos created:
  k11-eval-api       — FastAPI REST service (42 PRs)
  k11-eval-pipeline  — Data processing pipeline (38 PRs)
  k11-eval-webapp    — Flask web application (40 PRs)

Each repo gets a mix of:
  • CLEAN PRs  — routine changes with no follow-up fix
  • DEFECTIVE PRs — changes followed by a bug-fix commit (triggers auto-labeller)

Prerequisites:
  pip install httpx
  gh auth login          (GitHub CLI authenticated)
  git config user.email / user.name set

Usage:
    python eval/00_scaffold_repos.py \
        --org  your-github-username \
        --dry-run              # print plan without creating anything
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── PR definitions ────────────────────────────────────────────────────────────

@dataclass
class PRSpec:
    branch: str
    title: str
    body: str
    files: dict[str, str]          # filename → content
    defective: bool = False         # if True, a fix commit is added after merge
    fix_message: str = ""           # commit message for the fix


# ── Repo 1: FastAPI REST service ──────────────────────────────────────────────

API_PRS: list[PRSpec] = [
    # CLEAN
    PRSpec("feat/health-endpoint", "Add /health endpoint",
           "Adds a simple health check endpoint for load balancers.",
           {"api/health.py": textwrap.dedent("""\
               from fastapi import APIRouter
               router = APIRouter()
               @router.get('/health')
               def health(): return {'status': 'ok'}
           """)}),
    PRSpec("docs/update-readme", "Update README with API examples",
           "Adds curl examples for all endpoints.",
           {"README.md": "# API Service\n\n## Endpoints\n\n### GET /health\n```\ncurl http://localhost:8000/health\n```\n"}),
    PRSpec("refactor/split-routes", "Split routes into separate modules",
           "Moves user and product routes to dedicated files.",
           {"api/routes/users.py": "# user routes\n", "api/routes/products.py": "# product routes\n"}),
    PRSpec("feat/pagination", "Add pagination to list endpoints",
           "Implements limit/offset pagination.",
           {"api/pagination.py": textwrap.dedent("""\
               def paginate(query, limit=20, offset=0):
                   return query.offset(offset).limit(limit)
           """)}),
    PRSpec("chore/update-deps", "Update dependencies to latest versions",
           "Bumps fastapi, pydantic, httpx.",
           {"requirements.txt": "fastapi==0.115.0\npydantic==2.9.0\nhttpx==0.27.0\n"}),
    PRSpec("feat/rate-limiting", "Add rate limiting middleware",
           "Limits requests to 100/min per IP.",
           {"api/middleware/rate_limit.py": textwrap.dedent("""\
               from collections import defaultdict
               import time
               RATE_LIMIT = 100
               WINDOW = 60
               counters = defaultdict(list)
               def check_rate_limit(ip: str) -> bool:
                   now = time.time()
                   counters[ip] = [t for t in counters[ip] if now - t < WINDOW]
                   if len(counters[ip]) >= RATE_LIMIT:
                       return False
                   counters[ip].append(now)
                   return True
           """)}),
    PRSpec("test/add-health-tests", "Add tests for health endpoint",
           "Unit tests for the health check.",
           {"tests/test_health.py": textwrap.dedent("""\
               from fastapi.testclient import TestClient
               from api.main import app
               client = TestClient(app)
               def test_health(): assert client.get('/health').status_code == 200
           """)}),
    PRSpec("feat/cors-config", "Configure CORS for frontend integration",
           "Allows requests from trusted origins.",
           {"api/cors.py": textwrap.dedent("""\
               ALLOWED_ORIGINS = ['https://app.example.com']
           """)}),
    PRSpec("chore/add-gitignore", "Add .gitignore for Python project",
           "Standard Python .gitignore.",
           {".gitignore": "__pycache__/\n*.pyc\n.env\n.venv/\ndist/\n"}),
    PRSpec("feat/structured-logging", "Add structured JSON logging",
           "Replaces print statements with structured logging.",
           {"api/logging_config.py": textwrap.dedent("""\
               import logging, json
               class JsonFormatter(logging.Formatter):
                   def format(self, record):
                       return json.dumps({'level': record.levelname, 'msg': record.getMessage()})
           """)}),
    # DEFECTIVE
    PRSpec("feat/auth-middleware", "Add JWT authentication middleware",
           "Validates Bearer tokens on all protected routes.",
           {"api/middleware/auth.py": textwrap.dedent("""\
               import jwt
               SECRET = 'hardcoded-secret'   # BUG: should be from env
               def verify_token(token: str) -> dict:
                   return jwt.decode(token, SECRET, algorithms=['HS256'])
           """)},
           defective=True,
           fix_message="fix: auth middleware used hardcoded secret key"),
    PRSpec("feat/user-registration", "Add user registration endpoint",
           "POST /users endpoint with email validation.",
           {"api/routes/register.py": textwrap.dedent("""\
               def register(email: str, password: str):
                   # BUG: password stored in plaintext
                   db.insert({'email': email, 'password': password})
           """)},
           defective=True,
           fix_message="fix: user registration stored password in plaintext"),
    PRSpec("feat/file-upload", "Add file upload endpoint",
           "POST /upload for document processing.",
           {"api/routes/upload.py": textwrap.dedent("""\
               async def upload(file):
                   # BUG: no file size limit
                   content = await file.read()
                   return {'size': len(content)}
           """)},
           defective=True,
           fix_message="fix: file upload had no size limit causing OOM"),
    PRSpec("refactor/db-connection", "Refactor database connection pooling",
           "Moves to async connection pool.",
           {"api/db.py": textwrap.dedent("""\
               # BUG: pool not closed on shutdown
               pool = None
               async def get_pool():
                   global pool
                   if pool is None:
                       pool = await create_pool()
                   return pool
           """)},
           defective=True,
           fix_message="fix: database connection pool leaked on shutdown"),
    PRSpec("feat/search-endpoint", "Add full-text search endpoint",
           "GET /search with query parameter.",
           {"api/routes/search.py": textwrap.dedent("""\
               def search(q: str):
                   # BUG: SQL injection vulnerability
                   return db.execute(f'SELECT * FROM items WHERE name LIKE \"%{q}%\"')
           """)},
           defective=True,
           fix_message="fix: search endpoint vulnerable to SQL injection"),
    # More CLEAN
    PRSpec("feat/openapi-tags", "Add OpenAPI tags to all endpoints",
           "Groups endpoints by domain in Swagger UI.",
           {"api/tags.py": "TAGS = ['users', 'products', 'search', 'admin']\n"}),
    PRSpec("chore/docker-healthcheck", "Add Docker HEALTHCHECK instruction",
           "Makes container health visible to orchestrators.",
           {"Dockerfile": "FROM python:3.11-slim\nHEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1\n"}),
    PRSpec("test/add-auth-tests", "Add authentication tests",
           "Tests for token validation and rejection.",
           {"tests/test_auth.py": textwrap.dedent("""\
               def test_valid_token(): assert verify('valid') == {'sub': 'user1'}
               def test_invalid_token(): assert verify('bad') is None
           """)}),
    PRSpec("feat/response-compression", "Enable gzip response compression",
           "Reduces payload size for large responses.",
           {"api/compression.py": "from fastapi.middleware.gzip import GZipMiddleware\n"}),
    PRSpec("docs/api-changelog", "Add CHANGELOG.md",
           "Documents API version history.",
           {"CHANGELOG.md": "# Changelog\n\n## v2.0.0\n- Added auth middleware\n- Added search endpoint\n"}),
    # DEFECTIVE
    PRSpec("feat/admin-panel", "Add admin panel route",
           "Exposes admin operations behind /admin.",
           {"api/routes/admin.py": textwrap.dedent("""\
               # BUG: no role check, any authenticated user can access
               @router.delete('/admin/users/{user_id}')
               def delete_user(user_id: int):
                   db.delete(user_id)
           """)},
           defective=True,
           fix_message="fix: admin routes lacked role-based access control"),
    PRSpec("feat/cache-headers", "Add cache control headers",
           "Sets Cache-Control on static responses.",
           {"api/middleware/cache.py": textwrap.dedent("""\
               # BUG: sets no-cache on all routes including public static
               def cache_middleware(response):
                   response.headers['Cache-Control'] = 'no-store'
                   return response
           """)},
           defective=True,
           fix_message="fix: cache middleware incorrectly disabled caching on static assets"),
    # More CLEAN
    PRSpec("refactor/error-handlers", "Centralise error handlers",
           "Moves scattered try/except into global handlers.",
           {"api/errors.py": textwrap.dedent("""\
               from fastapi import Request
               from fastapi.responses import JSONResponse
               async def http_exception_handler(request: Request, exc):
                   return JSONResponse({'error': str(exc)}, status_code=exc.status_code)
           """)}),
    PRSpec("feat/metrics-endpoint", "Add Prometheus metrics endpoint",
           "Exposes /metrics for Prometheus scraping.",
           {"api/metrics.py": "from prometheus_fastapi_instrumentator import Instrumentator\n"}),
    PRSpec("chore/pre-commit-hooks", "Add pre-commit configuration",
           "Runs ruff and mypy on commit.",
           {".pre-commit-config.yaml": "repos:\n- repo: https://github.com/astral-sh/ruff-pre-commit\n  rev: v0.6.0\n  hooks:\n  - id: ruff\n"}),
    PRSpec("test/add-pagination-tests", "Add pagination tests",
           "Tests limit/offset behaviour.",
           {"tests/test_pagination.py": textwrap.dedent("""\
               def test_default_limit(): assert len(paginate(items)) == 20
               def test_custom_offset(): assert paginate(items, offset=5)[0] == items[5]
           """)}),
    PRSpec("feat/request-id-middleware", "Add X-Request-ID middleware",
           "Injects unique request IDs for tracing.",
           {"api/middleware/request_id.py": textwrap.dedent("""\
               import uuid
               def add_request_id(request, call_next):
                   request.state.id = str(uuid.uuid4())
                   response = call_next(request)
                   response.headers['X-Request-ID'] = request.state.id
                   return response
           """)}),
    PRSpec("chore/add-makefile", "Add Makefile for common commands",
           "Simplifies local dev with make run, make test.",
           {"Makefile": "run:\n\tuvicorn api.main:app --reload\ntest:\n\tpytest tests/\n"}),
    # DEFECTIVE
    PRSpec("feat/export-endpoint", "Add CSV export endpoint",
           "GET /export downloads all records as CSV.",
           {"api/routes/export.py": textwrap.dedent("""\
               # BUG: no authentication required on export — exposes all data
               @router.get('/export')
               def export_all():
                   return db.get_all()
           """)},
           defective=True,
           fix_message="fix: export endpoint was unauthenticated, exposed all records"),
    PRSpec("refactor/settings-module", "Extract settings to pydantic BaseSettings",
           "Moves env var handling to settings.py.",
           {"api/settings.py": textwrap.dedent("""\
               from pydantic_settings import BaseSettings
               class Settings(BaseSettings):
                   # BUG: debug=True baked in, not read from env
                   debug: bool = True
                   db_url: str = 'sqlite:///./test.db'
           """)},
           defective=True,
           fix_message="fix: settings had debug=True hardcoded instead of reading from env"),
    # More CLEAN
    PRSpec("feat/webhook-receiver", "Add webhook receiver endpoint",
           "POST /webhooks/github for CI integration.",
           {"api/routes/webhooks.py": textwrap.dedent("""\
               import hmac, hashlib
               def verify_signature(payload: bytes, sig: str, secret: str) -> bool:
                   expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
                   return hmac.compare_digest(f'sha256={expected}', sig)
           """)}),
    PRSpec("test/add-search-tests", "Add search endpoint tests",
           "Tests search with various inputs.",
           {"tests/test_search.py": textwrap.dedent("""\
               def test_search_found(): assert len(search('widget')) > 0
               def test_search_empty(): assert search('zzz_nonexistent') == []
               def test_search_special_chars(): assert search("o'malley") is not None
           """)}),
    PRSpec("chore/ci-workflow", "Add GitHub Actions CI workflow",
           "Runs lint and tests on every push.",
           {".github/workflows/ci.yml": textwrap.dedent("""\
               name: CI
               on: [push, pull_request]
               jobs:
                 test:
                   runs-on: ubuntu-latest
                   steps:
                   - uses: actions/checkout@v4
                   - run: pip install -r requirements.txt
                   - run: pytest tests/
           """)}),
    PRSpec("feat/background-tasks", "Add background task queue",
           "Uses FastAPI BackgroundTasks for async jobs.",
           {"api/tasks.py": textwrap.dedent("""\
               from fastapi import BackgroundTasks
               def send_email_background(bg: BackgroundTasks, to: str, body: str):
                   bg.add_task(send_email, to, body)
           """)}),
    PRSpec("refactor/dependency-injection", "Refactor to use FastAPI Depends",
           "Replaces global db with injected dependency.",
           {"api/dependencies.py": textwrap.dedent("""\
               from fastapi import Depends
               from api.db import get_session
               def get_db(): return next(get_session())
           """)}),
    # DEFECTIVE
    PRSpec("feat/password-reset", "Add password reset flow",
           "POST /auth/reset sends reset email.",
           {"api/routes/auth.py": textwrap.dedent("""\
               import random
               def generate_reset_token():
                   # BUG: random is not cryptographically secure
                   return str(random.randint(100000, 999999))
           """)},
           defective=True,
           fix_message="fix: password reset token used non-cryptographic random"),
    PRSpec("feat/api-versioning", "Add API versioning prefix /v1/",
           "All routes now prefixed with /v1/.",
           {"api/versioning.py": textwrap.dedent("""\
               # BUG: old routes not redirected, breaks existing clients
               V1_PREFIX = '/v1'
           """)},
           defective=True,
           fix_message="fix: api versioning broke existing clients with no redirect"),
    # Final CLEAN
    PRSpec("docs/contributing-guide", "Add CONTRIBUTING.md",
           "Documents how to contribute to the project.",
           {"CONTRIBUTING.md": "# Contributing\n\n1. Fork the repo\n2. Create a branch\n3. Open a PR\n"}),
    PRSpec("feat/structured-errors", "Standardise error response schema",
           "All errors return {code, message, detail}.",
           {"api/schemas/error.py": textwrap.dedent("""\
               from pydantic import BaseModel
               class ErrorResponse(BaseModel):
                   code: str
                   message: str
                   detail: str | None = None
           """)}),
    PRSpec("chore/update-python-312", "Upgrade to Python 3.12",
           "Updates base image and syntax.",
           {"Dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -r requirements.txt\n"}),
    PRSpec("test/add-integration-tests", "Add integration test suite",
           "Tests full request/response cycle.",
           {"tests/integration/test_api.py": textwrap.dedent("""\
               def test_full_flow(client):
                   r = client.post('/users', json={'email': 'a@b.com', 'password': 'pass'})
                   assert r.status_code == 201
           """)}),
]

# ── Repo 2: Data pipeline (shorter — 38 PRs) ─────────────────────────────────

PIPELINE_PRS: list[PRSpec] = [
    PRSpec("feat/csv-reader", "Add CSV ingestion module", "Reads CSVs into DataFrames.",
           {"pipeline/readers/csv_reader.py": "import pandas as pd\ndef read_csv(path): return pd.read_csv(path)\n"}),
    PRSpec("feat/json-reader", "Add JSON ingestion module", "Reads JSON Lines files.",
           {"pipeline/readers/json_reader.py": "import pandas as pd\ndef read_json(path): return pd.read_json(path, lines=True)\n"}),
    PRSpec("feat/schema-validation", "Add schema validation step", "Validates column types.",
           {"pipeline/validate.py": "def validate(df, schema):\n    for col, dtype in schema.items():\n        assert df[col].dtype == dtype\n"}),
    PRSpec("feat/deduplication", "Add deduplication step", "Removes duplicate rows.",
           {"pipeline/dedup.py": "def dedup(df, key): return df.drop_duplicates(subset=[key])\n"}),
    PRSpec("chore/add-logging", "Add pipeline logging", "Logs row counts at each step.",
           {"pipeline/logging.py": "import logging\nlog = logging.getLogger('pipeline')\n"}),
    PRSpec("feat/parquet-writer", "Add Parquet output writer", "Writes processed data to Parquet.",
           {"pipeline/writers/parquet_writer.py": "def write_parquet(df, path): df.to_parquet(path, index=False)\n"}),
    PRSpec("test/add-reader-tests", "Add tests for CSV and JSON readers", "Unit tests.",
           {"tests/test_readers.py": "def test_csv(): assert len(read_csv('tests/fixtures/sample.csv')) > 0\n"}),
    # DEFECTIVE
    PRSpec("feat/db-writer", "Add database writer step", "Writes processed rows to Postgres.",
           {"pipeline/writers/db_writer.py": textwrap.dedent("""\
               # BUG: no transaction — partial writes on failure
               def write_to_db(df, conn):
                   for _, row in df.iterrows():
                       conn.execute('INSERT INTO records VALUES (?)', row.tolist())
           """)},
           defective=True,
           fix_message="fix: db writer had no transaction, caused partial writes on failure"),
    PRSpec("feat/date-normaliser", "Add date normalisation step", "Converts dates to ISO format.",
           {"pipeline/transforms/dates.py": textwrap.dedent("""\
               # BUG: assumes US date format MM/DD/YYYY, breaks on UK dates
               def normalise_date(s): return pd.to_datetime(s, format='%m/%d/%Y')
           """)},
           defective=True,
           fix_message="fix: date normaliser assumed US format, broke on non-US locales"),
    PRSpec("feat/null-handler", "Add null value handler", "Fills or drops nulls per config.",
           {"pipeline/transforms/nulls.py": "def handle_nulls(df, strategy='drop'): return df.dropna() if strategy=='drop' else df.fillna(0)\n"}),
    PRSpec("feat/column-renamer", "Add column rename transform", "Maps old names to new.",
           {"pipeline/transforms/rename.py": "def rename_cols(df, mapping): return df.rename(columns=mapping)\n"}),
    PRSpec("chore/add-requirements", "Add requirements.txt", "Pins all dependencies.",
           {"requirements.txt": "pandas==2.2.0\npyarrow==16.0.0\npsycopg2-binary==2.9.9\n"}),
    PRSpec("feat/s3-reader", "Add S3 ingestion module", "Reads files directly from S3.",
           {"pipeline/readers/s3_reader.py": "import boto3\ndef read_s3(bucket, key): return boto3.client('s3').get_object(Bucket=bucket, Key=key)['Body']\n"}),
    # DEFECTIVE
    PRSpec("feat/email-notifier", "Add email notification on pipeline failure", "Sends alert email.",
           {"pipeline/notify.py": textwrap.dedent("""\
               import smtplib
               # BUG: SMTP credentials in source code
               SMTP_USER = 'pipeline@example.com'
               SMTP_PASS = 'hunter2'
               def send_alert(msg): pass
           """)},
           defective=True,
           fix_message="fix: SMTP credentials were hardcoded in notify.py"),
    PRSpec("feat/retry-logic", "Add retry logic for transient failures", "Retries failed steps.",
           {"pipeline/retry.py": "import time\ndef with_retry(fn, retries=3):\n    for i in range(retries):\n        try: return fn()\n        except Exception:\n            if i==retries-1: raise\n            time.sleep(2**i)\n"}),
    PRSpec("test/add-transform-tests", "Add tests for transforms", "Tests rename and null handling.",
           {"tests/test_transforms.py": "def test_rename(): assert 'new_col' in rename_cols(df, {'old_col': 'new_col'}).columns\n"}),
    PRSpec("feat/data-profiler", "Add data profiling step", "Computes stats on each column.",
           {"pipeline/profile.py": "def profile(df): return df.describe(include='all')\n"}),
    PRSpec("chore/add-ci", "Add CI workflow", "Runs tests on push.",
           {".github/workflows/ci.yml": "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n    - uses: actions/checkout@v4\n    - run: pip install -r requirements.txt && pytest\n"}),
    # DEFECTIVE
    PRSpec("feat/chunked-reader", "Add chunked reading for large files", "Reads files in chunks.",
           {"pipeline/readers/chunked.py": textwrap.dedent("""\
               # BUG: chunk size hardcoded to 1000, not configurable
               # causes OOM on machines with low RAM and large rows
               CHUNK_SIZE = 1000
               def read_chunked(path):
                   return pd.read_csv(path, chunksize=CHUNK_SIZE)
           """)},
           defective=True,
           fix_message="fix: chunked reader OOM on large rows due to hardcoded chunk size"),
    PRSpec("feat/type-coercer", "Add type coercion step", "Casts columns to target types.",
           {"pipeline/transforms/coerce.py": "def coerce(df, types):\n    for col, t in types.items(): df[col] = df[col].astype(t)\n    return df\n"}),
    PRSpec("feat/pipeline-config", "Add YAML pipeline config loader", "Loads pipeline from YAML.",
           {"pipeline/config.py": "import yaml\ndef load_config(path):\n    with open(path) as f: return yaml.safe_load(f)\n"}),
    PRSpec("refactor/extract-base-reader", "Extract BaseReader abstract class", "Unifies reader interface.",
           {"pipeline/readers/base.py": "from abc import ABC, abstractmethod\nclass BaseReader(ABC):\n    @abstractmethod\n    def read(self, path): pass\n"}),
    PRSpec("feat/metrics-collector", "Add pipeline metrics collector", "Tracks row counts and durations.",
           {"pipeline/metrics.py": "metrics = {}\ndef record(name, value): metrics[name] = value\n"}),
    # DEFECTIVE
    PRSpec("feat/archive-step", "Add archive step to move processed files", "Moves files to archive.",
           {"pipeline/archive.py": textwrap.dedent("""\
               import shutil, os
               # BUG: deletes source before confirming successful archive
               def archive(src, dst):
                   os.remove(src)
                   shutil.copy(src, dst)  # src already deleted!
           """)},
           defective=True,
           fix_message="fix: archive step deleted source file before confirming copy"),
    PRSpec("feat/dry-run-mode", "Add dry-run mode", "Runs pipeline without writing output.",
           {"pipeline/runner.py": "DRY_RUN = False\ndef run(config, dry_run=False):\n    global DRY_RUN; DRY_RUN = dry_run\n"}),
    PRSpec("test/add-writer-tests", "Add tests for Parquet writer", "Tests output file format.",
           {"tests/test_writers.py": "def test_parquet(tmp_path):\n    write_parquet(df, tmp_path/'out.parquet')\n    assert (tmp_path/'out.parquet').exists()\n"}),
    PRSpec("docs/pipeline-diagram", "Add pipeline architecture diagram", "ASCII art in README.",
           {"README.md": "# Data Pipeline\n\nIngest → Validate → Transform → Deduplicate → Write\n"}),
    # DEFECTIVE
    PRSpec("feat/alerting-thresholds", "Add alerting on data quality thresholds", "Alerts if null rate > threshold.",
           {"pipeline/alerts.py": textwrap.dedent("""\
               # BUG: threshold comparison is inverted — alerts when data is GOOD
               def check_null_rate(df, threshold=0.05):
                   rate = df.isnull().mean().max()
                   if rate < threshold:    # BUG: should be >
                       send_alert(f'High null rate: {rate}')
           """)},
           defective=True,
           fix_message="fix: alerting threshold comparison was inverted"),
    PRSpec("chore/add-makefile", "Add Makefile", "Simplifies common commands.",
           {"Makefile": "run:\n\tpython -m pipeline.runner\ntest:\n\tpytest tests/\n"}),
    PRSpec("feat/incremental-load", "Add incremental load support", "Only processes new records.",
           {"pipeline/incremental.py": "def get_new_records(df, last_id): return df[df['id'] > last_id]\n"}),
    PRSpec("refactor/split-config", "Split monolithic config into sections", "Separates source/sink/transform config.",
           {"pipeline/config_schema.py": "from pydantic import BaseModel\nclass SourceConfig(BaseModel): path: str\nclass SinkConfig(BaseModel): path: str\n"}),
    PRSpec("test/add-integration-tests", "Add end-to-end pipeline test", "Tests full pipeline run.",
           {"tests/test_pipeline.py": "def test_full_pipeline(tmp_path):\n    run({'source': 'tests/fixtures/sample.csv', 'sink': str(tmp_path/'out.parquet')})\n    assert (tmp_path/'out.parquet').exists()\n"}),
    PRSpec("feat/compression-writer", "Add gzip compression to CSV writer", "Compresses output CSV.",
           {"pipeline/writers/csv_writer.py": "def write_csv(df, path, compress=True): df.to_csv(path, compression='gzip' if compress else None, index=False)\n"}),
]

# ── Repo 3: Flask web app (40 PRs) ────────────────────────────────────────────

WEBAPP_PRS: list[PRSpec] = [
    PRSpec("feat/base-template", "Add base HTML template", "Jinja2 base layout.",
           {"templates/base.html": "<!DOCTYPE html><html><head><title>{% block title %}App{% endblock %}</title></head><body>{% block content %}{% endblock %}</body></html>\n"}),
    PRSpec("feat/home-page", "Add home page route", "GET / renders index.html.",
           {"app/routes/home.py": "from flask import Blueprint, render_template\nbp = Blueprint('home', __name__)\n@bp.route('/')\ndef index(): return render_template('index.html')\n"}),
    PRSpec("feat/user-model", "Add User database model", "SQLAlchemy User model.",
           {"app/models/user.py": "from app import db\nclass User(db.Model):\n    id = db.Column(db.Integer, primary_key=True)\n    email = db.Column(db.String(120), unique=True)\n"}),
    PRSpec("chore/add-flask-config", "Add Flask configuration module", "Dev/prod config classes.",
           {"app/config.py": "class Config:\n    DEBUG = False\nclass DevConfig(Config):\n    DEBUG = True\n    SQLALCHEMY_DATABASE_URI = 'sqlite:///dev.db'\n"}),
    PRSpec("feat/login-page", "Add login page", "GET/POST /login with form.",
           {"templates/login.html": "<form method='post'><input name='email'><input name='password' type='password'><button>Login</button></form>\n"}),
    # DEFECTIVE
    PRSpec("feat/session-management", "Add session management", "Sets user session on login.",
           {"app/auth.py": textwrap.dedent("""\
               from flask import session
               # BUG: session secret key hardcoded
               SECRET_KEY = 'dev-secret-123'
               def login_user(user_id): session['user_id'] = user_id
           """)},
           defective=True,
           fix_message="fix: session secret key was hardcoded in auth.py"),
    PRSpec("feat/dashboard", "Add user dashboard", "GET /dashboard for logged-in users.",
           {"app/routes/dashboard.py": "from flask import Blueprint\nbp = Blueprint('dashboard', __name__)\n@bp.route('/dashboard')\ndef dashboard(): return 'Dashboard'\n"}),
    PRSpec("feat/static-assets", "Add static asset pipeline", "CSS and JS served from /static.",
           {"static/css/main.css": "body { font-family: sans-serif; margin: 0; padding: 20px; }\n"}),
    PRSpec("chore/add-requirements", "Add requirements.txt", "Pins Flask dependencies.",
           {"requirements.txt": "Flask==3.0.0\nFlask-SQLAlchemy==3.1.1\nFlask-Login==0.6.3\n"}),
    PRSpec("test/add-home-tests", "Add tests for home page", "Tests 200 response.",
           {"tests/test_home.py": "def test_home(client): assert client.get('/').status_code == 200\n"}),
    # DEFECTIVE
    PRSpec("feat/contact-form", "Add contact form", "POST /contact sends email.",
           {"app/routes/contact.py": textwrap.dedent("""\
               # BUG: no CSRF protection on form submission
               @bp.route('/contact', methods=['POST'])
               def contact():
                   send_email(request.form['email'], request.form['message'])
           """)},
           defective=True,
           fix_message="fix: contact form had no CSRF protection"),
    PRSpec("feat/profile-page", "Add user profile page", "GET /profile shows user info.",
           {"app/routes/profile.py": "from flask import Blueprint\nbp = Blueprint('profile', __name__)\n@bp.route('/profile')\ndef profile(): return 'Profile'\n"}),
    PRSpec("refactor/blueprints", "Refactor to use Flask blueprints", "Splits routes into blueprints.",
           {"app/__init__.py": "from flask import Flask\ndef create_app():\n    app = Flask(__name__)\n    from app.routes.home import bp; app.register_blueprint(bp)\n    return app\n"}),
    PRSpec("feat/404-handler", "Add custom 404 error page", "Returns branded 404.",
           {"app/errors.py": "from flask import render_template\ndef not_found(e): return render_template('404.html'), 404\n"}),
    PRSpec("chore/add-ci", "Add CI workflow", "Tests on push.",
           {".github/workflows/ci.yml": "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n    - uses: actions/checkout@v4\n    - run: pip install -r requirements.txt && pytest\n"}),
    # DEFECTIVE
    PRSpec("feat/file-manager", "Add file manager page", "Browse uploaded files.",
           {"app/routes/files.py": textwrap.dedent("""\
               import os
               # BUG: path traversal vulnerability
               @bp.route('/files/<path:filename>')
               def get_file(filename):
                   return open(os.path.join('/uploads', filename)).read()
           """)},
           defective=True,
           fix_message="fix: file manager had path traversal vulnerability"),
    PRSpec("feat/pagination-widget", "Add pagination widget template", "Reusable Jinja2 macro.",
           {"templates/macros/pagination.html": "{% macro paginate(page, total) %}<div>Page {{page}} of {{total}}</div>{% endmacro %}\n"}),
    PRSpec("feat/search-page", "Add search results page", "GET /search?q=...",
           {"app/routes/search.py": "from flask import Blueprint, request, render_template\nbp = Blueprint('search', __name__)\n@bp.route('/search')\ndef search(): return render_template('search.html', q=request.args.get('q'))\n"}),
    PRSpec("test/add-auth-tests", "Add authentication tests", "Tests login/logout flow.",
           {"tests/test_auth.py": "def test_login(client):\n    r = client.post('/login', data={'email': 'a@b.com', 'password': 'pass'})\n    assert r.status_code in (200, 302)\n"}),
    PRSpec("feat/dark-mode", "Add dark mode toggle", "CSS custom properties for theme.",
           {"static/css/dark.css": ":root { --bg: #1a1a1a; --fg: #f0f0f0; }\n"}),
    # DEFECTIVE
    PRSpec("feat/admin-users", "Add admin user management page", "Lists all users.",
           {"app/routes/admin.py": textwrap.dedent("""\
               # BUG: no admin role check — any logged-in user can access
               @bp.route('/admin/users')
               @login_required
               def admin_users():
                   return User.query.all()
           """)},
           defective=True,
           fix_message="fix: admin users page accessible to non-admin users"),
    PRSpec("feat/notifications", "Add in-app notifications", "Shows unread count in nav.",
           {"app/models/notification.py": "from app import db\nclass Notification(db.Model):\n    id = db.Column(db.Integer, primary_key=True)\n    user_id = db.Column(db.Integer)\n    message = db.Column(db.String(255))\n    read = db.Column(db.Boolean, default=False)\n"}),
    PRSpec("refactor/move-to-factory", "Use application factory pattern", "Moves app creation to factory.",
           {"run.py": "from app import create_app\napp = create_app()\nif __name__ == '__main__': app.run()\n"}),
    PRSpec("feat/api-endpoints", "Add JSON API endpoints", "Returns JSON for AJAX requests.",
           {"app/routes/api.py": "from flask import Blueprint, jsonify\nbp = Blueprint('api', __name__, url_prefix='/api')\n@bp.route('/status')\ndef status(): return jsonify({'ok': True})\n"}),
    PRSpec("chore/add-pre-commit", "Add pre-commit hooks", "Runs ruff on commit.",
           {".pre-commit-config.yaml": "repos:\n- repo: https://github.com/astral-sh/ruff-pre-commit\n  rev: v0.6.0\n  hooks:\n  - id: ruff\n"}),
    # DEFECTIVE
    PRSpec("feat/export-users", "Add user data export", "Downloads user list as CSV.",
           {"app/routes/export.py": textwrap.dedent("""\
               # BUG: exports all users including password hashes
               @bp.route('/export/users')
               def export_users():
                   users = User.query.all()
                   return csv_response([(u.email, u.password_hash) for u in users])
           """)},
           defective=True,
           fix_message="fix: user export included password hashes in CSV output"),
    PRSpec("feat/rate-limit", "Add rate limiting to login", "Limits to 5 attempts/min.",
           {"app/limiter.py": "from flask_limiter import Limiter\nfrom flask_limiter.util import get_remote_address\nlimiter = Limiter(key_func=get_remote_address, default_limits=['100/minute'])\n"}),
    PRSpec("test/add-profile-tests", "Add profile page tests", "Tests profile renders for auth user.",
           {"tests/test_profile.py": "def test_profile_requires_login(client):\n    r = client.get('/profile')\n    assert r.status_code == 302  # redirect to login\n"}),
    PRSpec("feat/sitemap", "Add sitemap.xml", "For search engine indexing.",
           {"app/routes/sitemap.py": "from flask import Blueprint, make_response\nbp = Blueprint('sitemap', __name__)\n@bp.route('/sitemap.xml')\ndef sitemap(): return make_response('<?xml version=\"1.0\"?><urlset></urlset>', 200)\n"}),
    PRSpec("docs/deployment-guide", "Add deployment guide", "Documents Heroku/Railway deploy.",
           {"docs/deploy.md": "# Deployment\n\n## Railway\n\n```bash\nrailway up\n```\n"}),
    # DEFECTIVE
    PRSpec("feat/password-change", "Add password change form", "POST /account/password.",
           {"app/routes/account.py": textwrap.dedent("""\
               # BUG: does not verify current password before allowing change
               @bp.route('/account/password', methods=['POST'])
               @login_required
               def change_password():
                   new_pw = request.form['new_password']
                   current_user.set_password(new_pw)
                   db.session.commit()
           """)},
           defective=True,
           fix_message="fix: password change did not verify current password first"),
    PRSpec("refactor/error-pages", "Add styled error pages", "Custom 403/404/500 templates.",
           {"templates/errors/404.html": "<h1>404</h1><p>Page not found.</p>\n",
            "templates/errors/500.html": "<h1>500</h1><p>Server error.</p>\n"}),
    PRSpec("feat/remember-me", "Add remember-me cookie", "Persistent login across sessions.",
           {"app/auth.py": "from flask_login import login_user\ndef login(user, remember=False): login_user(user, remember=remember)\n"}),
    PRSpec("chore/update-deps", "Update all dependencies", "Bumps to latest stable versions.",
           {"requirements.txt": "Flask==3.1.0\nFlask-SQLAlchemy==3.1.1\nFlask-Login==0.6.3\nFlask-Limiter==3.8.0\n"}),
    PRSpec("test/add-api-tests", "Add API endpoint tests", "Tests JSON responses.",
           {"tests/test_api.py": "def test_status(client):\n    r = client.get('/api/status')\n    assert r.json == {'ok': True}\n"}),
    PRSpec("feat/two-factor-auth", "Add TOTP two-factor authentication", "Uses pyotp.",
           {"app/totp.py": "import pyotp\ndef generate_secret(): return pyotp.random_base32()\ndef verify_totp(secret, token): return pyotp.TOTP(secret).verify(token)\n"}),
    PRSpec("docs/readme-update", "Update README with feature list", "Documents all features.",
           {"README.md": "# Web App\n\n## Features\n- User auth\n- Dashboard\n- Profile\n- Search\n- Admin panel\n- 2FA\n"}),
]

REPOS = [
    ("k11-eval-api",      "FastAPI REST service for K11tech AQA evaluation",      API_PRS),
    ("k11-eval-pipeline", "Data processing pipeline for K11tech AQA evaluation",   PIPELINE_PRS),
    ("k11-eval-webapp",   "Flask web application for K11tech AQA evaluation",      WEBAPP_PRS),
]


# ── Git helpers ───────────────────────────────────────────────────────────────

def run(cmd: list[str], cwd=None, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check,
                          capture_output=True, text=True)


def repo_exists(org: str, name: str) -> bool:
       result = subprocess.run(
              ["gh", "repo", "view", f"{org}/{name}"],
              check=False,
              capture_output=True,
              text=True,
       )
       return result.returncode == 0


def get_existing_pr_count(org: str, name: str) -> int:
       result = subprocess.run(
              [
                     "gh", "pr", "list",
                     "--repo", f"{org}/{name}",
                     "--state", "all",
                     "--limit", "500",
                     "--json", "number",
              ],
              check=False,
              capture_output=True,
              text=True,
       )
       if result.returncode != 0:
              return 0
       try:
              return len(json.loads(result.stdout or "[]"))
       except json.JSONDecodeError:
              return 0


def create_repo(org: str, name: str, description: str, dry_run: bool) -> tuple[str, bool]:
       """Create GitHub repo and return clone URL and whether it was newly created."""
       print(f"\n[repo] Creating repo: {org}/{name}")
       if dry_run:
              print(f"   [DRY RUN] gh repo create {org}/{name} --public")
              return f"https://github.com/{org}/{name}.git", False

       if repo_exists(org, name):
              print(f"   [resume] Exists, reusing: https://github.com/{org}/{name}")
              return f"https://github.com/{org}/{name}.git", False

       run([
              "gh", "repo", "create", f"{org}/{name}",
              "--public", "--description", description,
              "--clone=false",
       ])
       print(f"   [ok] Created: https://github.com/{org}/{name}")
       return f"https://github.com/{org}/{name}.git", True


def scaffold_pr(repo_dir: str, org: str, repo_name: str,
                pr: PRSpec, pr_num: int, dry_run: bool):
    """Create a branch, commit files, push, open PR, merge, optionally add fix commit."""

    print(f"  [{pr_num:2d}] {pr.branch}  {'⚠ DEFECTIVE' if pr.defective else '✓ clean'}")

    if dry_run:
        return

    # Create branch
    run(["git", "checkout", "-b", pr.branch], cwd=repo_dir)

    # Write files
    for filepath, content in pr.files.items():
        full = Path(repo_dir) / filepath
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")

    # Commit
    run(["git", "add", "."], cwd=repo_dir)
    run(["git", "commit", "-m", pr.title], cwd=repo_dir)

    # Push
    # Force-update avoids failures when resuming and a remote branch with the same
    # name exists from a prior partial run.
    run(["git", "push", "--force", "--set-upstream", "origin", pr.branch], cwd=repo_dir)

    # Open PR
    run(["gh", "pr", "create",
         "--title", pr.title,
         "--body", pr.body,
         "--base", "main",
         "--head", pr.branch], cwd=repo_dir)

    # Merge PR
    run(["gh", "pr", "merge", pr.branch, "--merge", "--delete-branch"],
        cwd=repo_dir)

    # Pull merged state back to local main
    run(["git", "checkout", "main"], cwd=repo_dir)
    run(["git", "pull"], cwd=repo_dir)

    # Add fix commit for defective PRs (triggers auto-labeller)
    if pr.defective and pr.fix_message:
        fix_file = Path(repo_dir) / f"fixes/fix_{pr_num:02d}.py"
        fix_file.parent.mkdir(parents=True, exist_ok=True)
        fix_file.write_text(
            f"# {pr.fix_message}\\n# Applied fix after detecting issue in PR #{pr_num}\\n",
            encoding="utf-8",
        )
        run(["git", "add", "."], cwd=repo_dir)
        run(["git", "commit", "-m", pr.fix_message], cwd=repo_dir)
        run(["git", "push"], cwd=repo_dir)

    time.sleep(1)  # avoid GitHub rate limits


def scaffold_repo(org: str, name: str, description: str,
                  prs: list[PRSpec], dry_run: bool):
       clone_url, created_new = create_repo(org, name, description, dry_run)

       with tempfile.TemporaryDirectory() as tmpdir:
              repo_dir = os.path.join(tmpdir, name)

              if not dry_run:
                     # Clone
                     run(["git", "clone", clone_url, repo_dir])

                     if created_new:
                            # Create initial commit only for newly-created repos.
                            readme = Path(repo_dir) / "README.md"
                            readme.write_text(f"# {name}\n\n{description}\n", encoding="utf-8")
                            run(["git", "add", "."], cwd=repo_dir)
                            run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir)
                            run(["git", "push"], cwd=repo_dir)

              start_index = 0
              prs_to_create = prs
              if not dry_run:
                     start_index = get_existing_pr_count(org, name)
                     if start_index >= len(prs):
                            print(f"  All PRs already present ({start_index}/{len(prs)}), skipping.")
                            print(f"\n[ok] Repo complete: https://github.com/{org}/{name}")
                            return
                     if start_index > 0:
                            print(f"  Resuming at PR {start_index + 1} (already present: {start_index})")
                     prs_to_create = prs[start_index:]

              print(f"  Creating {len(prs_to_create)} PRs ...")
              for i, pr in enumerate(prs_to_create, start_index + 1):
                     scaffold_pr(repo_dir, org, name, pr, i, dry_run)

       print(f"\n[ok] Repo complete: https://github.com/{org}/{name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", required=True,
                        help="GitHub username or org (e.g. kavitaj11)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without creating anything")
    parser.add_argument("--repo", default=None,
                        help="Only scaffold one repo by name (e.g. k11-eval-api)")
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN — no repos or PRs will be created\n")

    # Check prerequisites
    if not args.dry_run:
        for tool in ["git", "gh"]:
            if not shutil.which(tool):
                print(f"ERROR: '{tool}' not found. Install GitHub CLI: https://cli.github.com")
                sys.exit(1)

    total_prs = sum(len(prs) for _, _, prs in REPOS)
    defective  = sum(pr.defective for _, _, prs in REPOS for pr in prs)
    print(f"Plan: {len(REPOS)} repos, {total_prs} PRs total ({defective} defective, {total_prs-defective} clean)\n")

    for repo_name, description, prs in REPOS:
        if args.repo and args.repo != repo_name:
            continue
        scaffold_repo(args.org, repo_name, description, prs, args.dry_run)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}All repos scaffolded.")
    if not args.dry_run:
        print("\nNext step:")
        print(f"  python eval/01_collect_dataset.py \\")
        print(f"    --repos {args.org}/k11-eval-api {args.org}/k11-eval-pipeline {args.org}/k11-eval-webapp \\")
        print(f"    --since 2026-01-01 --until 2026-06-30 --per-repo 40")


if __name__ == "__main__":
    main()




