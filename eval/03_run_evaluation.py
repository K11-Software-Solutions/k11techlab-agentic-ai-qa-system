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


async def trigger_pipeline(
    client: httpx.AsyncClient,
    webhook_url: str,
    repo: str,
    pr_number: int,
    mode: str,  # "parallel" | "serial"
) -> dict:
    """POST a synthetic PR event to the webhook and poll for the result."""
    payload = {
        "action": "closed",
        "pull_request": {
            "number": pr_number,
            "merged": True,
            "base": {"repo": {"full_name": repo}},
        },
        "eval_mode": mode,          # pipeline reads this to switch dispatch strategy
    }

    start = time.monotonic()
    resp = await client.post(
        f"{webhook_url}/webhook/github",
        json=payload,
        headers={"X-Eval-Mode": mode},
        timeout=600,
    )
    resp.raise_for_status()
    duration = time.monotonic() - start

    body = resp.json()
    return {
        "run_id":       body.get("run_id"),
        "verdict":      body.get("verdict"),          # APPROVE | BLOCK | NEEDS_REVIEW
        "risk_score":   body.get("risk_score"),
        "hitl_triggered": body.get("hitl_triggered", False),
        "defects_found":  body.get("defects_found", []),
        "eval_passed":    body.get("eval_passed"),
        "duration_s":     round(duration, 2),
        "error":          body.get("error"),
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
    # BLOCK or NEEDS_REVIEW = system flagged as defective
    flagged = verdict in ("BLOCK", "NEEDS_REVIEW")
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
