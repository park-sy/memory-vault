#!/usr/bin/env python3
"""Feature Factory — automated Feature Pipeline orchestration daemon.

Python daemon (Level 0) that drives the Feature Pipeline.
LLM is only used inside workers; the daemon itself is pure code.

Start:
    python3 scripts/feature-factory.py

    # Or in a tmux session:
    tmux new-session -d -s cc-factory \
      -c ~/dev/memory-vault \
      "python3 scripts/feature-factory.py"

Daemon ID: cc-factory
"""

import json
import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure package imports work
sys.path.insert(0, str(Path(__file__).parent))

from feature_factory.config import (
    DAEMON_ID, TICK_INTERVAL, HOUSEKEEP_INTERVAL,
    DEFAULT_PROJECT_DIR, STORAGE_DIR,
)
from feature_factory import db
from feature_factory import dispatcher
from feature_factory import worker_manager as wm
from feature_factory import approval_handler
from feature_factory import health_check
from feature_factory import recovery


# ── Logging ──────────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    """Set up console + rotating JSON file logging."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler (human-readable)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # JSON file handler (machine-readable, rotating)
    log_dir = STORAGE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "feature-factory.jsonl"

    file_handler = logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(_JsonFormatter())
    root.addHandler(file_handler)


class _JsonFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


log = logging.getLogger("factory")


# ── Daemon ───────────────────────────────────────────────────────────────────

class FeatureFactory:
    """Main event loop for the Feature Factory daemon."""

    def __init__(self) -> None:
        self.running = False
        self.last_housekeep = 0.0
        self.tick_count = 0

    def run(self) -> None:
        """Start the main event loop."""
        self.running = True

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # Initialize DB
        db.init_db()
        log.info("Feature Factory started (id=%s)", DAEMON_ID)
        log.info("DB: %s", db.FACTORY_DB_PATH)
        log.info("Supervision: %s", db.get_config("supervision") or "on")

        # Write PID file
        pid_file = STORAGE_DIR / "feature-factory.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))

        # Startup recovery — resume from DB state
        try:
            recovery.recover_from_db()
        except Exception as e:
            log.error("Recovery failed: %s", e)

        # Initialize base worker pool
        try:
            wm.init_base_pool(DEFAULT_PROJECT_DIR)
        except Exception as e:
            log.warning("Base pool init failed (will retry): %s", e)

        try:
            while self.running:
                self._tick()
                time.sleep(TICK_INTERVAL)
        finally:
            pid_file.unlink(missing_ok=True)
            log.info("Feature Factory stopped.")

    def _tick(self) -> None:
        """Single iteration of the main loop."""
        self.tick_count += 1

        try:
            # 1. Poll inbox for new messages
            messages = dispatcher.poll_inbox()
            for msg in messages:
                try:
                    dispatcher.dispatch(msg)
                except Exception as e:
                    log.error("Dispatch error for msg #%d: %s", msg.id, e)

            # 2. Drive pipeline state machine
            dispatcher.tick_pipeline()

            # 3. Housekeeping (every HOUSEKEEP_INTERVAL seconds)
            now = time.time()
            if now - self.last_housekeep > HOUSEKEEP_INTERVAL:
                self._housekeep()
                self.last_housekeep = now

        except Exception as e:
            log.error("Tick error: %s", e)

    def _housekeep(self) -> None:
        """Periodic maintenance tasks."""
        # Health check — crashed/stalled workers
        try:
            health_check.check_worker_health()
        except Exception as e:
            log.warning("Health check error: %s", e)

        # Check approval timeouts
        try:
            reminded = approval_handler.check_timeouts()
            if reminded:
                log.info("Sent %d approval timeout reminder(s)", reminded)
        except Exception as e:
            log.warning("Approval timeout check error: %s", e)

        # Clean up idle workers
        try:
            removed = wm.cleanup_idle_workers()
            if removed:
                log.info("Cleaned up %d idle worker(s)", removed)
        except Exception as e:
            log.warning("Worker cleanup error: %s", e)

    def _handle_signal(self, signum: int, frame) -> None:
        log.info("Signal %d received, shutting down...", signum)
        self.running = False


# ── Entry Point ──────────────────────────────────────────────────────────────

def main() -> None:
    _setup_logging()
    factory = FeatureFactory()
    factory.run()


if __name__ == "__main__":
    main()
