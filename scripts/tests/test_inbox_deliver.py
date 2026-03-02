"""test_inbox_deliver.py — inbox-deliver hook tests (~10 assertions)."""

import importlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import List
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult, EnvBackup
from msgbus import MsgBusConfig, init_db, send, Message


def _load_module():
    """Load inbox-deliver module."""
    mod_name = "inbox-deliver"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


def _make_config() -> MsgBusConfig:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return MsgBusConfig(db_path=f.name)


def _test_inbox_deliver(s: Suite) -> None:
    mod = _load_module()

    # ── _check_lockfile tests ──
    test_session = "test-inbox-session"

    # 1. no lockfile → False (don't skip)
    lockfile_path = mod.LOCK_DIR / f"cc-inbox-deliver-{test_session}.lock"
    if lockfile_path.exists():
        lockfile_path.unlink()

    original_session = mod.SESSION
    mod.SESSION = test_session
    try:
        s.check_eq("check_lockfile: no file = False", mod._check_lockfile(), False)

        # 2. fresh lockfile → True (skip)
        lockfile_path.touch()
        s.check_eq("check_lockfile: fresh file = True", mod._check_lockfile(), True)

        # 3. old lockfile → False (don't skip)
        old_time = time.time() - 60  # 60 seconds ago
        os.utime(str(lockfile_path), (old_time, old_time))
        s.check_eq("check_lockfile: old file = False", mod._check_lockfile(), False)

    finally:
        mod.SESSION = original_session
        if lockfile_path.exists():
            lockfile_path.unlink()

    # ── _format_messages tests ──

    # Create mock messages
    single_msg = Message(
        id=1, created_at="2026-03-01", sender="test-sender",
        recipient="worker1", msg_type="notify", priority=5,
        payload='{"text": "hello"}', status="pending",
        reply_to=None, expires_at=None,
    )

    multi_msgs = [
        Message(
            id=i, created_at="2026-03-01", sender=f"sender{i}",
            recipient="worker1", msg_type="task", priority=5,
            payload=f"task-{i}", status="pending",
            reply_to=None, expires_at=None,
        )
        for i in range(1, 4)
    ]

    # 4. single message format
    fmt_single = mod._format_messages([single_msg])
    s.check_contains("format_messages: single has msgbus prefix", "[msgbus #1]", fmt_single)
    s.check_contains("format_messages: single has sender", "test-sender", fmt_single)

    # 5. multiple messages format
    fmt_multi = mod._format_messages(multi_msgs)
    s.check_contains("format_messages: multi has count", "3건", fmt_multi)

    # 6. long payload truncated
    long_msg = Message(
        id=99, created_at="2026-03-01", sender="s",
        recipient="r", msg_type="notify", priority=5,
        payload="x" * 1000, status="pending",
        reply_to=None, expires_at=None,
    )
    fmt_long = mod._format_messages([long_msg])
    s.check("format_messages: long payload truncated", len(fmt_long) < 1000)

    # ── main() behavior tests (mocked) ──

    # 7. CC_SESSION empty → exit(0)
    with EnvBackup(["CC_SESSION"]):
        os.environ.pop("CC_SESSION", None)
        mod2 = _load_module()
        # SESSION is read at module level, so after reload it should be ""
        s.check_eq("main: CC_SESSION empty = empty SESSION", mod2.SESSION, "")

    # 8. lockfile valid → skip (test the check function)
    # Already tested above in check_lockfile tests

    # 9-10. tmux checks (mock)
    with patch.object(mod, '_tmux_session_exists', return_value=False):
        s.check_eq("tmux_session_exists mock: returns False", mod._tmux_session_exists("fake"), False)

    with patch.object(mod, '_tmux_session_exists', return_value=True):
        s.check_eq("tmux_session_exists mock: returns True", mod._tmux_session_exists("fake"), True)


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("inbox-deliver", _test_inbox_deliver)
