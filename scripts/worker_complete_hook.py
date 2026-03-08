#!/usr/bin/env python3
"""Worker completion hook — Claude Code Stop hook.

워커(cc-pool-N)의 turn이 끝날 때 발동.
활성 assignment가 있고, AskUserQuestion/plan-approval 상태가 아니면
stage_complete 알림을 자동 전송.

등록: ~/.claude/settings.json → hooks.Stop
"""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
FACTORY_DB = VAULT_DIR / "storage" / "feature-factory.db"

# Claude Code 입력 대기 패턴 — 이 상태면 작업이 아직 진행 중
SKIP_PATTERNS = [
    "Enter to select",    # AskUserQuestion 선택지
    "Type something",     # 자유 입력
    "Tab/Arrow keys",     # 네비게이션
    "Plan mode",          # plan 작성 중
    "Waiting for",        # plan 승인 대기
]


def main() -> None:
    session = os.environ.get("CC_SESSION_NAME", "")
    if not session.startswith("cc-pool-"):
        return

    try:
        worker_id = int(session.split("-")[-1])
    except ValueError:
        return

    assignment = _get_active_assignment(worker_id)
    if not assignment:
        return

    task_id, stage = assignment

    output = _capture_tmux(session)
    if not output:
        return

    if any(p in output for p in SKIP_PATTERNS):
        return

    _send_completion(task_id, stage, worker_id)


def _get_active_assignment(worker_id: int):
    """factory DB에서 활성 assignment 조회. Returns (task_id, stage) or None."""
    if not FACTORY_DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(FACTORY_DB), timeout=5)
        try:
            row = conn.execute(
                "SELECT task_id, stage FROM worker_assignments "
                "WHERE worker_id = ? AND status = 'assigned' "
                "ORDER BY assigned_at DESC LIMIT 1",
                (worker_id,),
            ).fetchone()
            return row  # (task_id, stage) or None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _capture_tmux(session: str):
    """tmux scrollback 캡처 (마지막 50줄). Returns stdout or None."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session, "-p", "-S", "-50"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout if result.returncode == 0 else None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _send_completion(task_id: int, stage: str, worker_id: int) -> None:
    """notify.py로 stage_complete 이벤트 전송."""
    payload = json.dumps({
        "event": "stage_complete",
        "stage": stage,
        "task_id": task_id,
    })
    notify_script = VAULT_DIR / "scripts" / "notify.py"
    try:
        subprocess.run(
            [
                sys.executable, str(notify_script),
                payload,
                "--sender", f"cc-pool-{worker_id}",
                "--recipient", "cc-factory",
                "--channel", "ops",
            ],
            capture_output=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        pass


if __name__ == "__main__":
    main()
