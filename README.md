# PinchBench 🦀

**A benchmark for testing your OpenClaw agents!**

PinchBench helps you evaluate how well your OpenClaw agent and selected model can handle real-world tasks like calendar management, research, file operations, and multi-step workflows. It's designed to be easy to run and easy to extend.

![PinchBench terminal output](./pinchbench.png)

## Quick Start

### Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** - Fast Python package manager
- **An OpenClaw instance** - You'll need access to an OpenClaw server to run agents

### Run the Benchmark

```bash
# Run with your model of choice
uv run benchmark.py --model anthropic/claude-sonnet-4

# Run specific tasks
uv run benchmark.py --model anthropic/claude-sonnet-4 --suite task_01_calendar,task_02_stock

# Run only tasks with automated grading
uv run benchmark.py --model anthropic/claude-sonnet-4 --suite automated-only
```

That's it! The benchmark will:

1. Load all tasks from the `tasks/` directory
2. Run your agent through each task
3. Grade the results automatically (where possible)
4. Save results to `/tmp/pinchbench/`

## Command Line Options

| Option                 | Description                                                   |
| ---------------------- | ------------------------------------------------------------- |
| `--model`              | Model identifier (e.g., `anthropic/claude-sonnet-4`)          |
| `--suite`              | Tasks to run: `all`, `automated-only`, or comma-separated IDs |
| `--output-dir`         | Where to save results (default: `results/`)                   |
| `--timeout-multiplier` | Scale task timeouts (useful for slower models)                |
| `--runs`               | Number of runs per task for averaging                         |
| `--no-upload`          | Skip uploading results to a leaderboard                       |

## What Gets Tested

PinchBench includes 11 tasks that cover common agent capabilities:

| Task               | Category     | Description                              |
| ------------------ | ------------ | ---------------------------------------- |
| `task_00_sanity`   | Basic        | Simple verification that the agent works |
| `task_01_calendar` | Productivity | Calendar event creation                  |
| `task_02_stock`    | Research     | Stock price lookup                       |
| `task_03_blog`     | Writing      | Blog post creation                       |
| `task_04_weather`  | Coding       | Weather script creation                  |
| `task_05_summary`  | Analysis     | Document summarization                   |
| `task_06_events`   | Research     | Tech conference research                 |
| `task_07_email`    | Writing      | Professional email drafting              |
| `task_08_memory`   | Memory       | Context retrieval                        |
| `task_09_files`    | Files        | File structure creation                  |
| `task_10_workflow` | Integration  | Multi-step API workflow                  |

## Understanding Results

Results are saved as JSON files containing:

```json
{
  "tasks": [
    {
      "task_id": "task_01_calendar",
      "grading": {
        "passed": true,
        "score": 1.0
      },
      "execution_time": 45.2
    }
  ]
}
```

### Quick Analysis with jq

```bash
# List all task scores
jq '.tasks[] | {task_id, score: .grading.score}' results.json

# Show failed tasks
jq '.tasks[] | select(.grading.passed == false)' results.json

# Calculate average score
jq '{average_score: ([.tasks[].grading.score] | add / length)}' results.json
```

## Adding Your Own Tasks

Create a new markdown file in `tasks/` following this structure:

````markdown
---
id: task_my_task
name: My Custom Task
category: custom
grading_type: automated
timeout_seconds: 120
workspace_files: []
---

## Prompt

[What the user asks the agent to do]

## Expected Behavior

[What a successful agent should do]

## Grading Criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Automated Checks

```python
def grade(transcript: list, workspace_path: str) -> dict:
    # Your grading logic
    return {"score": 1.0, "passed": True}
```
````

````

See [`tasks/TASK_TEMPLATE.md`](tasks/TASK_TEMPLATE.md) for a complete template.

## Connecting to Your OpenClaw Instance

PinchBench expects your OpenClaw instance to be accessible via SSH. The connection is configured through environment variables or a config file. Check your OpenClaw documentation for setup details.

## Contributing

We welcome contributions! Here's how to help:

1. **Add tasks** - Create new benchmark tasks in `tasks/`
2. **Improve grading** - Make our automated checks more robust
3. **Fix bugs** - Check the issues tab
4. **Documentation** - Help make this README even better

### Development Setup

```bash
# Clone the repo
git clone https://github.com/your-org/pinchbench.git
cd pinchbench

# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest
````

## License

This project is open source! See the [LICENSE](LICENSE) file for details.

## Getting Help

- **Issues** - File a bug or request a feature
- **Discussions** - Ask questions and share ideas
- **Documentation** - Check the `plans/` directory for design docs

---

Happy benchmarking! 🦀🦞🦐
