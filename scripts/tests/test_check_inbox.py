"""test_check_inbox.py — check_inbox.py tests (~6 assertions)."""

import json
import sys
import tempfile
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult
from msgbus import MsgBusConfig, init_db, send, receive, peek, ack, Message

# Import check_inbox formatting functions
from check_inbox import _format_message, _message_to_dict


def _make_config() -> MsgBusConfig:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return MsgBusConfig(db_path=f.name)


def _test_check_inbox(s: Suite) -> None:
    # ── _format_message tests ──

    msg = Message(
        id=42, created_at="2026-03-01 12:00:00", sender="orchestrator",
        recipient="cc-pool-1", msg_type="task", priority=3,
        payload='{"text": "Review auth module"}', status="pending",
        reply_to=None, expires_at=None,
    )

    # 1. format includes key fields
    formatted = _format_message(msg)
    s.check_contains("format_message: has id", "#42", formatted)
    s.check_contains("format_message: has sender", "orchestrator", formatted)

    # 2. format with reply_to
    msg_reply = Message(
        id=43, created_at="2026-03-01", sender="s",
        recipient="r", msg_type="result", priority=5,
        payload="done", status="read",
        reply_to=42, expires_at=None,
    )
    formatted_reply = _format_message(msg_reply)
    s.check_contains("format_message: has reply_to", "reply to #42", formatted_reply)

    # ── _message_to_dict tests ──

    # 3. dict structure
    d = _message_to_dict(msg)
    s.check_eq("message_to_dict: id", d["id"], 42)
    s.check_eq("message_to_dict: sender", d["sender"], "orchestrator")

    # ── peek vs receive state difference ──

    cfg = _make_config()
    init_db(cfg)
    send(cfg, "a", "inbox-test", "notify", {"text": "hello"})

    # 4. peek preserves pending
    peeked = peek(cfg, "inbox-test")
    s.check_eq("peek: returns 1 message", len(peeked), 1)

    # 5. peek again still returns
    peeked2 = peek(cfg, "inbox-test")
    s.check_eq("peek again: still returns 1", len(peeked2), 1)

    # 6. receive consumes
    received = receive(cfg, "inbox-test")
    remaining = peek(cfg, "inbox-test")
    s.check_eq("receive then peek: empty", len(remaining), 0)


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("check-inbox", _test_check_inbox)
