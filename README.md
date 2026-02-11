# PinchBench - OpenClaw Agent Benchmarking System

A benchmarking system for evaluating OpenClaw agents across various tasks.

## Overview

PinchBench loads task definitions from the `tasks/` directory and provides a framework for creating and benchmarking OpenClaw agents. Each task includes:

- Task metadata (ID, name, category, timeout)
- User prompt
- Expected behavior description
- Grading criteria
- Automated grading functions (where applicable)
- LLM judge rubrics (where applicable)

## Quick Start

Run the benchmark script using `uv` (no virtual environment setup needed):

```bash
uv run benchmark.py
```

This will:

1. Load all tasks from the `tasks/` directory
2. Display a summary of loaded tasks
3. Demonstrate agent scaffolding (execution not yet implemented)

## Script Features

### Task Loading

The [`TaskLoader`](benchmark.py:89) class handles:

- Reading task markdown files
- Parsing YAML frontmatter
- Extracting task sections (Prompt, Expected Behavior, Grading Criteria, etc.)
- Creating structured [`Task`](benchmark.py:31) objects

### Agent Scaffolding

The [`OpenClawAgent`](benchmark.py:189) class provides:

- Agent initialization with configuration
- Task execution interface (to be implemented)
- Result tracking structure

### Benchmark Runner

The [`BenchmarkRunner`](benchmark.py:217) class orchestrates:

- Task loading and management
- Agent creation
- Benchmark execution across tasks
- Result aggregation

## Task Structure

Tasks are defined in markdown files with YAML frontmatter:

````markdown
---
id: task_01_example
name: Example Task
category: example
grading_type: automated
timeout_seconds: 120
workspace_files: []
---

## Prompt

[User-facing task prompt]

## Expected Behavior

[Description of expected agent behavior]

## Grading Criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Automated Checks

```python
def grade(transcript: list, workspace_path: str) -> dict:
    # Grading logic
    return scores
```
````

````

## Current Tasks

The system includes 10 benchmark tasks:

1. **task_01_calendar** - Calendar Event Creation
2. **task_02_stock** - Stock Price Research
3. **task_03_blog** - Blog Post Writing
4. **task_04_weather** - Weather Script Creation
5. **task_05_summary** - Document Summarization
6. **task_06_events** - Tech Conference Research
7. **task_07_email** - Professional Email Drafting
8. **task_08_memory** - Memory Retrieval from Context
9. **task_09_files** - File Structure Creation
10. **task_10_workflow** - Multi-step API Workflow

## Logging

The script uses Python's built-in logging with:
- Console output (INFO level)
- File output to `benchmark.log`
- Structured log messages for debugging

## Dependencies

- Python >= 3.10
- PyYAML >= 6.0.1

Dependencies are automatically managed by `uv` using inline script metadata.

## Next Steps

The current implementation provides:
- ✅ Task loading and parsing
- ✅ Agent scaffolding
- ✅ Logging infrastructure
- ⏳ Agent execution (to be implemented)
- ⏳ Grading system (to be implemented)
- ⏳ Result reporting (to be implemented)

## Development

To extend the system:

1. **Add new tasks**: Create markdown files in `tasks/` following the template
2. **Implement agent execution**: Complete the [`execute_task`](benchmark.py:199) method in [`OpenClawAgent`](benchmark.py:189)
3. **Add grading**: Implement the grading system to evaluate agent performance
4. **Create reports**: Build result aggregation and reporting functionality

## Usage Examples

### Load and display all tasks

```python
from pathlib import Path
from benchmark import BenchmarkRunner

runner = BenchmarkRunner(Path("tasks"))
runner.load_tasks()
runner.print_task_summary()
````

### Create an agent

```python
agent = runner.create_agent(
    agent_id="my_agent_v1",
    config={
        'model': 'claude-3-opus',
        'temperature': 0.7,
    }
)
```

### Run benchmark (when implemented)

```python
# Run on all tasks
results = runner.run_benchmark(agent)

# Run on specific tasks
results = runner.run_benchmark(
    agent,
    task_ids=['task_01_calendar', 'task_02_stock']
)
```

## License

See project license file.
