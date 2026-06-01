"""
FastAPI webhook server.
Receives GitHub PR events and HITL decisions (from Slack bot or review UI).
"""

from __future__ import annotations
import asyncio
import hashlib
import hmac
import logging
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pipeline import run_pipeline, submit_hitl_decision, get_pipeline_state

logger  = logging.getLogger(__name__)
app     = FastAPI(title="K11 TechLab QA Webhook", version="2.0.0")
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


# ── Models ────────────────────────────────────────────────────────────────────

class HITLDecisionRequest(BaseModel):
    run_id:    str
    decision:  str          # "approve" | "reject"
    reviewer:  str
    comment:   Optional[str] = ""
    pr_number: Optional[int] = 0
    repo_name: Optional[str] = ""


class PipelineStatusResponse(BaseModel):
    run_id:      str
    eval_passed: Optional[bool]
    verdict:     Optional[str]
    defect_count: Optional[int]
    error_count:  Optional[int]


# ── GitHub webhook ────────────────────────────────────────────────────────────

@app.post("/webhook/github")
async def github_webhook(
    request:          Request,
    background_tasks: BackgroundTasks,
    x_github_event:   str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
):
    body = await request.body()

    if WEBHOOK_SECRET:
        _verify_signature(body, x_hub_signature_256)

    if x_github_event != "pull_request":
        return JSONResponse({"status": "ignored", "event": x_github_event})

    payload = await request.json()
    action  = payload.get("action")
    if action not in ("opened", "synchronize", "reopened"):
        return JSONResponse({"status": "ignored", "action": action})

    pr      = payload["pull_request"]
    pr_diff = await _fetch_pr_diff(
        repo_name=payload["repository"]["full_name"],
        pr_number=pr["number"],
    )

    import uuid
    run_id = str(uuid.uuid4())

    background_tasks.add_task(
        _run_pipeline_background,
        run_id=run_id,
        pr_number=pr["number"],
        repo_name=payload["repository"]["full_name"],
        pr_diff=pr_diff,
        base_branch=pr["base"]["ref"],
        author=pr["user"]["login"],
    )

    logger.info("Pipeline triggered: run_id=%s pr=%s#%d", run_id, payload["repository"]["full_name"], pr["number"])
    return JSONResponse({"status": "accepted", "run_id": run_id}, status_code=202)


# ── HITL endpoints ────────────────────────────────────────────────────────────

@app.post("/api/hitl/decision")
async def hitl_decision(req: HITLDecisionRequest, background_tasks: BackgroundTasks):
    """Resume a pipeline paused at the HITL gate."""
    if req.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    background_tasks.add_task(
        _resume_pipeline_background,
        run_id=req.run_id,
        decision=req.decision,
        reviewer=req.reviewer,
        comment=req.comment or "",
        pr_number=req.pr_number or 0,
        repo_name=req.repo_name or "",
    )
    logger.info("HITL decision queued: run_id=%s decision=%s reviewer=%s", req.run_id, req.decision, req.reviewer)
    return JSONResponse({"status": "accepted", "run_id": req.run_id})


# Slack slash command handler: /qa-approve <run_id> or /qa-reject <run_id> <reason>
@app.post("/api/slack/command")
async def slack_command(request: Request, background_tasks: BackgroundTasks):
    form   = await request.form()
    text   = str(form.get("text", "")).strip()
    cmd    = str(form.get("command", ""))
    user   = str(form.get("user_name", "slack-user"))

    parts  = text.split(None, 1)
    run_id = parts[0] if parts else ""
    comment = parts[1] if len(parts) > 1 else ""

    if not run_id:
        return JSONResponse({"text": "Usage: /qa-approve <run_id> or /qa-reject <run_id> [reason]"})

    decision = "approve" if "approve" in cmd else "reject"
    background_tasks.add_task(
        _resume_pipeline_background,
        run_id=run_id, decision=decision, reviewer=user, comment=comment,
    )
    return JSONResponse({"text": f":hourglass: Processing {decision} for run `{run_id}`..."})


# ── Status endpoint ───────────────────────────────────────────────────────────

@app.get("/api/pipeline/{run_id}/status")
async def pipeline_status(run_id: str, pr_number: int = 0, repo_name: str = ""):
    state = await get_pipeline_state(run_id, pr_number, repo_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    summary = state.get("summary") or {}
    return PipelineStatusResponse(
        run_id=run_id,
        eval_passed=state.get("eval_passed"),
        verdict=summary.get("verdict"),
        defect_count=summary.get("defect_count"),
        error_count=len(state.get("errors", [])),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _run_pipeline_background(**kwargs):
    try:
        await run_pipeline(**kwargs)
    except Exception as exc:
        logger.error("Background pipeline failed: %s", exc, exc_info=True)


async def _resume_pipeline_background(**kwargs):
    try:
        await submit_hitl_decision(**kwargs)
    except Exception as exc:
        logger.error("Background HITL resume failed: %s", exc, exc_info=True)


async def _fetch_pr_diff(repo_name: str, pr_number: int) -> str:
    """Fetch the unified diff for a PR via GitHub API."""
    import aiohttp
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github.v3.diff"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                return await resp.text()
    except Exception as exc:
        logger.error("Failed to fetch PR diff: %s", exc)
        return ""


def _verify_signature(body: bytes, signature: str) -> None:
    if not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing signature")
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
