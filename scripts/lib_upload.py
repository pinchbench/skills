"""
Upload benchmark results to the PinchBench leaderboard server.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from urllib import error, request

DEFAULT_SERVER_URL = "https://api.pinchbench.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
CONFIG_DIR = Path(__file__).resolve().parent / ".pinchbench"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class UploadResult:
    status: str
    submission_id: str
    rank: int | None = None
    percentile: float | None = None
    leaderboard_url: str | None = None


class UploadError(RuntimeError):
    pass


def upload_results(
    results_path: Path,
    *,
    server_url: str | None = None,
    token: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    dry_run: bool = False,
) -> UploadResult:
    """
    Upload benchmark results to the PinchBench leaderboard server.

    Args:
        results_path: Path to the JSON results file
        server_url: Override server URL (default: from env or api.pinchbench.com)
        token: Auth token (default: from PINCHBENCH_TOKEN env var)
        timeout_seconds: HTTP request timeout
        dry_run: If True, validate but don't actually send

    Returns:
        UploadResult with status, rank, and leaderboard URL

    Raises:
        UploadError: If upload fails (network, auth, validation)
    """
    resolved_server = server_url or os.environ.get("PINCHBENCH_SERVER_URL") or DEFAULT_SERVER_URL
    resolved_token = _resolve_token(token)
    if not resolved_token:
        raise UploadError("PINCHBENCH_TOKEN is not configured")

    payload = _build_payload(results_path)
    if dry_run:
        return UploadResult(status="dry_run", submission_id=payload["submission_id"])

    endpoint = resolved_server.rstrip("/") + "/api/results"
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-PinchBench-Token": resolved_token,
        "X-PinchBench-Version": payload.get("client_version", ""),
        "User-Agent": "PinchBench/" + (payload.get("client_version") or "unknown"),
    }
    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            response_body = resp.read().decode("utf-8")
            if response_body:
                try:
                    data = json.loads(response_body)
                except json.JSONDecodeError:
                    data = {"status": "accepted"}
            else:
                data = {}
    except error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
            error_payload = json.loads(error_body) if error_body else {}
        except Exception:
            error_payload = {}
        raise UploadError(f"Upload failed ({exc.code}): {error_payload or exc.reason}") from exc
    except error.URLError as exc:
        raise UploadError(f"Upload failed (network): {exc.reason}") from exc

    submission_id = data.get("submission_id")
    if not submission_id:
        submission_id = payload["submission_id"]
    rank = data.get("rank")
    if rank is not None:
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            rank = None
    percentile = data.get("percentile")
    if percentile is not None:
        try:
            percentile = float(percentile)
        except (TypeError, ValueError):
            percentile = None

    return UploadResult(
        status=str(data.get("status", "accepted")),
        submission_id=str(submission_id),
        rank=rank,
        percentile=percentile,
        leaderboard_url=data.get("leaderboard_url"),
    )


def register_token(
    *,
    server_url: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, str | None]:
    resolved_server = server_url or os.environ.get("PINCHBENCH_SERVER_URL") or DEFAULT_SERVER_URL
    endpoint = resolved_server.rstrip("/") + "/api/register"
    body = json.dumps({}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "PinchBench/" + _read_client_version(),
    }
    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            response_body = resp.read().decode("utf-8")
            data = json.loads(response_body) if response_body else {}
    except error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
            error_payload = json.loads(error_body) if error_body else {}
        except Exception:
            error_payload = {}
        raise UploadError(f"Registration failed ({exc.code}): {error_payload or exc.reason}") from exc
    except error.URLError as exc:
        raise UploadError(f"Registration failed (network): {exc.reason}") from exc

    token = data.get("token") or data.get("api_key")
    if not token:
        raise UploadError("Registration failed: response missing token")
    claim_url = data.get("claim_url")
    return token, claim_url


def save_token_config(token: str, claim_url: str | None = None) -> Path:
    config = _read_config()
    config["token"] = token
    if claim_url:
        config["claim_url"] = claim_url
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return CONFIG_PATH


def _build_payload(results_path: Path) -> Dict[str, Any]:
    raw = json.loads(results_path.read_text(encoding="utf-8"))
    tasks = raw.get("tasks", [])
    total_score = 0.0
    max_score = 0.0
    total_execution_time = 0.0
    total_cost_usd = 0.0
    usage_summary = {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_requests": 0,
        "total_cost_usd": 0.0,
    }

    formatted_tasks: list[dict[str, Any]] = []
    for task in tasks:
        grading = task.get("grading", {})
        runs = grading.get("runs", []) if isinstance(grading.get("runs", []), list) else []
        if "score" in grading:
            score = float(grading.get("score", 0.0))
        else:
            score = float(grading.get("mean", 0.0))

        if "max_score" in grading:
            max_for_task = float(grading.get("max_score", 0.0))
        elif runs:
            max_for_task = float(
                max(
                    (
                        float(run.get("max_score", 0.0))
                        for run in runs
                        if isinstance(run, dict)
                    ),
                    default=0.0,
                )
            )
        else:
            max_for_task = 0.0
        total_score += score
        max_score += max_for_task

        usage = task.get("usage", {})
        total_execution_time += float(task.get("execution_time", 0.0) or 0.0)
        cost_usd = float(usage.get("cost_usd", 0.0) or 0.0)
        total_cost_usd += cost_usd
        usage_summary["total_input_tokens"] += int(usage.get("input_tokens", 0))
        usage_summary["total_output_tokens"] += int(usage.get("output_tokens", 0))
        usage_summary["total_requests"] += int(usage.get("request_count", 0))
        usage_summary["total_cost_usd"] += cost_usd

        grading_type = grading.get("grading_type")
        if not grading_type and runs:
            grading_type = runs[0].get("grading_type") if isinstance(runs[0], dict) else None
        breakdown = grading.get("breakdown")
        if breakdown is None and runs:
            breakdown = runs[0].get("breakdown") if isinstance(runs[0], dict) else {}
        if breakdown is None:
            breakdown = {}
        notes = grading.get("notes")
        if notes is None and runs:
            notes = runs[0].get("notes") if isinstance(runs[0], dict) else ""
        if notes is None:
            notes = ""

        formatted_tasks.append(
            {
                "task_id": task.get("task_id"),
                "score": score,
                "max_score": max_for_task,
                "grading_type": grading_type,
                "timed_out": bool(task.get("timed_out")),
                "execution_time_seconds": task.get("execution_time"),
                "breakdown": breakdown,
                "notes": notes,
                "frontmatter": task.get("frontmatter", {}),
            }
        )

    client_version = _read_client_version()
    model = raw.get("model", "")
    provider = model.split("/")[0] if "/" in model else ""

    payload = {
        "submission_id": str(uuid.uuid4()),
        "timestamp": _format_timestamp(raw.get("timestamp")),
        "client_version": client_version,
        "benchmark_version": raw.get("benchmark_version"),
        "model": model,
        "provider": provider,
        "run_id": raw.get("run_id"),
        "openclaw_version": _get_openclaw_version(),
        "total_score": round(total_score, 6),
        "max_score": round(max_score, 6),
        "total_execution_time_seconds": round(total_execution_time, 6),
        "total_cost_usd": round(total_cost_usd, 6),
        "tasks": formatted_tasks,
        "usage_summary": usage_summary,
        "metadata": {
            "suite": raw.get("suite"),
            "system": collect_system_metadata(),
        },
    }
    return payload


def _read_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _resolve_token(explicit_token: str | None) -> str | None:
    if explicit_token:
        return explicit_token
    env_token = os.environ.get("PINCHBENCH_TOKEN")
    if env_token:
        return env_token
    config = _read_config()
    return config.get("token")


def _format_timestamp(timestamp: Any) -> str:
    if isinstance(timestamp, (int, float)):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(timestamp)))
    if isinstance(timestamp, str):
        return timestamp
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_client_version() -> str:
    pyproject = Path(__file__).with_name("pyproject.toml")
    if not pyproject.exists():
        return ""
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version") and "=" in stripped:
            return stripped.split("=", 1)[1].strip().strip('"')
    return ""


def _get_openclaw_version() -> str | None:
    try:
        result = subprocess.run(
            ["openclaw", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def collect_system_metadata() -> Dict[str, Any]:
    """Collect system metadata for submission."""
    meta = {
        "os": sys.platform,
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "cpu_count": os.cpu_count(),
        "hostname_hash": hash(platform.node()) % 10000,
    }

    if sys.platform == "linux":
        meta.update(_collect_linux_info())
    elif sys.platform == "darwin":
        meta.update(_collect_macos_info())

    return meta


def _collect_linux_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    cpuinfo_path = Path("/proc/cpuinfo")
    meminfo_path = Path("/proc/meminfo")

    try:
        cpuinfo = cpuinfo_path.read_text(encoding="utf-8")
        for line in cpuinfo.splitlines():
            if "model name" in line:
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass

    try:
        meminfo = meminfo_path.read_text(encoding="utf-8")
        total_kb = _parse_meminfo_value(meminfo, "MemTotal")
        avail_kb = _parse_meminfo_value(meminfo, "MemAvailable")
        if total_kb is not None:
            info["memory_total_gb"] = round(total_kb / 1e6, 1)
        if avail_kb is not None:
            info["memory_available_gb"] = round(avail_kb / 1e6, 1)
    except OSError:
        pass

    return info


def _parse_meminfo_value(meminfo: str, key: str) -> int | None:
    for line in meminfo.splitlines():
        if line.startswith(f"{key}:"):
            value = line.split(":", 1)[1].strip().split(" ")[0]
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _collect_macos_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {}

    def sysctl(key: str) -> str | None:
        try:
            result = subprocess.run(
                ["sysctl", "-n", key],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    cpu_brand = sysctl("machdep.cpu.brand_string")
    if cpu_brand:
        info["cpu_model"] = cpu_brand

    mem_bytes = sysctl("hw.memsize")
    if mem_bytes:
        try:
            info["memory_total_gb"] = round(int(mem_bytes) / 1e9, 1)
        except ValueError:
            pass

    physical = sysctl("hw.physicalcpu")
    if physical:
        try:
            info["cpu_cores_physical"] = int(physical)
        except ValueError:
            pass

    logical = sysctl("hw.logicalcpu")
    if logical:
        try:
            info["cpu_cores_logical"] = int(logical)
        except ValueError:
            pass

    return info
