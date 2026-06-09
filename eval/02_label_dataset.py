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
"""
eval/02_label_dataset.py
────────────────────────
Auto-labels each PR in the dataset as DEFECTIVE or CLEAN using two
heuristics applied to post-merge commit history:

  1. Bug-fix commit  — a commit merged within 30 days of the PR whose
     message matches bug/fix/hotfix/revert/regression keywords.
  2. Revert commit   — a commit that reverts the PR's merge commit.

A PR is labelled DEFECTIVE if either heuristic fires.
A PR is labelled CLEAN otherwise.

After auto-labelling, optionally export a CSV for manual override by
a second reviewer (used to compute Cohen's κ).

Usage:
    python eval/02_label_dataset.py \
        --dataset eval/data/dataset.json \
        --out     eval/data/dataset_labelled.json \
        --csv     eval/data/manual_review.csv
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

GITHUB_API  = "https://api.github.com"
BUG_PATTERN = re.compile(
    r"\b(fix|bug|hotfix|revert|regression|broke|broken|incident|rollback|patch)\b",
    re.IGNORECASE,
)
REVERT_PATTERN = re.compile(r'revert\s+"?merge pull request #(\d+)', re.IGNORECASE)
WINDOW_DAYS = 30


def github_headers():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN not set.", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def commits_after_merge(client: httpx.Client, repo: str, merged_at: str) -> list[dict]:
    """Fetch commits to default branch in the 30-day window after merge."""
    merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    since = merged_dt.isoformat()
    until = (merged_dt + timedelta(days=WINDOW_DAYS)).isoformat()

    resp = client.get(
        f"{GITHUB_API}/repos/{repo}/commits",
        params={"since": since, "until": until, "per_page": 100},
    )
    if resp.status_code == 409:   # empty repo
        return []
    resp.raise_for_status()
    return resp.json()


def label_pr(client: httpx.Client, pr: dict) -> tuple[str, str]:
    """Return (label, method) for a single PR."""
    repo      = pr["repo"]
    pr_number = pr["pr_number"]
    merged_at = pr["merged_at"]

    commits = commits_after_merge(client, repo, merged_at)
    time.sleep(0.3)

    for commit in commits:
        msg = commit.get("commit", {}).get("message", "")

        # Heuristic 1 — revert of this PR
        m = REVERT_PATTERN.search(msg)
        if m and int(m.group(1)) == pr_number:
            return "DEFECTIVE", "revert_commit"

        # Heuristic 2 — bug-fix keywords
        if BUG_PATTERN.search(msg):
            return "DEFECTIVE", "bugfix_keyword"

    return "CLEAN", "no_signal"


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """Compute Cohen's κ between two label lists."""
    assert len(labels_a) == len(labels_b)
    n = len(labels_a)
    cats = list(set(labels_a) | set(labels_b))
    po = sum(a == b for a, b in zip(labels_a, labels_b)) / n
    pe = sum(
        (labels_a.count(c) / n) * (labels_b.count(c) / n)
        for c in cats
    )
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="eval/data/dataset.json")
    parser.add_argument("--out",     default="eval/data/dataset_labelled.json")
    parser.add_argument("--csv",     default="eval/data/manual_review.csv",
                        help="Export CSV for second reviewer")
    parser.add_argument("--import-csv", dest="import_csv", default=None,
                        help="Import completed manual review CSV to merge labels")
    args = parser.parse_args()

    with open(args.dataset) as f:
        dataset = json.load(f)

    prs = dataset["prs"]

    # ── Import manual review if provided ──────────────────────────────────────
    if args.import_csv:
        manual = {}
        with open(args.import_csv) as f:
            for row in csv.DictReader(f):
                manual[row["id"]] = row["reviewer_label"].upper()

        auto_labels  = [pr["ground_truth"] for pr in prs if pr["id"] in manual]
        human_labels = [manual[pr["id"]]   for pr in prs if pr["id"] in manual]
        kappa = cohen_kappa(auto_labels, human_labels)
        print(f"Cohen's κ (auto vs human): {kappa:.3f}")

        # Resolve disagreements: human label wins
        disagreements = 0
        for pr in prs:
            if pr["id"] in manual and manual[pr["id"]] != pr["ground_truth"]:
                pr["ground_truth"]  = manual[pr["id"]]
                pr["label_method"]  = "manual_override"
                disagreements += 1
        print(f"Disagreements resolved (human wins): {disagreements}")

    else:
        # ── Auto-label ────────────────────────────────────────────────────────
        with httpx.Client(headers=github_headers(), timeout=30) as client:
            for i, pr in enumerate(prs):
                label, method = label_pr(client, pr)
                pr["ground_truth"] = label
                pr["label_method"] = method
                status = "⚠ DEFECTIVE" if label == "DEFECTIVE" else "✓ clean"
                print(f"  [{i+1:3d}/{len(prs)}] {pr['id']:40s} {status}  ({method})")

        defective = sum(1 for p in prs if p["ground_truth"] == "DEFECTIVE")
        print(f"\nAuto-label complete: {defective} DEFECTIVE / {len(prs)-defective} CLEAN")

        # ── Export CSV for manual review ──────────────────────────────────────
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "repo", "pr_number", "title", "merged_at",
                "auto_label", "label_method", "reviewer_label", "reviewer_notes"
            ])
            writer.writeheader()
            for pr in prs:
                writer.writerow({
                    "id":              pr["id"],
                    "repo":            pr["repo"],
                    "pr_number":       pr["pr_number"],
                    "title":           pr["title"],
                    "merged_at":       pr["merged_at"],
                    "auto_label":      pr["ground_truth"],
                    "label_method":    pr["label_method"],
                    "reviewer_label":  "",   # to be filled by reviewer
                    "reviewer_notes":  "",
                })
        print(f"Manual review CSV exported: {args.csv}")
        print("→ Fill in 'reviewer_label' column, then re-run with --import-csv")

    # ── Save labelled dataset ─────────────────────────────────────────────────
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"\n✓ Labelled dataset saved: {args.out}")


if __name__ == "__main__":
    main()
