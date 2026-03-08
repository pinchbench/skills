"""
OpenClaw agent execution helpers for PinchBench.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib_tasks import Task


logger = logging.getLogger(__name__)
MAX_OPENCLAW_MESSAGE_CHARS = 4000


def slugify_model(model_id: str) -> str:
    return model_id.replace("/", "-").replace(".", "-")


def normalize_model_id(model_id: str) -> str:
    """Normalize a model ref while preserving provider routing.

    PinchBench is a deterministic benchmark tool: it must not silently rewrite
    provider-qualified model refs (for example by forcing openrouter/...).
    """
    normalized = model_id.strip()
    while normalized.startswith("/"):
        normalized = normalized[1:]
    if not normalized or "/" not in normalized:
        raise ValueError(
            "Model must be provider-qualified (provider/model), "
            f"got: {model_id!r}"
        )
    return normalized


_MODEL_CATALOG_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _load_model_catalog() -> Dict[str, Dict[str, Any]]:
    global _MODEL_CATALOG_CACHE
    if _MODEL_CATALOG_CACHE is not None:
        return _MODEL_CATALOG_CACHE

    try:
        result = subprocess.run(
            ["openclaw", "models", "list", "--all", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"openclaw CLI not found while loading model catalog: {exc}") from exc

    if result.returncode != 0:
        raise RuntimeError(
            "Failed to load model catalog via `openclaw models list --all --json`: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse model catalog JSON: {exc}") from exc

    models = payload.get("models", []) if isinstance(payload, dict) else []
    catalog: Dict[str, Dict[str, Any]] = {}
    for entry in models:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if not isinstance(key, str):
            continue
        catalog[key.lower()] = entry

    _MODEL_CATALOG_CACHE = catalog
    return catalog


def _suggest_model_ref(model_ref: str, catalog: Dict[str, Dict[str, Any]]) -> Optional[str]:
    if model_ref.lower().startswith("openrouter/"):
        return None
    candidate = f"openrouter/{model_ref}".lower()
    if candidate in catalog:
        return f"openrouter/{model_ref}"
    return None


def ensure_model_available(model_id: str, *, role: str) -> str:
    """Validate model ref format and availability in local OpenClaw config."""
    normalized_model = normalize_model_id(model_id)
    catalog = _load_model_catalog()
    entry = catalog.get(normalized_model.lower())
    if entry is None:
        suggestion = _suggest_model_ref(normalized_model, catalog)
        extra = f" Maybe you meant `{suggestion}`." if suggestion else ""
        raise ValueError(
            f"{role} model `{normalized_model}` is not in the OpenClaw model catalog.{extra}"
        )
    if not entry.get("available", False):
        suggestion = _suggest_model_ref(normalized_model, catalog)
        extra = f" Maybe you meant `{suggestion}`." if suggestion else ""
        raise ValueError(
            f"{role} model `{normalized_model}` exists but is not available/configured in this OpenClaw instance.{extra}"
        )
    return normalized_model


def _get_agent_workspace(agent_id: str) -> Path | None:
    """Get the workspace path for an agent from OpenClaw config."""
    try:
        list_result = subprocess.run(
            ["openclaw", "agents", "list"],
            capture_output=True,
            text=True,
            check=False,
        )
        if list_result.returncode != 0:
            return None

        # Parse the agent list output to find workspace
        # OpenClaw normalizes colons to dashes in agent names, so check both.
        normalized_id = agent_id.replace(":", "-")
        lines = list_result.stdout.split("\n")
        found_agent = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f"- {agent_id}") or stripped.startswith(f"- {normalized_id}"):
                found_agent = True
            elif found_agent and "Workspace:" in line:
                workspace_str = line.split("Workspace:")[1].strip()
                # Expand ~ if present
                if workspace_str.startswith("~/"):
                    workspace_str = str(Path.home() / workspace_str[2:])
                return Path(workspace_str)
            elif found_agent and line.strip().startswith("-"):
                # Found next agent, stop looking
                break
        return None
    except Exception as exc:
        logger.warning("Failed to get agent workspace: %s", exc)
        return None


def ensure_agent_exists(agent_id: str, model_id: str, workspace_dir: Path) -> bool:
    """Ensure the OpenClaw agent exists with the correct workspace.

    If the agent already exists but points to a different workspace, it is
    deleted and recreated so that the new workspace takes effect.
    Returns True if the agent was (re)created.
    """
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

    if list_result.returncode == 0:
        # Check for exact agent ID match — avoid substring false positives
        # (e.g. "bench-foo-4" matching "bench-foo-4-5" in the output).
        # Output format is "- <agent_id>" or "- <agent_id> (default)" per line.
        # OpenClaw normalizes colons to dashes in directory/display names, so
        # also check the normalized form.
        existing_agents = set()
        for line in list_result.stdout.splitlines():
            line = line.strip()
            if line.startswith("- "):
                # Extract agent name: "- bench-foo-4-5" or "- main (default)"
                name_part = line[2:].split()[0] if line[2:].strip() else ""
                if name_part:
                    existing_agents.add(name_part)
        normalized_id = agent_id.replace(":", "-")
        if agent_id in existing_agents or normalized_id in existing_agents:
            # Agent exists — check if workspace matches
            current_workspace = _get_agent_workspace(agent_id)
            if current_workspace is not None and current_workspace.resolve() == workspace_dir.resolve():
                logger.info("Agent %s already exists with correct workspace", agent_id)
                return False
            # Workspace is stale or unknown — delete and recreate
            delete_name = normalized_id if normalized_id in existing_agents else agent_id
            logger.info(
                "Agent %s exists with stale workspace (%s != %s), recreating",
                agent_id,
                current_workspace,
                workspace_dir,
            )
            subprocess.run(
                ["openclaw", "agents", "delete", delete_name, "--force"],
                capture_output=True,
                text=True,
                check=False,
            )

    normalized_model = normalize_model_id(model_id)
    logger.info("Creating OpenClaw agent %s", agent_id)
    try:
        create_result = subprocess.run(
            [
                "openclaw",
                "agents",
                "add",
                agent_id,
                "--model",
                normalized_model,
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


def cleanup_agent_sessions(agent_id: str) -> None:
    """Remove stored session transcripts for an agent to avoid unbounded growth."""
    agent_dir = _get_agent_store_dir(agent_id)
    sessions_dir = agent_dir / "sessions"
    if not sessions_dir.exists():
        return
    removed = 0
    for pattern in ("*.jsonl", "*.jsonl.lock"):
        for path in sessions_dir.glob(pattern):
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("Failed to remove session file %s: %s", path, exc)
    sessions_store = sessions_dir / "sessions.json"
    if sessions_store.exists():
        try:
            sessions_store.unlink()
        except OSError as exc:
            logger.warning("Failed to remove session store %s: %s", sessions_store, exc)
    if removed:
        logger.info("Removed %s old OpenClaw session transcripts for %s", removed, agent_id)


def prepare_task_workspace(skill_dir: Path, run_id: str, task: Task, agent_id: str) -> Path:
    """
    Prepare workspace for a task by copying fixtures.
    Uses the agent's configured workspace to ensure files are in the right place.
    """
    # Get agent's workspace from agent config
    workspace = _get_agent_workspace(agent_id)
    if workspace is None:
        # Fallback to task-specific workspace if agent workspace not found
        logger.warning("Could not find agent workspace, using fallback")
        workspace = Path(f"/tmp/pinchbench/{run_id}/{task.task_id}")

    workspace.mkdir(parents=True, exist_ok=True)

    for file_spec in task.workspace_files:
        if "content" in file_spec:
            dest = workspace / file_spec["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(file_spec["content"])
            continue

        source = skill_dir / "assets" / file_spec["source"]
        dest = workspace / file_spec["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(source.read_bytes())
        except FileNotFoundError:
            logger.error("Workspace file not found: %s", source)
            raise

    return workspace


def _get_agent_store_dir(agent_id: str) -> Path:
    base_dir = Path.home() / ".openclaw" / "agents"
    direct_dir = base_dir / agent_id
    if direct_dir.exists():
        return direct_dir
    normalized_dir = base_dir / agent_id.replace(":", "-")
    if normalized_dir.exists():
        return normalized_dir
    return direct_dir


def _resolve_session_id_from_store(agent_id: str) -> str | None:
    agent_dir = _get_agent_store_dir(agent_id)
    sessions_store = agent_dir / "sessions" / "sessions.json"
    if not sessions_store.exists():
        return None
    try:
        sessions_payload = json.loads(sessions_store.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse sessions store: %s", exc)
        return None
    if not isinstance(sessions_payload, dict):
        return None

    normalized_id = agent_id.replace(":", "-")
    preferred_keys = [
        f"agent:{agent_id}:main",
        f"agent:{agent_id}:default",
        f"agent:{normalized_id}:main",
        f"agent:{normalized_id}:default",
    ]
    for key in preferred_keys:
        entry = sessions_payload.get(key)
        if isinstance(entry, dict) and entry.get("sessionId"):
            return entry["sessionId"]

    newest_entry = None
    newest_timestamp = -1
    for entry in sessions_payload.values():
        if not isinstance(entry, dict):
            continue
        if "sessionId" not in entry:
            continue
        updated_at = entry.get("updatedAt")
        if isinstance(updated_at, (int, float)) and updated_at > newest_timestamp:
            newest_timestamp = updated_at
            newest_entry = entry
    if newest_entry:
        return newest_entry.get("sessionId")
    return None


def _find_recent_session_path(agent_dir: Path, started_at: float) -> Path | None:
    sessions_dir = agent_dir / "sessions"
    if not sessions_dir.exists():
        return None
    candidates = list(sessions_dir.glob("*.jsonl"))
    if not candidates:
        return None
    tolerance_seconds = 5.0
    recent_candidates = [
        path for path in candidates if path.stat().st_mtime >= (started_at - tolerance_seconds)
    ]
    pool = recent_candidates or candidates
    return max(pool, key=lambda path: path.stat().st_mtime)


def _entry_timestamp_epoch(entry: Dict[str, Any]) -> Optional[float]:
    ts = entry.get("timestamp")
    if isinstance(ts, (int, float)):
        # OpenClaw sometimes stores ms in nested message.timestamp, but the
        # top-level timestamp is typically ISO. Keep numeric support just in case.
        return ts / 1000.0 if ts > 10_000_000_000 else float(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    msg = entry.get("message")
    if isinstance(msg, dict):
        mts = msg.get("timestamp")
        if isinstance(mts, (int, float)):
            return mts / 1000.0 if mts > 10_000_000_000 else float(mts)
    return None


def _load_transcript(agent_id: str, session_id: str, started_at: float) -> List[Dict[str, Any]]:
    agent_dir = _get_agent_store_dir(agent_id)
    transcript_path = None

    # OpenClaw ignores the --session-id we pass and generates its own UUID-based
    # session ID internally.  We need to discover the actual transcript path.
    #
    # Strategy (with retries to handle write-delay):
    #   1. Resolve the real session ID from sessions.json
    #   2. Glob for any .jsonl in the sessions dir (most-recently-modified)
    #   3. Try our passed-in session ID as a last resort
    for attempt in range(6):
        # 1. Try sessions.json first — OpenClaw writes the real UUID here
        resolved_session_id = _resolve_session_id_from_store(agent_id)
        if resolved_session_id:
            candidate = agent_dir / "sessions" / f"{resolved_session_id}.jsonl"
            if candidate.exists():
                transcript_path = candidate
                logger.info(
                    "Found transcript via sessions.json: %s (attempt %s)",
                    candidate.name,
                    attempt + 1,
                )
                break

        # 2. Glob fallback — pick the most recently modified .jsonl
        recent_path = _find_recent_session_path(agent_dir, started_at)
        if recent_path is not None:
            transcript_path = recent_path
            logger.info(
                "Found transcript via glob fallback: %s (attempt %s)",
                recent_path.name,
                attempt + 1,
            )
            break

        # 3. Try our passed-in session ID (unlikely to work, but check anyway)
        direct_path = agent_dir / "sessions" / f"{session_id}.jsonl"
        if direct_path.exists():
            transcript_path = direct_path
            logger.info(
                "Found transcript via passed session ID: %s (attempt %s)",
                direct_path.name,
                attempt + 1,
            )
            break

        if attempt < 5:
            time.sleep(1.0)

    if transcript_path is None:
        sessions_dir = agent_dir / "sessions"
        if sessions_dir.exists():
            all_files = list(sessions_dir.iterdir())
            logger.warning(
                "Transcript not found for agent %s. Sessions dir contents: %s",
                agent_id,
                [f.name for f in all_files],
            )
        else:
            logger.warning(
                "Transcript not found — sessions dir does not exist: %s",
                sessions_dir,
            )
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

    # When sessions are persistent, multiple task turns can share one session
    # file. Keep only entries for this invocation window when possible.
    cutoff = started_at - 2.0
    recent_entries = []
    for entry in transcript:
        entry_ts = _entry_timestamp_epoch(entry)
        if entry_ts is not None and entry_ts >= cutoff:
            recent_entries.append(entry)
    if recent_entries:
        return recent_entries

    return transcript


def _extract_usage_from_transcript(transcript: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum token usage and cost from all assistant messages in transcript."""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "request_count": 0,
    }

    for entry in transcript:
        if entry.get("type") != "message":
            continue
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue
        totals["request_count"] += 1
        usage = msg.get("usage", {})
        totals["input_tokens"] += usage.get("input", 0)
        totals["output_tokens"] += usage.get("output", 0)
        totals["cache_read_tokens"] += usage.get("cacheRead", 0)
        totals["cache_write_tokens"] += usage.get("cacheWrite", 0)
        totals["total_tokens"] += usage.get("totalTokens", 0)
        cost = usage.get("cost", {})
        totals["cost_usd"] += cost.get("total", 0.0)

    return totals


def _extract_runtime_model_ref(transcript: List[Dict[str, Any]]) -> Optional[str]:
    """Extract the last provider/model seen at runtime from transcript."""
    latest_model_ref: Optional[str] = None

    for entry in transcript:
        if entry.get("type") != "custom":
            continue
        if entry.get("customType") != "model-snapshot":
            continue
        data = entry.get("data", {})
        provider = data.get("provider")
        model_id = data.get("modelId")
        if isinstance(provider, str) and isinstance(model_id, str):
            latest_model_ref = f"{provider}/{model_id}"

    if latest_model_ref:
        return latest_model_ref

    for entry in transcript:
        if entry.get("type") != "message":
            continue
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue
        provider = msg.get("provider")
        model_id = msg.get("model")
        if isinstance(provider, str) and isinstance(model_id, str):
            latest_model_ref = f"{provider}/{model_id}"

    return latest_model_ref


def _extract_terminal_assistant_error(transcript: List[Dict[str, Any]]) -> Optional[str]:
    """Return terminal assistant error if the *last* assistant message ended in error.

    OpenClaw may recover from transient provider/auth errors mid-turn (profile
    rotation). For deterministic benchmark status we only treat the run as an
    assistant error when the last assistant event is itself an error.
    """
    last_assistant_msg: Optional[Dict[str, Any]] = None
    for entry in transcript:
        if entry.get("type") != "message":
            continue
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue
        if isinstance(msg, dict):
            last_assistant_msg = msg

    if not last_assistant_msg:
        return None

    error_message = last_assistant_msg.get("errorMessage")
    stop_reason = last_assistant_msg.get("stopReason")
    if isinstance(error_message, str) and error_message.strip():
        return error_message.strip()
    if stop_reason == "error":
        return "assistant stopReason=error"
    return None


def execute_openclaw_task(
    *,
    task: Task,
    agent_id: str,
    model_id: str,
    run_id: str,
    timeout_multiplier: float,
    skill_dir: Path,
    thinking_level: Optional[str] = None,
    clear_sessions: bool = False,
) -> Dict[str, Any]:
    logger.info("🤖 Agent [%s] starting task: %s", agent_id, task.task_id)
    logger.info("   Task: %s", task.name)
    logger.info("   Category: %s", task.category)

    # Optional cleanup for deterministic fresh session directories.
    # Default is to preserve sessions so runs are resumable / auditable.
    if clear_sessions:
        cleanup_agent_sessions(agent_id)

    start_time = time.time()
    workspace = prepare_task_workspace(skill_dir, run_id, task, agent_id)
    session_id = f"{task.task_id}_{int(time.time() * 1000)}"
    timeout_seconds = task.timeout_seconds * timeout_multiplier
    stdout = ""
    stderr = ""
    exit_code = -1
    timed_out = False

    try:
        command = [
            "openclaw",
            "agent",
            "--agent",
            agent_id,
            "--session-id",
            session_id,
            "--message",
            task.prompt,
        ]
        if thinking_level:
            command.extend(["--thinking", thinking_level])

        result = subprocess.run(
            command,
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

    transcript = _load_transcript(agent_id, session_id, start_time)
    usage = _extract_usage_from_transcript(transcript)
    execution_time = time.time() - start_time

    requested_model = normalize_model_id(model_id)
    runtime_model = _extract_runtime_model_ref(transcript)
    assistant_error = _extract_terminal_assistant_error(transcript)

    status = "success"
    if timed_out:
        status = "timeout"
    if not transcript:
        status = "error"
    if exit_code not in (0, -1) and not timed_out:
        status = "error"
    if stderr and "openclaw command not found" in str(stderr):
        status = "error"
    if assistant_error:
        status = "error"
        stderr = f"{stderr}\nAssistant error: {assistant_error}".strip()
    if runtime_model is None:
        status = "error"
        stderr = f"{stderr}\nCould not verify runtime provider/model from transcript.".strip()
    elif runtime_model.lower() != requested_model.lower():
        status = "error"
        stderr = (
            f"{stderr}\nModel mismatch: requested `{requested_model}` but runtime used `{runtime_model}`."
        ).strip()

    return {
        "agent_id": agent_id,
        "task_id": task.task_id,
        "status": status,
        "requested_model": requested_model,
        "runtime_model": runtime_model,
        "transcript": transcript,
        "usage": usage,
        "workspace": str(workspace),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "execution_time": execution_time,
        "stdout": stdout,
        "stderr": stderr,
    }


def run_openclaw_prompt(
    *,
    agent_id: str,
    prompt: str,
    workspace: Path,
    timeout_seconds: float,
    expected_model_ref: Optional[str] = None,
    clear_sessions: bool = False,
) -> Dict[str, Any]:
    """Run a single OpenClaw prompt for helper agents like the judge."""
    # Optional cleanup for deterministic fresh session directories.
    # Default is to preserve judge sessions for audit/debug/resume.
    if clear_sessions:
        cleanup_agent_sessions(agent_id)

    start_time = time.time()
    workspace.mkdir(parents=True, exist_ok=True)
    session_id = f"judge_{int(time.time() * 1000)}"
    stdout = ""
    stderr = ""
    exit_code = -1
    timed_out = False

    chunks = [
        prompt[i : i + MAX_OPENCLAW_MESSAGE_CHARS]
        for i in range(0, max(1, len(prompt)), MAX_OPENCLAW_MESSAGE_CHARS)
    ]
    if len(chunks) > 1:
        total_chunks = len(chunks)
        chunks = [
            (
                f"You are receiving a long prompt in {total_chunks} parts.\n"
                f"Ignore and do not respond until the final part.\n\n"
                f"Part 1/{total_chunks}:\n{chunks[0]}"
            )
        ] + [
            (
                f"Part {i + 2}/{total_chunks}:\n{chunks[i + 1]}"
                if i + 2 < total_chunks
                else (
                    f"Part {i + 2}/{total_chunks} (final):\n{chunks[i + 1]}\n"
                    "All parts received. Proceed with final judgment now."
                )
            )
            for i in range(0, total_chunks - 1)
        ]
    for chunk in chunks:
        elapsed = time.time() - start_time
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            timed_out = True
            break
        try:
            result = subprocess.run(
                [
                    "openclaw",
                    "agent",
                    "--agent",
                    agent_id,
                    "--session-id",
                    session_id,
                    "--message",
                    chunk,
                ],
                capture_output=True,
                text=True,
                cwd=str(workspace),
                timeout=remaining,
                check=False,
            )
            stdout += result.stdout
            stderr += result.stderr
            exit_code = result.returncode
            if result.returncode not in (0, -1) and not timed_out:
                break
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout += exc.stdout or ""
            stderr += exc.stderr or ""
            break
        except FileNotFoundError as exc:
            stderr += f"openclaw command not found: {exc}"
            break

    transcript = _load_transcript(agent_id, session_id, start_time)
    execution_time = time.time() - start_time
    runtime_model = _extract_runtime_model_ref(transcript)
    assistant_error = _extract_terminal_assistant_error(transcript)

    status = "success"
    if timed_out:
        status = "timeout"
    if not transcript:
        status = "error"
    if exit_code not in (0, -1) and not timed_out:
        status = "error"
    if stderr and "openclaw command not found" in str(stderr):
        status = "error"
    if assistant_error:
        status = "error"
        stderr = f"{stderr}\nAssistant error: {assistant_error}".strip()

    expected_model = normalize_model_id(expected_model_ref) if expected_model_ref else None
    if expected_model:
        if runtime_model is None:
            status = "error"
            stderr = f"{stderr}\nCould not verify runtime provider/model from judge transcript.".strip()
        elif runtime_model.lower() != expected_model.lower():
            status = "error"
            stderr = (
                f"{stderr}\nJudge model mismatch: requested `{expected_model}` "
                f"but runtime used `{runtime_model}`."
            ).strip()

    return {
        "agent_id": agent_id,
        "status": status,
        "requested_model": expected_model,
        "runtime_model": runtime_model,
        "transcript": transcript,
        "workspace": str(workspace),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "execution_time": execution_time,
        "stdout": stdout,
        "stderr": stderr,
    }
