"""
OpenClaw agent execution helpers for PinchBench.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from lib_tasks import Task


logger = logging.getLogger(__name__)


def slugify_model(model_id: str) -> str:
    return model_id.replace("/", "-").replace(".", "-")


def ensure_agent_exists(agent_id: str, model_id: str, workspace_dir: Path) -> bool:
    """Ensure the OpenClaw agent exists. Returns True if created."""
    workspace_dir.mkdir(parents=True, exist_ok=True)

    try:
        list_result = subprocess.run(
            ["openclaw", "agents", "list"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        logger.error("openclaw CLI not found while listing agents")
        return False

    if list_result.returncode == 0 and agent_id in list_result.stdout:
        logger.info("Agent %s already exists", agent_id)
        return False

    logger.info("Creating OpenClaw agent %s", agent_id)
    try:
        create_result = subprocess.run(
            [
                "openclaw",
                "agents",
                "add",
                agent_id,
                "--model",
                model_id,
                "--workspace",
                str(workspace_dir),
                "--non-interactive",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        logger.error("openclaw CLI not found while creating agent")
        return False

    if create_result.returncode != 0:
        logger.warning(
            "Agent creation returned %s: %s", create_result.returncode, create_result.stderr
        )
    return True


def prepare_task_workspace(skill_dir: Path, run_id: str, task: Task) -> Path:
    workspace = Path(f"/tmp/pinchbench/{run_id}/{task.task_id}")
    workspace.mkdir(parents=True, exist_ok=True)

    for file_spec in task.workspace_files:
        source = skill_dir / "fixtures" / file_spec["source"]
        dest = workspace / file_spec["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(source.read_bytes())
        except FileNotFoundError:
            logger.error("Workspace file not found: %s", source)
            raise

    return workspace


def _load_transcript(agent_id: str, session_id: str) -> List[Dict[str, Any]]:
    transcript_path = (
        Path.home()
        / ".openclaw"
        / "agents"
        / agent_id
        / "sessions"
        / f"{session_id}.jsonl"
    )
    for attempt in range(3):
        if transcript_path.exists():
            break
        if attempt < 2:
            time.sleep(0.5)
    if not transcript_path.exists():
        logger.warning("Transcript missing at %s", transcript_path)
        return []

    transcript: List[Dict[str, Any]] = []
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            transcript.append(json.loads(line))
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse transcript line: %s", exc)
            transcript.append({"raw": line, "parse_error": str(exc)})
    return transcript


def execute_openclaw_task(
    *,
    task: Task,
    agent_id: str,
    model_slug: str,
    run_id: str,
    timeout_multiplier: float,
    skill_dir: Path,
) -> Dict[str, Any]:
    logger.info("🤖 Agent [%s] starting task: %s", agent_id, task.task_id)
    logger.info("   Task: %s", task.name)
    logger.info("   Category: %s", task.category)

    start_time = time.time()
    workspace = prepare_task_workspace(skill_dir, run_id, task)
    session_id = f"{task.task_id}_{int(time.time() * 1000)}"
    timeout_seconds = task.timeout_seconds * timeout_multiplier
    stdout = ""
    stderr = ""
    exit_code = -1
    timed_out = False

    try:
        result = subprocess.run(
            [
                "openclaw",
                "agent",
                "--agent",
                f"bench-{model_slug}",
                "--session-id",
                session_id,
                "--message",
                task.prompt,
            ],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=timeout_seconds,
            check=False,
        )
        stdout = result.stdout
        stderr = result.stderr
        exit_code = result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    except FileNotFoundError as exc:
        stderr = f"openclaw command not found: {exc}"

    transcript = _load_transcript(agent_id, session_id)
    execution_time = time.time() - start_time

    status = "success"
    if timed_out:
        status = "timeout"
    if not transcript:
        status = "error"
    if exit_code not in (0, -1) and not timed_out:
        status = "error"
    if stderr and "openclaw command not found" in str(stderr):
        status = "error"

    return {
        "agent_id": agent_id,
        "task_id": task.task_id,
        "status": status,
        "transcript": transcript,
        "workspace": str(workspace),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "execution_time": execution_time,
        "stdout": stdout,
        "stderr": stderr,
    }
