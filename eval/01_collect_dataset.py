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
eval/01_collect_dataset.py
──────────────────────────
Fetches merged pull requests from GitHub repos and saves them as a
structured JSON dataset for the K11tech Agentic AI QA System evaluation.

Usage:
    export GITHUB_TOKEN=ghp_...
    python eval/01_collect_dataset.py \
        --repos owner/repo1 owner/repo2 owner/repo3 \
        --since 2026-01-01 \
        --until 2026-06-30 \
        --per-repo 40 \
        --out eval/data/dataset.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

GITHUB_API = "https://api.github.com"


def github_headers():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable not set.", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_prs(client: httpx.Client, repo: str, since: str, until: str, limit: int) -> list[dict]:
    """Fetch merged PRs for a repo within the date window."""
    collected = []
    page = 1

    since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
    until_dt = datetime.fromisoformat(until).replace(tzinfo=timezone.utc)

    print(f"  Fetching PRs from {repo} ...")

    while len(collected) < limit:
        resp = client.get(
            f"{GITHUB_API}/repos/{repo}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": 100,
                "page": page,
            },
        )
        resp.raise_for_status()
        prs = resp.json()
        if not prs:
            break

        for pr in prs:
            # Only merged PRs
            if not pr.get("merged_at"):
                continue
            merged_at = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
            if merged_at < since_dt:
                return collected  # PRs are sorted newest-first, done
            if merged_at > until_dt:
                continue
            # Must have changed files
            files_resp = client.get(
                f"{GITHUB_API}/repos/{repo}/pulls/{pr['number']}/files"
            )
            files_resp.raise_for_status()
            files = files_resp.json()
            if not files:
                continue

            collected.append({
                "id": f"{repo}#{pr['number']}",
                "repo": repo,
                "pr_number": pr["number"],
                "title": pr["title"],
                "author": pr["user"]["login"],
                "merged_at": pr["merged_at"],
                "base_sha": pr["base"]["sha"],
                "head_sha": pr["head"]["sha"],
                "merge_commit_sha": pr.get("merge_commit_sha"),
                "files_changed": len(files),
                "additions": pr.get("additions", 0),
                "deletions": pr.get("deletions", 0),
                "url": pr["html_url"],
                # Ground truth filled in by 02_label_dataset.py
                "ground_truth": None,
                "label_method": None,
            })

            if len(collected) >= limit:
                break

        page += 1
        time.sleep(0.5)  # respect rate limits

    return collected


def main():
    parser = argparse.ArgumentParser(description="Collect PR dataset for evaluation")
    parser.add_argument("--repos", nargs="+", required=True,
                        help="GitHub repos in owner/repo format")
    parser.add_argument("--since", default="2026-01-01",
                        help="Start date (ISO format, default 2026-01-01)")
    parser.add_argument("--until", default="2026-06-30",
                        help="End date (ISO format, default 2026-06-30)")
    parser.add_argument("--per-repo", type=int, default=40,
                        help="Max PRs per repo (default 40)")
    parser.add_argument("--out", default="eval/data/dataset.json",
                        help="Output file path")
    args = parser.parse_args()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    all_prs = []
    with httpx.Client(headers=github_headers(), timeout=30) as client:
        for repo in args.repos:
            prs = get_prs(client, repo, args.since, args.until, args.per_repo)
            print(f"  ✓ {repo}: {len(prs)} PRs collected")
            all_prs.extend(prs)

    # Write dataset
    dataset = {
        "meta": {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "repos": args.repos,
            "since": args.since,
            "until": args.until,
            "total_prs": len(all_prs),
        },
        "prs": all_prs,
    }
    with open(args.out, "w") as f:
        json.dump(dataset, f, indent=2)

    print(f"\n✓ Dataset saved: {args.out}  ({len(all_prs)} PRs total)")


if __name__ == "__main__":
    main()
