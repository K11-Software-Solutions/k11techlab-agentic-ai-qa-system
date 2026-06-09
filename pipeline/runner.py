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
Pipeline runner — entry points for starting and resuming CI pipeline runs.
"""

from __future__ import annotations
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.memory import MemorySaver

from .state import CIPipelineState, initial_state
from .orchestrator import ci_builder

logger = logging.getLogger(__name__)

DB_PATH      = os.getenv("CHECKPOINT_DB", "checkpoints.db")
PIPELINE_VER = "2.0.0"


def _make_config(run_id: str, pr_number: int, repo_name: str) -> RunnableConfig:
    """Build the LangSmith-enriched RunnableConfig for a pipeline run."""
    project = f"k11techlab-agentic-qa-pr-{pr_number}"
    os.environ["LANGSMITH_PROJECT"] = project
    return RunnableConfig(
        configurable={"thread_id": run_id},
        tags=["production", f"pr-{pr_number}", repo_name.replace("/", "-")],
        metadata={
            "pr_number":        pr_number,
            "repo_name":        repo_name,
            "run_id":           run_id,
            "pipeline_version": PIPELINE_VER,
            "triggered_by":     "github_webhook",
        },
        run_name=f"ci-{repo_name.split('/')[-1]}-pr{pr_number}",
        max_concurrency=8,
    )


async def run_pipeline(
    pr_number: int,
    repo_name: str,
    pr_diff:   str,
    base_branch: str = "main",
    author: str = "",
    triggered_by: str = "github_webhook",
    run_id: str | None = None,
    use_memory: bool = False,
) -> CIPipelineState:
    """
    Start a new CI pipeline run and await completion.

    Args:
        use_memory: If True, use in-memory checkpointer (for tests).
    Returns:
        Final CIPipelineState.
    """
    run_id = run_id or str(uuid.uuid4())
    state  = initial_state(
        run_id=run_id,
        pr_number=pr_number,
        repo_name=repo_name,
        pr_diff=pr_diff,
        base_branch=base_branch,
        author=author,
        triggered_by=triggered_by,
    )
    config = _make_config(run_id, pr_number, repo_name)

    logger.info("Starting pipeline run_id=%s pr=%s#%d", run_id, repo_name, pr_number)

    if use_memory:
        app = ci_builder.compile(checkpointer=MemorySaver())
        result = await app.ainvoke(state, config)
    else:
        async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
            app = ci_builder.compile(checkpointer=checkpointer)
            result = await app.ainvoke(state, config)

    logger.info(
        "Pipeline complete run_id=%s verdict=%s eval_passed=%s",
        run_id,
        (result.get("summary") or {}).get("verdict"),
        result.get("eval_passed"),
    )
    return result


async def stream_pipeline(
    pr_number: int,
    repo_name: str,
    pr_diff:   str,
    run_id: str | None = None,
) -> AsyncIterator[dict]:
    """Stream pipeline events as they occur (for real-time webhook responses)."""
    run_id = run_id or str(uuid.uuid4())
    state  = initial_state(run_id=run_id, pr_number=pr_number, repo_name=repo_name, pr_diff=pr_diff)
    config = _make_config(run_id, pr_number, repo_name)

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        app = ci_builder.compile(checkpointer=checkpointer)
        async for event in app.astream(state, config, stream_mode="updates"):
            yield {"run_id": run_id, "event": event}


async def submit_hitl_decision(
    run_id:   str,
    decision: str,        # "approve" | "reject"
    reviewer: str,
    comment:  str = "",
    pr_number: int = 0,
    repo_name: str = "",
) -> CIPipelineState:
    """
    Resume a pipeline paused at the HITL gate.
    Called by the Slack bot or the /api/hitl webhook endpoint.
    """
    if decision not in ("approve", "reject"):
        raise ValueError(f"decision must be 'approve' or 'reject', got '{decision}'")

    config = _make_config(run_id, pr_number, repo_name)
    logger.info("HITL decision: run_id=%s decision=%s reviewer=%s", run_id, decision, reviewer)

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        app = ci_builder.compile(checkpointer=checkpointer)
        await app.aupdate_state(
            config,
            {
                "hitl_decision": decision,
                "hitl_reviewer": reviewer,
                "hitl_comment":  comment,
            },
            as_node="human_review_gate",
        )
        result = await app.ainvoke(None, config)

    return result


async def get_pipeline_state(run_id: str, pr_number: int = 0, repo_name: str = "") -> dict | None:
    """Retrieve the latest checkpoint state for a run (for status checks)."""
    config = _make_config(run_id, pr_number, repo_name)
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        app = ci_builder.compile(checkpointer=checkpointer)
        snapshot = await app.aget_state(config)
        return snapshot.values if snapshot else None
