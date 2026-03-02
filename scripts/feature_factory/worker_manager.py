"""Worker Manager — pool.sh wrapper + assignment tracking.

Manages worker lifecycle: assign roles, send tasks, detect completion,
elastic scaling, and idle cleanup.
"""

import logging
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional

from .config import (
    POOL_SH, DEFAULT_PROJECT_DIR, DAEMON_ID,
    BASE_POOL_SIZE, MAX_POOL_SIZE, IDLE_TIMEOUT,
    STAGE_ROLES, get_runtime_int,
)
from . import db
from . import token_gate

log = logging.getLogger("factory.worker")


@dataclass(frozen=True)
class WorkerState:
    worker_id: int
    exists: bool
    assignment: Optional[db.WorkerAssignment]

    @property
    def is_idle(self) -> bool:
        return self.exists and self.assignment is None


def _run_pool(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Execute a pool.sh command."""
    cmd = ["bash", POOL_SH, *args]
    log.debug("pool.sh: %s", " ".join(args))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _tmux_session_exists(name: str) -> bool:
    """Check if a tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def _list_pool_sessions() -> List[int]:
    """List all cc-pool-N session numbers."""
    try:
        result = subprocess.run(
            ["tmux", "ls", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        ids = []
        for line in result.stdout.strip().split("\n"):
            if line.startswith("cc-pool-"):
                try:
                    ids.append(int(line.split("-")[-1]))
                except ValueError:
                    pass
        return sorted(ids)
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


def _next_worker_id() -> int:
    """Find the next available worker ID."""
    existing = _list_pool_sessions()
    if not existing:
        return 1
    # Fill gaps first, then extend
    for i in range(1, max(existing) + 2):
        if i not in existing:
            return i
    return max(existing) + 1


# ── Public API ───────────────────────────────────────────────────────────────

def init_base_pool(project_dir: str = DEFAULT_PROJECT_DIR) -> List[int]:
    """Ensure base pool size workers are running. Returns created worker IDs."""
    existing = _list_pool_sessions()
    base_size = get_runtime_int("base_pool_size", BASE_POOL_SIZE)
    needed = base_size - len(existing)
    created = []

    if needed <= 0:
        log.info("Base pool OK: %d workers running", len(existing))
        return created

    log.info("Initializing %d base worker(s)", needed)
    result = _run_pool("init", str(needed), "--dir", project_dir)
    if result.returncode != 0:
        log.error("pool.sh init failed: %s", result.stderr)
        return created

    # Wait for sessions to come up
    time.sleep(2)
    new_sessions = _list_pool_sessions()
    created = [w for w in new_sessions if w not in existing]
    log.info("Created workers: %s", created)
    return created


def get_worker_state(worker_id: int) -> WorkerState:
    """Get the current state of a specific worker."""
    session_name = f"cc-pool-{worker_id}"
    exists = _tmux_session_exists(session_name)
    assignment = db.get_active_assignment_for_worker(worker_id)
    return WorkerState(worker_id=worker_id, exists=exists, assignment=assignment)


def get_all_worker_states() -> List[WorkerState]:
    """Get states for all pool workers."""
    session_ids = _list_pool_sessions()
    return [get_worker_state(wid) for wid in session_ids]


def find_idle_worker() -> Optional[int]:
    """Find an idle worker (exists + no active assignment). Returns worker_id or None."""
    assigned = set(db.get_assigned_worker_ids())
    for wid in _list_pool_sessions():
        if wid not in assigned:
            return wid
    return None


def ensure_worker_available(project_dir: str = DEFAULT_PROJECT_DIR) -> Optional[int]:
    """Get an idle worker, creating one if needed and within token budget. Returns worker_id or None."""
    idle = find_idle_worker()
    if idle is not None:
        return idle

    # Check token budget before scaling
    current_count = len(_list_pool_sessions())
    budget = token_gate.check_budget(current_count)

    if not budget.available:
        log.warning(
            "Cannot scale up: %s (source=%s, util=%.1f%%)",
            budget.reason, budget.source, budget.utilization_pct,
        )
        return None

    # Create a new worker
    new_id = _next_worker_id()
    log.info(
        "Scaling up: worker %d (budget: %.1f%% headroom, source=%s)",
        new_id, budget.headroom_pct, budget.source,
    )
    result = _run_pool("init", "1", "--dir", project_dir)
    if result.returncode != 0:
        log.error("Failed to create worker: %s", result.stderr)
        return None

    time.sleep(2)  # Wait for session to start
    if _tmux_session_exists(f"cc-pool-{new_id}"):
        return new_id

    # Fallback: check what was actually created
    after = _list_pool_sessions()
    for wid in after:
        if wid not in db.get_assigned_worker_ids():
            return wid
    return None


def assign_worker(
    worker_id: int,
    task_id: int,
    role: str,
    stage: str,
    task_message: str,
) -> Optional[int]:
    """Reset worker to role, send task, and create assignment. Returns assignment ID."""
    session_name = f"cc-pool-{worker_id}"
    if not _tmux_session_exists(session_name):
        log.error("Worker %d not found", worker_id)
        return None

    # Reset worker to the required role
    log.info("Assigning worker %d: role=%s, task=%d, stage=%s", worker_id, role, task_id, stage)
    reset_result = _run_pool("reset", str(worker_id), "--role", role)
    if reset_result.returncode != 0:
        log.error("Reset failed for worker %d: %s", worker_id, reset_result.stderr)
        return None

    # Wait for Claude Code to fully initialize (banner + input handler ready)
    time.sleep(15)

    # Send the task
    send_result = _run_pool("send", str(worker_id), task_message)
    if send_result.returncode != 0:
        log.error("Send failed for worker %d: %s", worker_id, send_result.stderr)
        return None

    # Record assignment in DB
    assignment_id = db.create_assignment(worker_id, task_id, role, stage)
    db.log_event(task_id, "worker_assign", {
        "worker_id": worker_id, "role": role, "stage": stage,
        "assignment_id": assignment_id,
    })

    return assignment_id


def release_worker(assignment_id: int, status: str = "completed") -> None:
    """Release a worker from its current assignment."""
    db.complete_assignment(assignment_id, status)
    log.info("Released assignment %d (status=%s)", assignment_id, status)


def cleanup_idle_workers() -> int:
    """Remove workers idle beyond timeout, keeping at least base pool size."""
    base_size = get_runtime_int("base_pool_size", BASE_POOL_SIZE)
    session_ids = _list_pool_sessions()
    if len(session_ids) <= base_size:
        return 0

    assigned = set(db.get_assigned_worker_ids())
    idle_workers = [wid for wid in session_ids if wid not in assigned]

    # Keep at least base pool size total
    removable_count = len(session_ids) - base_size
    if removable_count <= 0:
        return 0

    # Remove from highest ID first, never remove base pool (id=1)
    removed = 0
    for wid in sorted(idle_workers, reverse=True):
        if removed >= removable_count:
            break
        if wid <= base_size:
            continue

        session_name = f"cc-pool-{wid}"
        log.info("Cleanup: removing idle worker %d", wid)
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True, timeout=10,
            )
            removed += 1
        except subprocess.SubprocessError as e:
            log.warning("Failed to kill %s: %s", session_name, e)

    return removed


def get_role_for_stage(stage: str) -> str:
    """Get the appropriate worker role for a pipeline stage."""
    return STAGE_ROLES.get(stage, "coder")
