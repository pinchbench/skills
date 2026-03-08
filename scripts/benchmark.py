#!/usr/bin/env python3
"""
PinchBench - OpenClaw Agent Benchmarking System

This script orchestrates benchmarking of OpenClaw agents using tasks loaded
from the tasks/ directory.
"""
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml>=6.0.1",
# ]
# ///

import argparse
import json
import logging
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from lib_agent import (
    cleanup_agent_sessions,
    ensure_agent_exists,
    ensure_model_available,
    execute_openclaw_task,
    normalize_model_id,
    slugify_model,
)
from lib_grading import DEFAULT_JUDGE_MODEL, grade_task
from lib_tasks import Task, TaskLoader


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("benchmark.log")],
)

logger = logging.getLogger("benchmark")


class OpenClawAgent:
    """Scaffold for OpenClaw agent creation and execution."""

    def __init__(self, agent_id: str, config: Optional[Dict[str, Any]] = None):
        self.agent_id = agent_id
        self.config = config or {}
        logger.info(f"Initialized OpenClawAgent: {agent_id}")

    def execute_task(self, task: Task, simulate: bool = False) -> Dict[str, Any]:
        """
        Execute a task with this agent.

        Args:
            task: The Task object to execute
            simulate: If True, simulates execution for demonstration

        Returns:
            Dictionary containing execution results
        """
        if simulate:
            logger.info("Simulate flag no longer supported for execute_task")
        raise NotImplementedError("Use execute_openclaw_task helper for real runs")


class BenchmarkRunner:
    """Orchestrates benchmark execution across tasks and agents."""

    def __init__(self, tasks_dir: Path):
        self.task_loader = TaskLoader(tasks_dir)
        self.tasks: List[Task] = []
        self.agents: List[OpenClawAgent] = []
        logger.info("Initialized BenchmarkRunner")

    def load_tasks(self) -> None:
        """Load all tasks from the tasks directory."""
        logger.info("Loading tasks...")
        self.tasks = self.task_loader.load_all_tasks()
        logger.info(f"Loaded {len(self.tasks)} tasks")

    def create_agent(self, agent_id: str, config: Optional[Dict[str, Any]] = None) -> OpenClawAgent:
        """
        Create a new OpenClaw agent for benchmarking.

        Args:
            agent_id: Unique identifier for the agent
            config: Optional configuration dictionary

        Returns:
            OpenClawAgent instance
        """
        logger.info(f"Creating agent: {agent_id}")
        agent = OpenClawAgent(agent_id, config)
        self.agents.append(agent)
        return agent

    def run_benchmark(
        self, agent: OpenClawAgent, task_ids: Optional[List[str]] = None, simulate: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Run benchmark for an agent on specified tasks.

        Args:
            agent: The OpenClawAgent to benchmark
            task_ids: Optional list of task IDs to run. If None, runs all tasks.
            simulate: If True, simulates execution for demonstration

        Returns:
            List of result dictionaries
        """
        # Filter tasks if specific IDs provided
        if task_ids:
            tasks_to_run = [t for t in self.tasks if t.task_id in task_ids]
            logger.info(f"🎯 Running benchmark on {len(tasks_to_run)} specified tasks")
        else:
            tasks_to_run = self.tasks
            logger.info(f"🎯 Running benchmark on all {len(tasks_to_run)} tasks")

        results = []
        for i, task in enumerate(tasks_to_run, 1):
            logger.info(f"\n{'=' * 80}")
            logger.info(f"📋 Task {i}/{len(tasks_to_run)}")
            logger.info(f"{'=' * 80}")
            result = agent.execute_task(task, simulate=simulate)
            results.append(result)

        logger.info(f"\n{'=' * 80}")
        logger.info(f"✨ Benchmark complete! Executed {len(results)} tasks")
        logger.info(f"{'=' * 80}")

        # Print summary
        total_time = sum(r["execution_time"] for r in results)
        logger.info(f"\n📊 BENCHMARK SUMMARY")
        logger.info(f"   Agent: {agent.agent_id}")
        logger.info(f"   Tasks completed: {len(results)}")
        logger.info(f"   Total execution time: {total_time:.2f}s")
        logger.info(f"   Average time per task: {total_time / len(results):.2f}s")

        return results

    def print_task_summary(self) -> None:
        """Print a summary of all loaded tasks."""
        if not self.tasks:
            logger.warning("No tasks loaded")
            return

        print("\n" + "=" * 80)
        print(f"LOADED TASKS SUMMARY ({len(self.tasks)} tasks)")
        print("=" * 80)

        for task in self.tasks:
            print(f"\n[{task.task_id}] {task.name}")
            print(f"  Category: {task.category}")
            print(f"  Grading: {task.grading_type}")
            print(f"  Timeout: {task.timeout_seconds}s")
            print(f"  Criteria: {len(task.grading_criteria)} items")
            print(
                f"  Prompt: {task.prompt[:100]}..."
                if len(task.prompt) > 100
                else f"  Prompt: {task.prompt}"
            )

        print("\n" + "=" * 80)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PinchBench OpenClaw Benchmark Runner")
    parser.add_argument(
        "--model",
        required=False,
        help="Model identifier (e.g., anthropic/claude-sonnet-4)",
    )
    parser.add_argument(
        "--suite",
        default="all",
        help='Tasks to run: "all", "automated-only", or comma-separated IDs',
    )
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Results directory",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Request a new API token and save it to local config",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip uploading to server",
    )
    parser.add_argument(
        "--upload",
        type=str,
        metavar="RESULTS_JSON",
        help="Upload a previous run's results JSON and exit (skips benchmarking)",
    )
    parser.add_argument(
        "--timeout-multiplier",
        type=float,
        default=1.0,
        help="Scale all task timeouts",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of runs per task for averaging",
    )
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help=(
            "Judge model identifier (provider/model, e.g. anthropic/claude-opus-4.5). "
            "Must be available in the local OpenClaw model catalog."
        ),
    )
    parser.add_argument(
        "--thinking",
        default=None,
        help=(
            "Thinking level for benchmark model turns. "
            "Allowed: off|minimal|low|medium|high|xhigh|adaptive"
        ),
    )
    parser.add_argument(
        "--judge-only",
        type=str,
        metavar="EXECUTION_JSON",
        help=(
            "Skip benchmark execution and re-run grading from an existing results/checkpoint JSON. "
            "Useful for rejudging with a different --judge-model."
        ),
    )
    parser.add_argument(
        "--clear-sessions",
        action="store_true",
        help=(
            "Clear stored agent/judge session transcripts before each turn. "
            "Default is to preserve sessions for audit/resume workflows."
        ),
    )
    return parser.parse_args()


def _select_task_ids(tasks: List[Task], suite: str) -> Optional[List[str]]:
    if suite == "all":
        return None
    if suite == "automated-only":
        return [task.task_id for task in tasks if task.grading_type == "automated"]
    return [task_id.strip() for task_id in suite.split(",") if task_id.strip()]


def _next_run_id(run_root: Path) -> str:
    run_root.mkdir(parents=True, exist_ok=True)
    existing = []
    for entry in run_root.iterdir():
        if entry.is_dir() and entry.name.isdigit():
            existing.append(int(entry.name))
    next_id = (max(existing) + 1) if existing else 1
    return f"{next_id:04d}"


def _load_ascii_art(script_dir: Path, filename: str) -> str | None:
    """Load ASCII art from a local file if available."""
    art_path = script_dir / filename
    try:
        return art_path.read_text(encoding="utf-8").rstrip("\n")
    except FileNotFoundError:
        return None


def _supports_truecolor() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _get_git_version(script_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            cwd=script_dir,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _build_task_payload(
    *,
    result: Dict[str, Any],
    grading: Optional[Dict[str, Any]],
    frontmatter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "agent_id": result.get("agent_id"),
        "task_id": result.get("task_id"),
        "status": result.get("status"),
        "requested_model": result.get("requested_model"),
        "runtime_model": result.get("runtime_model"),
        "timed_out": result.get("timed_out", False),
        "execution_time": result.get("execution_time", 0.0),
        "exit_code": result.get("exit_code"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "transcript_length": len(result.get("transcript", [])),
        "transcript": result.get("transcript", []),
        "usage": result.get("usage", {}),
        "workspace": result.get("workspace", ""),
        "grading": grading,
        "frontmatter": frontmatter or result.get("frontmatter", {}),
    }
    return payload


def _write_aggregate(
    *,
    output_path: Path,
    benchmark_model: Optional[str],
    judge_model: str,
    thinking_level: Optional[str],
    benchmark_version: str,
    run_id: str,
    suite: str,
    runs_per_task: int,
    results: List[Dict[str, Any]],
    grades_by_task_id: Dict[str, Any],
    tasks_by_id: Dict[str, Task],
    mode: str = "benchmark",
    source_results: Optional[str] = None,
) -> None:
    tasks_payload = []
    for result in results:
        task_id = result.get("task_id")
        task_obj = tasks_by_id.get(task_id) if task_id else None
        grading = grades_by_task_id.get(task_id)
        tasks_payload.append(
            _build_task_payload(
                result=result,
                grading=grading,
                frontmatter=task_obj.frontmatter if task_obj else result.get("frontmatter", {}),
            )
        )

    aggregate = {
        "mode": mode,
        "source_results": source_results,
        "model": benchmark_model,
        "judge_model": judge_model,
        "thinking": thinking_level,
        "benchmark_version": benchmark_version,
        "run_id": run_id,
        "timestamp": time.time(),
        "suite": suite,
        "runs_per_task": runs_per_task,
        "tasks": tasks_payload,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")


def _colorize_gradient(ascii_art: str) -> str:
    if not _supports_truecolor():
        return ascii_art
    lines = ascii_art.splitlines()
    if not lines:
        return ascii_art
    last_index = max(len(lines) - 1, 1)
    colored_lines = []
    for idx, line in enumerate(lines):
        t = idx / last_index
        green_blue = int(255 * (1 - t))
        colored_lines.append(f"\x1b[38;2;255;{green_blue};{green_blue}m{line}\x1b[0m")
    return "\n".join(colored_lines)


def main():
    """Main entry point for the benchmark script."""
    # Determine tasks directory
    script_dir = Path(__file__).parent
    skill_root = script_dir.parent  # Parent of scripts/ is the skill root
    tasks_dir = skill_root / "tasks"

    logger.info("🦞🦀🦐 PinchBench - OpenClaw Benchmarking")
    ascii_crab = _load_ascii_art(skill_root, "crab.txt")
    if ascii_crab:
        print("\n" + _colorize_gradient(ascii_crab) + "\n")
    else:
        print("\n" + "🦀 " * 30)
        print("🦀 " * 30 + "\n")
    logger.info("🦞🦀🦐 Starting PinchBench 🦐🦀🦞")
    time.sleep(5)

    if not tasks_dir.exists():
        logger.error(f"❌ Tasks directory not found: {tasks_dir}")
        sys.exit(1)

    args = _parse_args()
    if not args.model and not args.register and not args.upload and not args.judge_only:
        logger.error("Missing required argument: --model (unless using --register, --upload, or --judge-only)")
        sys.exit(2)

    if args.register:
        try:
            from lib_upload import UploadError, register_token, save_token_config

            token, claim_url = register_token()
            config_path = save_token_config(token, claim_url)
            logger.info("Saved token to %s", config_path)
            if claim_url:
                logger.info("Claim URL: %s", claim_url)
            return
        except UploadError as exc:
            logger.error("Registration failed: %s", exc)
            sys.exit(1)

    if args.upload:
        results_path = Path(args.upload)
        if not results_path.exists():
            logger.error("Results file not found: %s", results_path)
            sys.exit(1)
        try:
            from lib_upload import UploadError, upload_results

            result = upload_results(results_path)
            if result.rank is not None:
                logger.info("Uploaded to leaderboard: rank #%s", result.rank)
            if result.leaderboard_url:
                logger.info("View at: %s", result.leaderboard_url)
            logger.info("Upload complete.")
            return
        except UploadError as exc:
            logger.error("Upload failed: %s", exc)
            sys.exit(1)

    logger.info("🔧 Initializing BenchmarkRunner...")
    runner = BenchmarkRunner(tasks_dir)

    logger.info("📂 Loading tasks from directory...")
    runner.load_tasks()

    skill_dir = skill_root

    if args.judge_only:
        source_path = Path(args.judge_only)
        if not source_path.exists():
            logger.error("--judge-only file not found: %s", source_path)
            sys.exit(2)
        try:
            source_payload = json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse --judge-only JSON: %s", exc)
            sys.exit(2)

        source_tasks_raw = source_payload.get("tasks", []) if isinstance(source_payload, dict) else []
        if not isinstance(source_tasks_raw, list) or not source_tasks_raw:
            logger.error("--judge-only JSON has no tasks to grade")
            sys.exit(2)

        try:
            judge_model = ensure_model_available(normalize_model_id(args.judge_model), role="Judge")
        except (ValueError, RuntimeError) as exc:
            logger.error(str(exc))
            sys.exit(2)

        source_tasks: List[Dict[str, Any]] = []
        source_by_id: Dict[str, Dict[str, Any]] = {}
        for task_entry in source_tasks_raw:
            if not isinstance(task_entry, dict):
                continue
            task_id = task_entry.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            source_tasks.append(task_entry)
            if task_id not in source_by_id:
                source_by_id[task_id] = task_entry

        requested_task_ids = _select_task_ids(runner.tasks, args.suite)
        if requested_task_ids is None:
            target_task_ids = [task.get("task_id") for task in source_tasks if task.get("task_id")]
        else:
            missing_task_ids = [task_id for task_id in requested_task_ids if task_id not in source_by_id]
            if missing_task_ids:
                logger.error(
                    "--judge-only input is missing requested task IDs: %s",
                    ", ".join(missing_task_ids),
                )
                sys.exit(2)
            target_task_ids = requested_task_ids

        if not target_task_ids:
            logger.error("No tasks selected for --judge-only run")
            sys.exit(2)

        tasks_by_id = {task.task_id: task for task in runner.tasks}
        run_root = Path("/tmp/pinchbench")
        run_id = _next_run_id(run_root)

        benchmark_model = source_payload.get("model") if isinstance(source_payload, dict) else None
        if benchmark_model is not None and not isinstance(benchmark_model, str):
            benchmark_model = None
        thinking_level = source_payload.get("thinking") if isinstance(source_payload, dict) else None
        if thinking_level is not None and not isinstance(thinking_level, str):
            thinking_level = None

        results: List[Dict[str, Any]] = []
        grades_by_task_id: Dict[str, Any] = {}

        for i, task_id in enumerate(target_task_ids, 1):
            task = tasks_by_id.get(task_id)
            if task is None:
                logger.error("Task id %s not found in local task set", task_id)
                sys.exit(2)

            source_task = source_by_id[task_id]
            if source_task.get("status") != "success":
                logger.error(
                    "Cannot judge task %s because execution status is %s (must be success)",
                    task_id,
                    source_task.get("status"),
                )
                sys.exit(1)

            transcript = source_task.get("transcript")
            if not isinstance(transcript, list):
                logger.error(
                    "Task %s in --judge-only input has no transcript array. "
                    "Use a results/checkpoint file produced by this updated benchmark.",
                    task_id,
                )
                sys.exit(2)

            execution_result = {
                "agent_id": source_task.get("agent_id", ""),
                "task_id": task_id,
                "status": source_task.get("status", "success"),
                "requested_model": source_task.get("requested_model"),
                "runtime_model": source_task.get("runtime_model"),
                "transcript": transcript,
                "usage": source_task.get("usage", {}),
                "workspace": source_task.get("workspace", ""),
                "exit_code": source_task.get("exit_code", 0),
                "timed_out": bool(source_task.get("timed_out", False)),
                "execution_time": float(source_task.get("execution_time", 0.0)),
                "stdout": source_task.get("stdout", ""),
                "stderr": source_task.get("stderr", ""),
                "frontmatter": source_task.get("frontmatter", {}),
            }

            logger.info("\n%s", "=" * 80)
            logger.info("📋 Judge-only task %s/%s: %s", i, len(target_task_ids), task_id)
            logger.info("%s", "=" * 80)

            try:
                grade = grade_task(
                    task=task,
                    execution_result=execution_result,
                    skill_dir=skill_dir,
                    judge_model=judge_model,
                    clear_judge_sessions=args.clear_sessions,
                )
            except Exception as exc:
                logger.error("Judge-only grading failed for %s: %s", task_id, exc)
                sys.exit(1)

            results.append(execution_result)
            grades_by_task_id[task_id] = {
                "runs": [grade.to_dict()],
                "mean": grade.score,
                "std": 0.0,
                "min": grade.score,
                "max": grade.score,
            }

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        model_slug = slugify_model(benchmark_model or "judge-only")
        output_path = output_dir / f"{run_id}_{model_slug}_judge-only.json"

        _write_aggregate(
            output_path=output_path,
            benchmark_model=benchmark_model,
            judge_model=judge_model,
            thinking_level=thinking_level,
            benchmark_version=_get_git_version(skill_root),
            run_id=run_id,
            suite=args.suite,
            runs_per_task=1,
            results=results,
            grades_by_task_id=grades_by_task_id,
            tasks_by_id=tasks_by_id,
            mode="judge-only",
            source_results=str(source_path.resolve()),
        )

        logger.info("Saved judge-only results to %s", output_path)
        if args.no_upload:
            logger.info("Skipping upload (--no-upload)")
        else:
            try:
                from lib_upload import UploadError, upload_results

                uploaded = upload_results(output_path)
                if uploaded.rank is not None:
                    logger.info("Uploaded to leaderboard: rank #%s", uploaded.rank)
                if uploaded.leaderboard_url:
                    logger.info("View at: %s", uploaded.leaderboard_url)
            except UploadError as exc:
                logger.warning("Upload failed: %s", exc)
        return

    try:
        benchmark_model = ensure_model_available(args.model, role="Benchmark")
        judge_model = normalize_model_id(args.judge_model)
    except (ValueError, RuntimeError) as exc:
        logger.error(str(exc))
        sys.exit(2)

    allowed_thinking_levels = {"off", "minimal", "low", "medium", "high", "xhigh", "adaptive"}
    thinking_level: Optional[str] = None
    if args.thinking:
        parsed_levels = [level.strip().lower() for level in args.thinking.split(",") if level.strip()]
        invalid_levels = [level for level in parsed_levels if level not in allowed_thinking_levels]
        if invalid_levels:
            logger.error(
                "Invalid --thinking value(s): %s. Allowed values: %s",
                ", ".join(invalid_levels),
                ", ".join(sorted(allowed_thinking_levels)),
            )
            sys.exit(2)
        if not parsed_levels:
            logger.error("--thinking was provided but no valid thinking levels were parsed")
            sys.exit(2)
        if len(parsed_levels) > 1:
            logger.error(
                "Multiple thinking levels in one run are not supported in this branch. "
                "Run separate benchmarks per level (e.g., --thinking off, then --thinking low)."
            )
            sys.exit(2)
        thinking_level = parsed_levels[0]

    model_slug = slugify_model(benchmark_model)
    run_root = Path("/tmp/pinchbench")
    run_id = _next_run_id(run_root)
    skill_dir = skill_root
    agent_id = f"bench-{model_slug}"
    # Use a shared workspace for the agent - we'll copy fixtures per task
    agent_workspace = Path(f"/tmp/pinchbench/{run_id}/agent_workspace")

    ensure_agent_exists(agent_id, benchmark_model, agent_workspace)
    if args.clear_sessions:
        cleanup_agent_sessions(agent_id)

    task_ids = _select_task_ids(runner.tasks, args.suite)
    results = []
    grades_by_task_id = {}

    tasks_to_run = runner.tasks
    if task_ids is not None:
        tasks_to_run = [task for task in runner.tasks if task.task_id in task_ids]
    tasks_by_id = {task.task_id: task for task in tasks_to_run}

    if any(task.grading_type in ("llm_judge", "hybrid") for task in tasks_to_run):
        try:
            judge_model = ensure_model_available(judge_model, role="Judge")
        except (ValueError, RuntimeError) as exc:
            logger.error(str(exc))
            sys.exit(2)

    runs_per_task = max(1, args.runs)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / f"{run_id}_{model_slug}.checkpoint.json"

    def _flush_checkpoint() -> None:
        _write_aggregate(
            output_path=checkpoint_path,
            benchmark_model=benchmark_model,
            judge_model=judge_model,
            thinking_level=thinking_level,
            benchmark_version=_get_git_version(skill_root),
            run_id=run_id,
            suite=args.suite,
            runs_per_task=runs_per_task,
            results=results,
            grades_by_task_id=grades_by_task_id,
            tasks_by_id=tasks_by_id,
            mode="checkpoint",
        )

    for i, task in enumerate(tasks_to_run, 1):
        task_grades = []
        for run_index in range(runs_per_task):
            logger.info("\n%s", "=" * 80)
            logger.info(
                "📋 Task %s/%s (Run %s/%s)",
                i,
                len(tasks_to_run),
                run_index + 1,
                runs_per_task,
            )
            logger.info("%s", "=" * 80)
            try:
                result = execute_openclaw_task(
                    task=task,
                    agent_id=agent_id,
                    model_id=benchmark_model,
                    run_id=f"{run_id}-{run_index + 1}",
                    timeout_multiplier=args.timeout_multiplier,
                    skill_dir=skill_dir,
                    thinking_level=thinking_level,
                    clear_sessions=args.clear_sessions,
                )
            except Exception as exc:
                logger.error("Task execution failed for %s: %s", task.task_id, exc)
                sys.exit(1)

            results.append(result)
            _flush_checkpoint()

            if result.get("status") != "success":
                logger.error(
                    "Task %s failed determinism checks or execution. requested_model=%s runtime_model=%s stderr=%s",
                    task.task_id,
                    result.get("requested_model"),
                    result.get("runtime_model"),
                    result.get("stderr"),
                )
                sys.exit(1)

            try:
                grade = grade_task(
                    task=task,
                    execution_result=result,
                    skill_dir=skill_dir,
                    judge_model=judge_model,
                    clear_judge_sessions=args.clear_sessions,
                )
            except Exception as exc:
                logger.error("Task grading failed for %s: %s", task.task_id, exc)
                _flush_checkpoint()
                sys.exit(1)

            task_grades.append(grade)

        task_scores = [grade.score for grade in task_grades]
        grades_by_task_id[task.task_id] = {
            "runs": [grade.to_dict() for grade in task_grades],
            "mean": statistics.mean(task_scores),
            "std": statistics.stdev(task_scores) if len(task_scores) > 1 else 0.0,
            "min": min(task_scores),
            "max": max(task_scores),
        }
        _flush_checkpoint()

    output_path = output_dir / f"{run_id}_{model_slug}.json"
    _write_aggregate(
        output_path=output_path,
        benchmark_model=benchmark_model,
        judge_model=judge_model,
        thinking_level=thinking_level,
        benchmark_version=_get_git_version(skill_root),
        run_id=run_id,
        suite=args.suite,
        runs_per_task=runs_per_task,
        results=results,
        grades_by_task_id=grades_by_task_id,
        tasks_by_id=tasks_by_id,
        mode="benchmark",
    )

    logger.info("Saved results to %s", output_path)
    logger.info("Checkpoint file: %s", checkpoint_path)
    if args.no_upload:
        logger.info("Skipping upload (--no-upload)")
    else:
        try:
            from lib_upload import UploadError, upload_results

            uploaded = upload_results(output_path)
            if uploaded.rank is not None:
                logger.info("Uploaded to leaderboard: rank #%s", uploaded.rank)
            if uploaded.leaderboard_url:
                logger.info("View at: %s", uploaded.leaderboard_url)
        except UploadError as exc:
            logger.warning("Upload failed: %s", exc)


if __name__ == "__main__":
    main()
