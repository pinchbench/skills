"""
PinchBench grading engine.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib_agent import ensure_agent_exists, run_openclaw_prompt, slugify_model
from lib_tasks import Task


logger = logging.getLogger(__name__)


DEFAULT_JUDGE_MODEL = "anthropic/claude-opus-4.5"
DEFAULT_JUDGE_AGENT_PREFIX = "bench-judge"
DEFAULT_JUDGE_TIMEOUT_SECONDS = 180


@dataclass
class GradeResult:
    task_id: str
    score: float
    max_score: float
    grading_type: str
    breakdown: Dict[str, float]
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "score": self.score,
            "max_score": self.max_score,
            "grading_type": self.grading_type,
            "breakdown": self.breakdown,
            "notes": self.notes,
        }


def grade_task(
    *,
    task: Task,
    execution_result: Dict[str, Any],
    skill_dir: Path,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    judge_agent_prefix: str = DEFAULT_JUDGE_AGENT_PREFIX,
    judge_timeout_seconds: float = DEFAULT_JUDGE_TIMEOUT_SECONDS,
) -> GradeResult:
    grading_type = task.grading_type
    if grading_type == "automated":
        return _grade_automated(task, execution_result)
    if grading_type == "llm_judge":
        return _grade_llm_judge(
            task=task,
            execution_result=execution_result,
            judge_model=judge_model,
            judge_agent_prefix=judge_agent_prefix,
            judge_timeout_seconds=judge_timeout_seconds,
            skill_dir=skill_dir,
        )
    if grading_type == "hybrid":
        auto_result = _grade_automated(task, execution_result)
        llm_result = _grade_llm_judge(
            task=task,
            execution_result=execution_result,
            judge_model=judge_model,
            judge_agent_prefix=judge_agent_prefix,
            judge_timeout_seconds=judge_timeout_seconds,
            skill_dir=skill_dir,
        )
        return _combine_grades(task, auto_result, llm_result)
    raise ValueError(f"Unknown grading type: {grading_type}")


def _grade_automated(task: Task, execution_result: Dict[str, Any]) -> GradeResult:
    grading_code = _extract_grading_code(task)
    if not grading_code:
        return GradeResult(
            task_id=task.task_id,
            score=0.0,
            max_score=1.0,
            grading_type="automated",
            breakdown={},
            notes="No automated grading code found",
        )

    namespace: Dict[str, Any] = {}
    exec(grading_code, namespace)
    grade_func = namespace.get("grade")
    if not callable(grade_func):
        return GradeResult(
            task_id=task.task_id,
            score=0.0,
            max_score=1.0,
            grading_type="automated",
            breakdown={},
            notes="Automated grading function missing",
        )

    scores = grade_func(
        execution_result.get("transcript", []),
        execution_result.get("workspace", ""),
    )
    if not isinstance(scores, dict):
        scores = {}

    total = _average_scores(scores)
    return GradeResult(
        task_id=task.task_id,
        score=total,
        max_score=1.0,
        grading_type="automated",
        breakdown=_normalize_score_dict(scores),
        notes="",
    )


def _grade_llm_judge(
    *,
    task: Task,
    execution_result: Dict[str, Any],
    judge_model: str,
    judge_agent_prefix: str,
    judge_timeout_seconds: float,
    skill_dir: Path,
) -> GradeResult:
    transcript_summary = _summarize_transcript(execution_result.get("transcript", []))
    rubric = task.llm_judge_rubric or _format_grading_criteria(task)
    prompt = _build_judge_prompt(task, transcript_summary, rubric)

    agent_id = _ensure_judge_agent(judge_agent_prefix, judge_model, skill_dir)
    judge_workspace = Path(f"/tmp/pinchbench/judge/{task.task_id}")
    judge_result = run_openclaw_prompt(
        agent_id=agent_id,
        prompt=prompt,
        workspace=judge_workspace,
        timeout_seconds=judge_timeout_seconds,
    )

    parsed = _parse_judge_response(judge_result.get("transcript", []))
    breakdown = parsed.get("scores", {})
    total = parsed.get("total")
    notes = parsed.get("notes", "")
    if total is None:
        total = _average_scores(breakdown)
    return GradeResult(
        task_id=task.task_id,
        score=float(total) if total is not None else 0.0,
        max_score=1.0,
        grading_type="llm_judge",
        breakdown=_normalize_score_dict(breakdown),
        notes=str(notes) if notes is not None else "",
    )


def _combine_grades(task: Task, auto_result: GradeResult, llm_result: GradeResult) -> GradeResult:
    weights = task.grading_weights or {"automated": 0.5, "llm_judge": 0.5}
    auto_weight = float(weights.get("automated", 0.5))
    llm_weight = float(weights.get("llm_judge", 0.5))
    total_weight = auto_weight + llm_weight
    if total_weight <= 0:
        auto_weight = llm_weight = 0.5
        total_weight = 1.0
    combined_score = (
        auto_result.score * auto_weight + llm_result.score * llm_weight
    ) / total_weight
    breakdown = {
        **{f"automated.{k}": v for k, v in auto_result.breakdown.items()},
        **{f"llm_judge.{k}": v for k, v in llm_result.breakdown.items()},
    }
    notes = " | ".join(filter(None, [auto_result.notes, llm_result.notes]))
    return GradeResult(
        task_id=task.task_id,
        score=combined_score,
        max_score=1.0,
        grading_type="hybrid",
        breakdown=breakdown,
        notes=notes,
    )


def _extract_grading_code(task: Task) -> str:
    if not task.automated_checks:
        return ""
    match = re.search(r"```python\s*(.*?)\s*```", task.automated_checks, re.DOTALL)
    if not match:
        return ""
    return match.group(1)


def _average_scores(scores: Dict[str, Any]) -> float:
    values = [float(v) for v in scores.values() if isinstance(v, (int, float))]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _normalize_score_dict(scores: Dict[str, Any]) -> Dict[str, float]:
    normalized: Dict[str, float] = {}
    for key, value in scores.items():
        try:
            normalized[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _format_grading_criteria(task: Task) -> str:
    if not task.grading_criteria:
        return ""
    return "\n".join(f"- {criterion}" for criterion in task.grading_criteria)


def _summarize_transcript(transcript: List[Dict[str, Any]]) -> str:
    summary_parts: List[str] = []
    for event in transcript:
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        role = msg.get("role")
        if role == "assistant":
            for item in msg.get("content", []):
                if item.get("type") == "toolCall":
                    summary_parts.append(
                        f"Tool: {item.get('name')}({json.dumps(item.get('arguments', {}))})"
                    )
        elif role == "toolResult":
            content = msg.get("content", [])
            if content:
                result_preview = str(content[0])[:200]
                summary_parts.append(f"Result: {result_preview}")
        elif role == "user":
            content = msg.get("content", [])
            if content:
                summary_parts.append(f"User: {content[0]}")
    return "\n".join(summary_parts)


def _build_judge_prompt(task: Task, transcript_summary: str, rubric: str) -> str:
    return (
        "You are grading an AI agent's performance on a task.\n\n"
        "Be a strict evaluator. Reserve 1.0 for genuinely excellent performance. "
        "An average acceptable completion should score around 0.6-0.7. "
        "Deduct points for unnecessary steps, verbose output, and inefficient tool usage.\n\n"
        "## Task\n"
        f"{task.prompt}\n\n"
        "## Expected Behavior\n"
        f"{task.expected_behavior}\n\n"
        "## Agent Transcript (summarized)\n"
        f"{transcript_summary}\n\n"
        "## Grading Rubric\n"
        f"{rubric}\n\n"
        "Score each criterion from 0.0 to 1.0. Provide brief justification for each score. "
        "Output strict JSON with keys: scores (object), total (number 0-1), notes (string)."
    )


def _ensure_judge_agent(judge_agent_prefix: str, judge_model: str, skill_dir: Path) -> str:
    model_slug = slugify_model(judge_model)
    agent_id = f"{judge_agent_prefix}-{model_slug}"
    workspace = Path("/tmp/pinchbench/judge/workspace")
    ensure_agent_exists(agent_id, judge_model, workspace)
    return agent_id


def _parse_judge_response(transcript: List[Dict[str, Any]]) -> Dict[str, Any]:
    content_chunks: List[str] = []
    for event in transcript:
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        if msg.get("role") != "assistant":
            continue
        for item in msg.get("content", []):
            if item.get("type") == "text":
                content_chunks.append(item.get("text", ""))
    raw_text = "\n".join(content_chunks).strip()
    if not raw_text:
        return {}

    # First, try to extract JSON from code blocks (```json ... ```)
    code_block_match = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL)
    if code_block_match:
        try:
            parsed = json.loads(code_block_match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Find all potential JSON objects by looking for balanced braces
    # We'll extract chunks that start with { and try to parse them
    json_candidates: List[str] = []
    brace_depth = 0
    current_json = []
    for char in raw_text:
        if char == "{":
            if brace_depth == 0:
                current_json = []
            brace_depth += 1

        if brace_depth > 0:
            current_json.append(char)

        if char == "}":
            brace_depth -= 1
            if brace_depth == 0 and current_json:
                json_candidates.append("".join(current_json))

    # Try parsing from the last JSON object backwards (most recent response)
    for candidate in reversed(json_candidates):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and "scores" in parsed:
                # Prefer JSON that has the expected structure
                return parsed
        except json.JSONDecodeError:
            continue

    # Try any valid JSON dict
    for candidate in reversed(json_candidates):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    logger.warning("Failed to parse judge JSON response")
    return {}
