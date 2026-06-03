# Evaluation Harness — K11tech Agentic AI QA System

Four scripts that reproduce the empirical evaluation in the research paper.

## Scripts

| Script | Purpose |
|--------|---------|
| `01_collect_dataset.py` | Fetch merged PRs from GitHub repos into `data/dataset.json` |
| `02_label_dataset.py`   | Auto-label PRs as DEFECTIVE/CLEAN; export CSV for manual review |
| `03_run_evaluation.py`  | Replay each PR through the pipeline (parallel + serial modes) |
| `04_analyse_results.py` | Compute RQ1–RQ4 metrics; output `metrics.json` + `summary.csv` |

## Quick Start

```bash
# 1. Install dependencies
pip install httpx

# 2. Set your GitHub token
export GITHUB_TOKEN=ghp_...
export WEBHOOK_URL=http://localhost:9000   # your running pipeline

# 3. Collect PRs (40 per repo × 3 repos = 120 total)
python eval/01_collect_dataset.py \
  --repos owner/repo1 owner/repo2 owner/repo3 \
  --since 2026-01-01 --until 2026-06-30 \
  --per-repo 40 \
  --out eval/data/dataset.json

# 4. Auto-label + export CSV for second reviewer
python eval/02_label_dataset.py \
  --dataset eval/data/dataset.json \
  --out     eval/data/dataset_labelled.json \
  --csv     eval/data/manual_review.csv

# 4b. After second reviewer fills in reviewer_label column:
python eval/02_label_dataset.py \
  --dataset    eval/data/dataset.json \
  --import-csv eval/data/manual_review.csv \
  --out        eval/data/dataset_labelled.json

# 5. Start the pipeline webhook (separate terminal)
make run-webhook

# 6. Run evaluation (parallel + serial modes)
python eval/03_run_evaluation.py \
  --dataset eval/data/dataset_labelled.json \
  --out     eval/data/results.jsonl \
  --mode    both

# 7. Analyse results
python eval/04_analyse_results.py \
  --results eval/data/results.jsonl \
  --out-dir eval/data/
```

## Output Files

```
eval/data/
├── dataset.json            # Raw PR metadata
├── dataset_labelled.json   # PRs with ground truth labels
├── manual_review.csv       # For second reviewer (Cohen's κ)
├── results.jsonl           # One JSON line per pipeline run
├── metrics.json            # RQ1–RQ4 computed metrics
└── summary.csv             # Per-PR result table
```

## Research Questions

| RQ | Metric | How Measured |
|----|--------|-------------|
| RQ1 | Pipeline execution time | Wall-clock seconds, parallel vs serial |
| RQ2 | Defect detection F1 | TP/FP/FN/TN against ground truth labels |
| RQ3 | Production escapes | FN rate (approved PRs with DEFECTIVE label) |
| RQ4 | Agent portability | Manual substitution test (Jira→Linear, Postgres→MySQL) |

## Ground Truth Labelling

A PR is auto-labelled **DEFECTIVE** if any commit merged within 30 days of the PR matches:
- A revert commit targeting this PR number
- A commit message containing: `fix`, `bug`, `hotfix`, `revert`, `regression`, `incident`, `rollback`, `patch`

Otherwise it is labelled **CLEAN**.

A second reviewer manually audits each label. Cohen's κ is reported in the paper.
