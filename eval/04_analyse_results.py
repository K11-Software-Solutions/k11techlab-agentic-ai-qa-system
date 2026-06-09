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
eval/04_analyse_results.py
──────────────────────────
Reads results.jsonl and computes all metrics for the four research questions:

  RQ1 — Execution time: parallel vs serial (mean, σ, % reduction)
  RQ2 — Defect detection: precision, recall, F1, false positive rate
  RQ3 — False negative rate (production escapes)
  RQ4 — HITL activation rate / eval pass rate

Outputs:
  • Terminal summary
  • eval/data/metrics.json   — machine-readable metrics
  • eval/data/summary.csv    — per-PR result table

Usage:
    python eval/04_analyse_results.py \
        --results eval/data/results.jsonl \
        --out-dir eval/data/
"""

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def load_results(path: str) -> list[dict]:
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    m = statistics.mean(values)
    s = statistics.stdev(values) if len(values) > 1 else 0.0
    return round(m, 2), round(s, 2)


def classify(verdict: str | None, ground_truth: str) -> str:
    flagged = verdict in ("BLOCK", "NEEDS_REVIEW", "FAIL", "REJECT")
    actual  = ground_truth == "DEFECTIVE"
    if flagged and actual:     return "TP"
    if flagged and not actual: return "FP"
    if not flagged and actual: return "FN"
    return "TN"


def f1(tp, fp, fn) -> float:
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return round(2 * prec * rec / (prec + rec), 3) if (prec + rec) > 0 else 0.0


def analyse(results: list[dict]) -> dict:
    # Split by mode
    by_mode = defaultdict(list)
    for r in results:
        by_mode[r["mode"]].append(r)

    # ── RQ1: Execution time ───────────────────────────────────────────────────
    rq1 = {}
    for mode, runs in by_mode.items():
        durations = [r["duration_s"] for r in runs if r.get("duration_s") is not None]
        m, s = mean_std(durations)
        rq1[mode] = {"mean_min": round(m / 60, 2), "std_min": round(s / 60, 2),
                     "mean_s": m, "std_s": s, "n": len(durations)}

    reduction = None
    if "parallel" in rq1 and "serial" in rq1:
        par = rq1["parallel"]["mean_s"]
        ser = rq1["serial"]["mean_s"]
        reduction = round((1 - par / ser) * 100, 1) if ser > 0 else None
    rq1["speedup_pct"] = reduction

    # ── RQ2: Defect detection (parallel mode only) ────────────────────────────
    parallel_runs = by_mode.get("parallel", [])
    counts = defaultdict(int)
    for r in parallel_runs:
        cls = classify(r.get("verdict"), r["ground_truth"])
        counts[cls] += 1

    tp, fp, fn, tn = counts["TP"], counts["FP"], counts["FN"], counts["TN"]
    total = tp + fp + fn + tn
    precision = round(tp / (tp + fp), 3) if (tp + fp) > 0 else 0.0
    recall    = round(tp / (tp + fn), 3) if (tp + fn) > 0 else 0.0
    fpr       = round(fp / (fp + tn), 3) if (fp + tn) > 0 else 0.0

    rq2 = {
        "TP": tp, "FP": fp, "FN": fn, "TN": tn, "total": total,
        "detection_rate_pct": round(recall * 100, 1),
        "false_positive_rate_pct": round(fpr * 100, 1),
        "precision": precision,
        "recall": recall,
        "f1": f1(tp, fp, fn),
    }

    # ── RQ3: False negatives (production escapes) ─────────────────────────────
    # FN = approved by system but DEFECTIVE ground truth
    rq3 = {
        "false_negatives": fn,
        "production_escape_rate_pct": round(fn / total * 100, 1) if total > 0 else 0.0,
        "note": "Production escapes = PRs not flagged (for example PASS/APPROVE) with DEFECTIVE ground truth",
    }

    # ── RQ4: HITL activation + eval pass rate ────────────────────────────────
    hitl_runs   = [r for r in parallel_runs if r.get("hitl_triggered")]
    eval_passed = [r for r in parallel_runs if r.get("eval_passed") is True]
    eval_total  = [r for r in parallel_runs if r.get("eval_passed") is not None]

    rq4 = {
        "hitl_activations": len(hitl_runs),
        "hitl_activation_rate_pct": round(len(hitl_runs) / len(parallel_runs) * 100, 1)
                                    if parallel_runs else 0.0,
        "eval_pass_count": len(eval_passed),
        "eval_total": len(eval_total),
        "eval_pass_rate_pct": round(len(eval_passed) / len(eval_total) * 100, 1)
                              if eval_total else 0.0,
    }

    return {"rq1": rq1, "rq2": rq2, "rq3": rq3, "rq4": rq4}


def print_summary(metrics: dict):
    r1 = metrics["rq1"]
    r2 = metrics["rq2"]
    r3 = metrics["rq3"]
    r4 = metrics["rq4"]

    print("\n" + "═" * 60)
    print("  K11tech Agentic AI QA System — Evaluation Results")
    print("═" * 60)

    print("\n── RQ1: Execution Time ──────────────────────────────────")
    for mode in ("parallel", "serial"):
        if mode in r1:
            d = r1[mode]
            print(f"  {mode:10s}: {d['mean_min']} min  (σ={d['std_min']} min,  n={d['n']})")
    if r1.get("speedup_pct") is not None:
        print(f"  Speedup (parallel vs serial): {r1['speedup_pct']}% reduction")

    print("\n── RQ2: Defect Detection (parallel mode) ────────────────")
    print(f"  TP={r2['TP']}  FP={r2['FP']}  FN={r2['FN']}  TN={r2['TN']}  (n={r2['total']})")
    print(f"  Detection rate : {r2['detection_rate_pct']}%")
    print(f"  False pos rate : {r2['false_positive_rate_pct']}%")
    print(f"  Precision      : {r2['precision']}")
    print(f"  Recall         : {r2['recall']}")
    print(f"  F1 Score       : {r2['f1']}")

    print("\n── RQ3: Production Escapes ──────────────────────────────")
    print(f"  False negatives (escapes): {r3['false_negatives']}")
    print(f"  Escape rate              : {r3['production_escape_rate_pct']}%")

    print("\n── RQ4: HITL & Self-Evaluation ──────────────────────────")
    print(f"  HITL activations  : {r4['hitl_activations']}  ({r4['hitl_activation_rate_pct']}%)")
    print(f"  Eval pass rate    : {r4['eval_pass_count']}/{r4['eval_total']}  ({r4['eval_pass_rate_pct']}%)")
    print("\n" + "═" * 60)


def write_csv(results: list[dict], path: str):
    fields = [
        "pr_id", "repo", "pr_number", "ground_truth", "mode",
        "verdict", "risk_score", "hitl_triggered", "eval_passed",
        "duration_s", "duration_min", "classification", "error",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            cls = classify(r.get("verdict"), r.get("ground_truth", ""))
            dur = r.get("duration_s")
            writer.writerow({
                **r,
                "duration_min": round(dur / 60, 2) if dur else None,
                "classification": cls,
            })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default="eval/data/results.jsonl")
    parser.add_argument("--out-dir", default="eval/data/")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    results = load_results(args.results)
    print(f"Loaded {len(results)} run records.")

    metrics = analyse(results)
    print_summary(metrics)

    # Save metrics JSON
    metrics_path = out / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\n✓ Metrics saved : {metrics_path}")

    # Save per-PR CSV
    csv_path = out / "summary.csv"
    write_csv(results, str(csv_path))
    print(f"✓ Summary CSV   : {csv_path}")


if __name__ == "__main__":
    main()
