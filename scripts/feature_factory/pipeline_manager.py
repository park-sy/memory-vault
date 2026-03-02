"""Pipeline Manager — dev-queue CLI subprocess wrapper.

Calls whos-life feature dev-queue commands and parses JSON output.
All functions are pure wrappers: no state mutation, no side effects beyond subprocess calls.
"""

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from .config import WHOS_LIFE_CLI, WHOS_LIFE_PYTHON

log = logging.getLogger("factory.pipeline")


@dataclass(frozen=True)
class PipelineResult:
    success: bool
    data: dict
    error: Optional[str] = None


def _run_cli(*args: str, timeout: int = 30) -> PipelineResult:
    """Execute a whos-life CLI command and parse JSON output."""
    cmd = [WHOS_LIFE_PYTHON, WHOS_LIFE_CLI, "feature", "dev-queue", *args, "--json"]
    log.debug("CLI: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return PipelineResult(success=False, data={}, error="CLI timeout")
    except FileNotFoundError:
        return PipelineResult(
            success=False, data={},
            error=f"CLI not found: {WHOS_LIFE_CLI}",
        )

    if result.returncode != 0:
        # Try to parse stderr as JSON error
        error_msg = result.stderr.strip() or result.stdout.strip()
        try:
            err_data = json.loads(error_msg)
            error_msg = err_data.get("error", error_msg)
        except (json.JSONDecodeError, TypeError):
            pass
        return PipelineResult(success=False, data={}, error=error_msg)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return PipelineResult(
            success=False, data={},
            error=f"Invalid JSON output: {result.stdout[:200]}",
        )

    # Check for error in response data
    if isinstance(data, dict) and "error" in data:
        return PipelineResult(success=False, data=data, error=data["error"])

    return PipelineResult(success=True, data=data)


# ── Pipeline Commands ────────────────────────────────────────────────────────

def register_idea(title: str, description: str = "", category: str = "") -> PipelineResult:
    """Register a new idea in the pipeline."""
    args = ["register-idea", "--title", title]
    if description:
        args.extend(["--description", description])
    if category:
        args.extend(["--category", category])
    return _run_cli(*args)


def get_pipeline_status() -> PipelineResult:
    """Get pipeline status (stage counts)."""
    return _run_cli("get-pipeline-status")


def get_queue_status() -> PipelineResult:
    """Get full queue with all task details."""
    return _run_cli("get-queue-status")


def advance_stage(task_id: int, stage: str) -> PipelineResult:
    """Advance a task to a new stage."""
    return _run_cli("advance-stage", str(task_id), "--stage", stage)


def approve_to_queue(task_id: int) -> PipelineResult:
    """Approve spec → queued transition."""
    return _run_cli("approve-to-queue", str(task_id))


def approve_stable(task_id: int) -> PipelineResult:
    """Approve testing → stable transition."""
    return _run_cli("approve-stable", str(task_id))


def submit_plan(task_id: int, plan_json: str) -> PipelineResult:
    """Submit a plan for designing/coding stage."""
    return _run_cli("submit-plan", str(task_id), "--plan-json", plan_json)


def approve_plan(task_id: int) -> PipelineResult:
    """Approve a pending plan."""
    return _run_cli("approve-plan", str(task_id))


def reject_plan(task_id: int, reason: str = "") -> PipelineResult:
    """Reject a pending plan."""
    args = ["reject-plan", str(task_id)]
    if reason:
        args.extend(["--reason", reason])
    return _run_cli(*args)


def get_plan(task_id: int) -> PipelineResult:
    """Get the current plan for a task."""
    return _run_cli("get-plan", str(task_id))


def record_test_run(task_id: int, success: bool, log_text: str = "") -> PipelineResult:
    """Record a test run result."""
    args = ["record-test-run", str(task_id)]
    if success:
        args.append("--success")
    if log_text:
        args.extend(["--log", log_text])
    return _run_cli(*args)


def get_task_detail(task_id: int) -> PipelineResult:
    """Get details for a specific task from the queue."""
    result = get_queue_status()
    if not result.success:
        return result
    items = result.data.get("items", [])
    for item in items:
        if item.get("id") == task_id:
            return PipelineResult(success=True, data=item)
    return PipelineResult(success=False, data={}, error=f"Task {task_id} not found")
