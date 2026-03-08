#!/usr/bin/env python3
"""Unified Scheduler — 통합 스케줄러.

launchd가 5분마다 tick을 호출. 등록된 작업의 schedule + conditions를 평가해서
충족된 작업만 실행한다.

Usage:
    python3 scripts/scheduler.py tick
    python3 scripts/scheduler.py status
    python3 scripts/scheduler.py add <id> <name> <schedule> <command> [--type TYPE] [--conditions JSON]
    python3 scripts/scheduler.py enable <id>
    python3 scripts/scheduler.py disable <id>
    python3 scripts/scheduler.py run <id>
    python3 scripts/scheduler.py log [--job ID] [--last N]
    python3 scripts/scheduler.py install
    python3 scripts/scheduler.py uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

VAULT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = VAULT_DIR / "storage" / "scheduler.db"
LOG_DIR = VAULT_DIR / "storage" / "logs"
PLIST_LABEL = "com.memoryvault.scheduler"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"

# tmux socket for launchd compatibility
TMUX_SOCKET = f"/private/tmp/tmux-{os.getuid()}/default"


# ── DB ─────────────────────────────────────────────────────────────────────


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            schedule TEXT NOT NULL,
            conditions TEXT NOT NULL DEFAULT '{}',
            command TEXT NOT NULL,
            command_type TEXT NOT NULL DEFAULT 'script',
            last_run TEXT,
            last_result TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            timeout INTEGER NOT NULL DEFAULT 300
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            exit_code INTEGER,
            output_summary TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)
    conn.commit()
    return conn


# ── Cron Parsing ───────────────────────────────────────────────────────────


def _match_cron_field(field: str, value: int, max_val: int) -> bool:
    """Match a single cron field against a value."""
    for part in field.split(","):
        part = part.strip()
        # */N — every N
        if part.startswith("*/"):
            step = int(part[2:])
            if step > 0 and value % step == 0:
                return True
        # N-M — range
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
        # * — any
        elif part == "*":
            return True
        # exact number
        else:
            if int(part) == value:
                return True
    return False


def _cron_matches(schedule: str, now: datetime) -> bool:
    """Check if a cron expression matches the given datetime.

    Format: minute hour day_of_month month day_of_week
    """
    parts = schedule.split()
    if len(parts) != 5:
        return False

    minute, hour, dom, month, dow = parts
    return (
        _match_cron_field(minute, now.minute, 59)
        and _match_cron_field(hour, now.hour, 23)
        and _match_cron_field(dom, now.day, 31)
        and _match_cron_field(month, now.month, 12)
        and _match_cron_field(dow, now.weekday(), 6)  # 0=Mon
    )


# ── Token Monitor Query ────────────────────────────────────────────────────

WHOS_LIFE_DIR = Path.home() / "dev" / "whos-life"
WHOS_LIFE_CLI = str(WHOS_LIFE_DIR / "cli.py")


def _query_token_remaining() -> float | None:
    """Query whos-life token-monitor for remaining token %.

    Returns 100 - max_utilization, or None if unavailable.
    Fallback pattern: failure → None → condition passes.
    """
    if not WHOS_LIFE_DIR.exists():
        return None

    try:
        result = subprocess.run(
            [
                sys.executable, WHOS_LIFE_CLI,
                "feature", "token-monitor", "get-status", "--json",
            ],
            capture_output=True, text=True, timeout=15,
            cwd=str(WHOS_LIFE_DIR),
        )

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        windows = data.get("windows", data.get("rate_limits", []))
        if not windows:
            return None

        max_util = max(
            float(w.get("utilization", w.get("utilization_pct", 0)))
            for w in windows
        )
        return 100.0 - max_util

    except (subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return None


# ── Conditions ─────────────────────────────────────────────────────────────


def _check_conditions(conditions_json: str, last_run: str) -> tuple:
    """Evaluate all conditions. Returns (passed: bool, reason: str)."""
    try:
        conds = json.loads(conditions_json) if conditions_json else {}
    except json.JSONDecodeError:
        return False, "invalid conditions JSON"

    if not conds:
        return True, ""

    now = datetime.now()

    # time_range: "HH:MM-HH:MM"
    if "time_range" in conds:
        try:
            start_s, end_s = conds["time_range"].split("-")
            sh, sm = map(int, start_s.split(":"))
            eh, em = map(int, end_s.split(":"))
            start_min = sh * 60 + sm
            end_min = eh * 60 + em
            now_min = now.hour * 60 + now.minute
            if start_min <= end_min:
                if not (start_min <= now_min <= end_min):
                    return False, f"outside time_range {conds['time_range']}"
            else:  # overnight range like 23:00-06:00
                if not (now_min >= start_min or now_min <= end_min):
                    return False, f"outside time_range {conds['time_range']}"
        except (ValueError, AttributeError):
            return False, "invalid time_range format"

    # day_of_week: [0=Mon, ..., 6=Sun]
    if "day_of_week" in conds:
        if now.weekday() not in conds["day_of_week"]:
            return False, f"wrong day_of_week (today={now.weekday()})"

    # min_interval_hours
    if "min_interval_hours" in conds and last_run:
        try:
            last_dt = datetime.fromisoformat(last_run)
            hours_since = (now - last_dt).total_seconds() / 3600
            if hours_since < conds["min_interval_hours"]:
                return False, f"min_interval {conds['min_interval_hours']}h (last: {hours_since:.1f}h ago)"
        except (ValueError, TypeError):
            pass

    # require_service: check tmux session exists
    if "require_service" in conds:
        svc = conds["require_service"]
        session_map = {"bridge": "cc-telegram-bridge", "factory": "cc-factory"}
        session_name = session_map.get(svc, svc)
        ret = subprocess.run(
            ["tmux", "-S", TMUX_SOCKET, "has-session", "-t", session_name],
            capture_output=True,
        )
        if ret.returncode != 0:
            return False, f"service {svc} not running"

    # no_active_workers: check pool status
    if conds.get("no_active_workers"):
        ret = subprocess.run(
            ["tmux", "-S", TMUX_SOCKET, "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if ret.returncode == 0:
            sessions = ret.stdout.strip().split("\n")
            active = [s for s in sessions if s.startswith("cc-pool-")]
            if active:
                return False, f"active workers: {len(active)}"

    # token_remaining_pct: query whos-life token-monitor for rate limit utilization
    if "token_remaining_pct" in conds:
        threshold = float(conds["token_remaining_pct"])
        remaining = _query_token_remaining()
        if remaining is not None and remaining < threshold:
            return False, f"token_remaining {remaining:.1f}% < {threshold:.0f}%"
        # remaining is None → monitor unavailable → pass (fallback)

    return True, ""


# ── Execution ──────────────────────────────────────────────────────────────


def _execute_job(job: dict) -> tuple:
    """Execute a job. Returns (exit_code, output_summary)."""
    cmd_type = job["command_type"]
    command = job["command"]
    timeout = job["timeout"]

    if cmd_type == "script":
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(VAULT_DIR),
                env={**os.environ, "PATH": f"/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}"},
            )
            output = (result.stdout + result.stderr)[-500:]
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return -1, f"timeout after {timeout}s"
        except Exception as e:
            return -2, str(e)[-500:]

    elif cmd_type == "claude-session":
        session_name = f"sched-{job['id']}"
        # Check if session already running
        ret = subprocess.run(
            ["tmux", "-S", TMUX_SOCKET, "has-session", "-t", session_name],
            capture_output=True,
        )
        if ret.returncode == 0:
            return -3, "session already running"

        # Spawn claude in tmux with log output
        log_file = LOG_DIR / f"{session_name}.log"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        claude_bin = Path.home() / ".local" / "bin" / "claude"
        claude_cmd = f"'{claude_bin}' -p '{command}' 2>&1 | tee '{log_file}'"
        try:
            subprocess.run(
                [
                    "tmux", "-S", TMUX_SOCKET,
                    "new-session", "-d", "-s", session_name,
                    "-c", str(VAULT_DIR),
                    claude_cmd,
                ],
                capture_output=True,
                timeout=10,
            )
            return 0, f"spawned tmux session {session_name} (log: {log_file})"
        except Exception as e:
            return -2, str(e)[-500:]

    elif cmd_type == "tmux-send":
        # Send command to existing tmux session
        parts = command.split(" ", 1)
        if len(parts) != 2:
            return -4, "tmux-send format: 'session_name command'"
        session_name, send_cmd = parts
        try:
            subprocess.run(
                [
                    "tmux", "-S", TMUX_SOCKET,
                    "send-keys", "-t", session_name,
                    send_cmd, "Enter",
                ],
                capture_output=True,
                timeout=10,
            )
            return 0, f"sent to {session_name}"
        except Exception as e:
            return -2, str(e)[-500:]

    return -5, f"unknown command_type: {cmd_type}"


# ── Commands ───────────────────────────────────────────────────────────────


def cmd_tick(args) -> None:
    """Evaluate and run due jobs."""
    now = datetime.now()
    db = _get_db()

    jobs = db.execute("SELECT * FROM jobs WHERE enabled = 1").fetchall()
    if not jobs:
        return

    for job in jobs:
        job_dict = dict(job)

        # Check cron schedule
        if not _cron_matches(job_dict["schedule"], now):
            continue

        # Check conditions
        passed, reason = _check_conditions(job_dict["conditions"], job_dict["last_run"])
        if not passed:
            _log(f"[SKIP] {job_dict['id']}: {reason}")
            continue

        # Execute
        _log(f"[RUN] {job_dict['id']}: {job_dict['command']}")
        started_at = now.isoformat()

        exit_code, output = _execute_job(job_dict)
        finished_at = datetime.now().isoformat()

        result = "success" if exit_code == 0 else "failed"

        db.execute(
            "UPDATE jobs SET last_run = ?, last_result = ? WHERE id = ?",
            (finished_at, result, job_dict["id"]),
        )
        db.execute(
            "INSERT INTO run_log (job_id, started_at, finished_at, exit_code, output_summary) VALUES (?, ?, ?, ?, ?)",
            (job_dict["id"], started_at, finished_at, exit_code, output),
        )
        db.commit()

        _log(f"[{result.upper()}] {job_dict['id']}: exit={exit_code}")


def cmd_status(args) -> None:
    """Show all jobs and their status."""
    db = _get_db()
    jobs = db.execute("SELECT * FROM jobs ORDER BY enabled DESC, id").fetchall()

    if not jobs:
        print("No jobs registered.")
        return

    print(f"{'ID':<22} {'Enabled':>7} {'Schedule':<16} {'Type':<15} {'Last Run':<20} {'Result':<8}")
    print("-" * 95)

    for job in jobs:
        enabled = "ON" if job["enabled"] else "OFF"
        last_run = job["last_run"][:16] if job["last_run"] else "-"
        result = job["last_result"] or "-"
        print(
            f"{job['id']:<22} {enabled:>7} {job['schedule']:<16} "
            f"{job['command_type']:<15} {last_run:<20} {result:<8}"
        )

    print(f"\nTotal: {len(jobs)} jobs")


def cmd_add(args) -> None:
    """Register a new job."""
    db = _get_db()
    try:
        db.execute(
            """INSERT INTO jobs (id, name, schedule, command, command_type, conditions, timeout, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                args.id,
                args.name,
                args.schedule,
                args.cmd,
                args.type,
                args.conditions,
                args.timeout,
            ),
        )
        db.commit()
        print(f"Added job: {args.id}")
    except sqlite3.IntegrityError:
        print(f"Error: job '{args.id}' already exists.")
        sys.exit(1)


def cmd_enable(args) -> None:
    """Enable a job."""
    db = _get_db()
    db.execute("UPDATE jobs SET enabled = 1 WHERE id = ?", (args.id,))
    db.commit()
    print(f"Enabled: {args.id}")


def cmd_disable(args) -> None:
    """Disable a job."""
    db = _get_db()
    db.execute("UPDATE jobs SET enabled = 0 WHERE id = ?", (args.id,))
    db.commit()
    print(f"Disabled: {args.id}")


def cmd_run(args) -> None:
    """Run a job immediately, ignoring schedule and conditions."""
    db = _get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (args.id,)).fetchone()
    if not job:
        print(f"Error: job '{args.id}' not found.")
        sys.exit(1)

    job_dict = dict(job)
    print(f"Running {args.id}...")

    started_at = datetime.now().isoformat()
    exit_code, output = _execute_job(job_dict)
    finished_at = datetime.now().isoformat()

    result = "success" if exit_code == 0 else "failed"

    db.execute(
        "UPDATE jobs SET last_run = ?, last_result = ? WHERE id = ?",
        (finished_at, result, args.id),
    )
    db.execute(
        "INSERT INTO run_log (job_id, started_at, finished_at, exit_code, output_summary) VALUES (?, ?, ?, ?, ?)",
        (args.id, started_at, finished_at, exit_code, output),
    )
    db.commit()

    print(f"Result: {result} (exit={exit_code})")
    if output.strip():
        print(f"Output: {output.strip()[:200]}")


def cmd_log(args) -> None:
    """Show run log."""
    db = _get_db()
    query = "SELECT * FROM run_log"
    params = []

    if args.job:
        query += " WHERE job_id = ?"
        params.append(args.job)

    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(args.last)

    rows = db.execute(query, params).fetchall()

    if not rows:
        print("No log entries.")
        return

    print(f"{'ID':>5} {'Job':<22} {'Started':<20} {'Exit':>4} {'Result'}")
    print("-" * 80)

    for row in rows:
        started = row["started_at"][:16] if row["started_at"] else "-"
        output = (row["output_summary"] or "")[:60].replace("\n", " ")
        print(f"{row['id']:>5} {row['job_id']:<22} {started:<20} {row['exit_code'] or 0:>4} {output}")


def cmd_install(args) -> None:
    """Install launchd plist for scheduler."""
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>{VAULT_DIR / 'scripts' / 'scheduler.py'}</string>
        <string>tick</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_DIR / 'scheduler.log'}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_DIR / 'scheduler.log'}</string>
    <key>WorkingDirectory</key>
    <string>{VAULT_DIR}</string>
</dict>
</plist>"""

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist_content)

    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)

    print(f"Installed: {PLIST_PATH}")
    print("Scheduler will tick every 5 minutes.")


def cmd_uninstall(args) -> None:
    """Uninstall launchd plist."""
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        PLIST_PATH.unlink()
        print(f"Uninstalled: {PLIST_PATH}")
    else:
        print("Plist not found — nothing to uninstall.")


def cmd_seed(args) -> None:
    """Register initial jobs."""
    db = _get_db()

    initial_jobs = [
        (
            "healthcheck",
            "서비스 상태 확인",
            "*/1 * * * *",
            "bash scripts/healthcheck.sh",
            "script",
            "{}",
            120,
        ),
        (
            "workflow-optimizer",
            "워크플로우 최적화 탐색",
            "0 2 * * *",
            "최적화 해줘. memory.md 읽고 활성 과제부터 진행.",
            "claude-session",
            json.dumps({"time_range": "01:00-06:00", "min_interval_hours": 20}),
            1800,
        ),
        (
            "memory-archiver",
            "기억 아카이브",
            "0 4 * * 0",
            "python3 scripts/memory-archiver.py",
            "script",
            json.dumps({"min_interval_hours": 144}),
            300,
        ),
        (
            "synthesize-decisions",
            "의사결정 프로필 합성",
            "0 3 * * 1",
            "python3 scripts/decision-clone.py synthesize",
            "script",
            json.dumps({"min_interval_hours": 144}),
            120,
        ),
    ]

    added = 0
    for job_id, name, schedule, command, cmd_type, conditions, timeout in initial_jobs:
        try:
            db.execute(
                """INSERT INTO jobs (id, name, schedule, command, command_type, conditions, timeout, enabled)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (job_id, name, schedule, command, cmd_type, conditions, timeout),
            )
            added += 1
            print(f"  Added: {job_id}")
        except sqlite3.IntegrityError:
            print(f"  Exists: {job_id}")

    db.commit()
    print(f"\nSeeded {added} jobs.")


# ── Logging ────────────────────────────────────────────────────────────────


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "scheduler.log"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"{ts} {msg}\n")


# ── Main ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified Scheduler — 통합 스케줄러",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("tick", help="Evaluate and run due jobs")
    sub.add_parser("status", help="Show all jobs")

    p_add = sub.add_parser("add", help="Register a new job")
    p_add.add_argument("id", help="Job ID")
    p_add.add_argument("name", help="Display name")
    p_add.add_argument("schedule", help="Cron expression (5 fields)")
    p_add.add_argument("cmd", help="Command to execute")
    p_add.add_argument("--type", default="script", choices=["script", "claude-session", "tmux-send"])
    p_add.add_argument("--conditions", default="{}", help="JSON conditions")
    p_add.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")

    p_enable = sub.add_parser("enable", help="Enable a job")
    p_enable.add_argument("id")

    p_disable = sub.add_parser("disable", help="Disable a job")
    p_disable.add_argument("id")

    p_run = sub.add_parser("run", help="Run a job now (ignore conditions)")
    p_run.add_argument("id")

    p_log = sub.add_parser("log", help="Show run log")
    p_log.add_argument("--job", default=None, help="Filter by job ID")
    p_log.add_argument("--last", type=int, default=20, help="Number of entries")

    sub.add_parser("install", help="Install launchd plist")
    sub.add_parser("uninstall", help="Uninstall launchd plist")
    sub.add_parser("seed", help="Register initial jobs")

    args = parser.parse_args()

    commands = {
        "tick": cmd_tick,
        "status": cmd_status,
        "add": cmd_add,
        "enable": cmd_enable,
        "disable": cmd_disable,
        "run": cmd_run,
        "log": cmd_log,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "seed": cmd_seed,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
