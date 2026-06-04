"""
eval/03_run_evaluation.py
─────────────────────────
Replays every PR in the labelled dataset through the K11tech Agentic AI QA
System pipeline and logs the result. Runs each PR twice:

  • PARALLEL  — normal pipeline (Phase 2 Send API, concurrent agents)
  • SERIAL    — forced sequential execution (baseline for RQ1 timing)

Results are appended to eval/data/results.jsonl (one JSON line per run).

Usage:
    python eval/03_run_evaluation.py \
        --dataset  eval/data/dataset_labelled.json \
        --out      eval/data/results.jsonl \
        --mode     both          # parallel | serial | both
        --start-at 0             # resume from PR index N
        --webhook  http://localhost:9000  # pipeline webhook URL
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

WEBHOOK_DEFAULT = "http://localhost:9000"
POLL_INTERVAL_S = 1.0
POLL_TIMEOUT_S = 600.0


def _is_flagged_verdict(verdict: str | None) -> bool:
    """Return True when the system verdict indicates risk/defect escalation."""
    return verdict in ("BLOCK", "NEEDS_REVIEW", "FAIL", "REJECT")


async def trigger_pipeline(
    client: httpx.AsyncClient,
    webhook_url: str,
    repo: str,
    pr_number: int,
    mode: str,  # "parallel" | "serial"
) -> dict:
    """POST a synthetic PR event and poll status until the run finishes."""
    payload = {
        "action": "opened",
        "repository": {"full_name": repo},
        "pull_request": {
            "number": pr_number,
            "base": {"ref": "main"},
            "user": {"login": "eval-bot"},
        },
        "eval_mode": mode,
    }

    start = time.monotonic()
    resp = await client.post(
        f"{webhook_url}/webhook/github",
        json=payload,
        headers={"X-Eval-Mode": mode, "X-GitHub-Event": "pull_request"},
        timeout=600,
    )
    resp.raise_for_status()
    body = resp.json()

    if body.get("status") == "ignored":
        return {
            "run_id": body.get("run_id"),
            "verdict": None,
            "risk_score": None,
            "hitl_triggered": False,
            "defects_found": [],
            "eval_passed": None,
            "duration_s": round(time.monotonic() - start, 2),
            "error": f"webhook ignored event/action: {body}",
        }

    run_id = body.get("run_id")
    if not run_id:
        return {
            "run_id": None,
            "verdict": body.get("verdict"),
            "risk_score": body.get("risk_score"),
            "hitl_triggered": body.get("hitl_triggered", False),
            "defects_found": body.get("defects_found", []),
            "eval_passed": body.get("eval_passed"),
            "duration_s": round(time.monotonic() - start, 2),
            "error": body.get("error") or "missing run_id in webhook response",
        }

    deadline = start + POLL_TIMEOUT_S
    status_payload: dict = {}
    while time.monotonic() < deadline:
        status_resp = await client.get(
            f"{webhook_url}/api/pipeline/{run_id}/status",
            timeout=60,
        )
        if status_resp.status_code == 404:
            await asyncio.sleep(POLL_INTERVAL_S)
            continue

        status_resp.raise_for_status()
        status_payload = status_resp.json()
        if status_payload.get("verdict") is not None:
            break

        await asyncio.sleep(POLL_INTERVAL_S)

    duration = time.monotonic() - start
    verdict = status_payload.get("verdict")
    defect_count = status_payload.get("defect_count")

    return {
        "run_id":       run_id,
        "verdict":      verdict,
        "risk_score":   None,
        "hitl_triggered": verdict == "NEEDS_REVIEW",
        "defects_found":  [] if defect_count is None else [{}] * int(defect_count),
        "eval_passed":    status_payload.get("eval_passed"),
        "duration_s":     round(duration, 2),
        "error":          None if verdict is not None else "timed out waiting for pipeline verdict",
    }


async def run_pr(
    client: httpx.AsyncClient,
    webhook_url: str,
    pr: dict,
    mode: str,
) -> dict:
    try:
        result = await trigger_pipeline(
            client, webhook_url, pr["repo"], pr["pr_number"], mode
        )
    except Exception as exc:
        result = {
            "run_id": None, "verdict": None, "risk_score": None,
            "hitl_triggered": False, "defects_found": [],
            "eval_passed": None, "duration_s": None,
            "error": str(exc),
        }

    return {
        "pr_id":         pr["id"],
        "repo":          pr["repo"],
        "pr_number":     pr["pr_number"],
        "ground_truth":  pr["ground_truth"],
        "mode":          mode,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        **result,
    }


def classify(verdict: str | None, ground_truth: str) -> str:
    """Map (verdict, ground_truth) to TP/FP/TN/FN."""
    flagged = _is_flagged_verdict(verdict)
    actual  = ground_truth == "DEFECTIVE"
    if flagged and actual:   return "TP"
    if flagged and not actual: return "FP"
    if not flagged and actual: return "FN"
    return "TN"


async def main_async(args):
    with open(args.dataset) as f:
        dataset = json.load(f)

    prs = dataset["prs"]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    modes = (
        ["parallel", "serial"] if args.mode == "both"
        else [args.mode]
    )

    total = len(prs) * len(modes)
    done  = 0

    async with httpx.AsyncClient(timeout=600) as client:
        with open(args.out, "a") as out_f:
            for i, pr in enumerate(prs):
                if i < args.start_at:
                    continue

                for mode in modes:
                    done += 1
                    print(f"[{done:3d}/{total}] {pr['id']:40s}  mode={mode} ...", end=" ", flush=True)

                    result = await run_pr(client, args.webhook, pr, mode)
                    cls    = classify(result.get("verdict"), pr["ground_truth"])
                    dur    = result.get("duration_s")
                    print(f"{cls}  {dur}s  verdict={result.get('verdict')}")

                    out_f.write(json.dumps(result) + "\n")
                    out_f.flush()

                    # Gentle pause between PRs to avoid hammering the pipeline
                    await asyncio.sleep(2)

    print(f"\n✓ Evaluation complete. Results written to: {args.out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset",  default="eval/data/dataset_labelled.json")
    parser.add_argument("--out",      default="eval/data/results.jsonl")
    parser.add_argument("--mode",     default="both",
                        choices=["parallel", "serial", "both"])
    parser.add_argument("--start-at", dest="start_at", type=int, default=0,
                        help="Resume from PR index N (useful after interruption)")
    parser.add_argument("--webhook",  default=os.getenv("WEBHOOK_URL", WEBHOOK_DEFAULT))
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
