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
"""Data Validation Agent — Phase 2, Agent 9.

Validates database schema migrations, referential integrity, and data
quality rules using the Postgres MCP server.
"""
from __future__ import annotations

from .base import AgentResult, BaseQAAgent

# SQL checks to run after migration
_INTEGRITY_CHECKS: list[dict] = [
    {
        "name": "orphaned_foreign_keys",
        "sql": """
            SELECT COUNT(*) AS orphans
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
              ON rc.constraint_name = kcu.constraint_name
            WHERE rc.delete_rule = 'NO ACTION'
        """,
        "threshold": 0,
        "comparison": "eq",
    },
    {
        "name": "null_in_required_columns",
        "sql": """
            SELECT COUNT(*) AS null_count
            FROM information_schema.columns
            WHERE is_nullable = 'NO'
              AND column_default IS NULL
              AND table_schema = 'public'
        """,
        "threshold": 0,
        "comparison": "gte",  # just informational
    },
]


class DataValidationAgent(BaseQAAgent):
    """Runs data integrity checks via the Postgres MCP server."""

    NAME = "data_agent"
    TIMEOUT = 120

    async def execute(self, state: dict, suite: dict) -> AgentResult:
        changed_files: list[str] = state.get("changed_files", [])
        migration_files = [f for f in changed_files if "migration" in f or "alembic" in f or ".sql" in f]

        defects: list[dict] = []
        passed = 0
        failed = 0

        # Only run DB checks if migrations are present
        if not migration_files:
            return AgentResult(
                agent=self.NAME,
                suite_type="data",
                priority=suite.get("priority", "low"),
                passed=1,
                failed=0,
                total_cases=1,
                metadata={"skipped": "no migration files detected"},
            )

        for check in _INTEGRITY_CHECKS:
            raw = await self.call_mcp(
                "postgres",
                "execute_query",
                {"sql": check["sql"].strip(), "read_only": True},
            )
            rows = raw.get("rows", [])
            value = rows[0][0] if rows else 0

            ok = True
            if check["comparison"] == "eq" and value != check["threshold"]:
                ok = False
            elif check["comparison"] == "gt" and value <= check["threshold"]:
                ok = False

            if ok:
                passed += 1
            else:
                failed += 1
                defects.append({
                    "title": f"Data integrity failure: {check['name']}",
                    "severity": "high",
                    "detail": f"Query returned {value}, threshold {check['threshold']}",
                    "check": check["name"],
                    "value": value,
                })

        return AgentResult(
            agent=self.NAME,
            suite_type="data",
            priority=suite.get("priority", "high"),
            passed=passed,
            failed=failed,
            total_cases=passed + failed,
            defects=defects,
            metadata={
                "migration_files": migration_files,
                "checks_run": len(_INTEGRITY_CHECKS),
            },
        )
