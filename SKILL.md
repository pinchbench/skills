---
name: pinchbench
description: Run PinchBench benchmarks to evaluate OpenClaw agent performance across real-world tasks. Use when testing model capabilities, comparing models, submitting benchmark results to the leaderboard, or checking how well your OpenClaw setup handles calendar, email, research, coding, and multi-step workflows.
metadata:
  author: pinchbench
  version: "1.0.0"
  homepage: https://pinchbench.com
  repository: https://github.com/pinchbench/skill
---

# PinchBench Benchmark Skill

PinchBench measures how well LLM models perform as the brain of an OpenClaw agent. Results are collected on a public leaderboard at [pinchbench.com](https://pinchbench.com).

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenClaw instance (this agent)

## Quick Start

```bash
cd <skill_directory>

# Run benchmark with a specific model
uv run benchmark.py --model anthropic/claude-sonnet-4

# Run only automated tasks (faster)
uv run benchmark.py --model anthropic/claude-sonnet-4 --suite automated-only

# Run specific tasks
uv run benchmark.py --model anthropic/claude-sonnet-4 --suite task_01_calendar,task_02_stock

# Skip uploading results
uv run benchmark.py --model anthropic/claude-sonnet-4 --no-upload
```

## Available Tasks (23)

| Task | Category | Description |
|------|----------|-------------|
| `task_00_sanity` | Basic | Verify agent works |
| `task_01_calendar` | Productivity | Calendar event creation |
| `task_02_stock` | Research | Stock price lookup |
| `task_03_blog` | Writing | Blog post creation |
| `task_04_weather` | Coding | Weather script |
| `task_05_summary` | Analysis | Document summarization |
| `task_06_events` | Research | Conference research |
| `task_07_email` | Writing | Email drafting |
| `task_08_memory` | Memory | Context retrieval |
| `task_09_files` | Files | File structure creation |
| `task_10_workflow` | Integration | Multi-step API workflow |
| `task_11_clawdhub` | Skills | ClawHub interaction |
| `task_12_skill_search` | Skills | Skill discovery |
| `task_13_image_gen` | Creative | Image generation |
| `task_14_humanizer` | Writing | Text humanization |
| `task_15_daily_summary` | Productivity | Daily digest |
| `task_16_email_triage` | Email | Inbox triage |
| `task_17_email_search` | Email | Email search |
| `task_18_market_research` | Research | Market analysis |
| `task_19_spreadsheet_summary` | Analysis | Spreadsheet analysis |
| `task_20_eli5_pdf_summary` | Analysis | PDF simplification |
| `task_21_openclaw_comprehension` | Knowledge | OpenClaw docs comprehension |
| `task_22_second_brain` | Memory | Knowledge management |

## Command Line Options

| Option | Description |
|--------|-------------|
| `--model` | Model identifier (e.g., `anthropic/claude-sonnet-4`) |
| `--suite` | `all`, `automated-only`, or comma-separated task IDs |
| `--output-dir` | Results directory (default: `results/`) |
| `--timeout-multiplier` | Scale task timeouts for slower models |
| `--runs` | Number of runs per task for averaging |
| `--no-upload` | Skip uploading to leaderboard |
| `--register` | Request new API token for submissions |
| `--upload FILE` | Upload previous results JSON |

## Token Registration

To submit results to the leaderboard:

```bash
# Register for an API token (one-time)
uv run benchmark.py --register

# Run benchmark (auto-uploads with token)
uv run benchmark.py --model anthropic/claude-sonnet-4
```

## Results

Results are saved as JSON in the output directory:

```bash
# View task scores
jq '.tasks[] | {task_id, score: .grading.mean}' results/0001_anthropic-claude-sonnet-4.json

# Show failed tasks
jq '.tasks[] | select(.grading.mean < 0.5)' results/*.json

# Calculate overall score
jq '{average: ([.tasks[].grading.mean] | add / length)}' results/*.json
```

## Adding Custom Tasks

Create a markdown file in `tasks/` following `TASK_TEMPLATE.md`. Each task needs:

- YAML frontmatter (id, name, category, grading_type, timeout)
- Prompt section
- Expected behavior
- Grading criteria
- Automated checks (Python grading function)

## Leaderboard

View results at [pinchbench.com](https://pinchbench.com). The leaderboard shows:

- Model rankings by overall score
- Per-task breakdowns
- Historical performance trends
