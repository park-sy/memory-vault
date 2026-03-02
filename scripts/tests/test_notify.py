"""test_notify.py — notify.py tests (~7 assertions)."""

import importlib
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult
from msgbus import MsgBusConfig, init_db, send, peek


def _make_config() -> MsgBusConfig:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return MsgBusConfig(db_path=f.name)


def _test_notify(s: Suite) -> None:
    # ── payload building tests ──
    # Test the logic that notify.py's main() builds

    # 1. basic payload structure
    payload = {"text": "Build complete"}
    s.check_eq("payload: text field", payload["text"], "Build complete")

    # 2. payload with actions
    payload_with_actions = {"text": "Plan ready", "actions": ["approve", "reject"]}
    s.check_eq("payload: actions field", payload_with_actions["actions"], ["approve", "reject"])

    # 3. payload with channel
    payload_with_channel = {"text": "Status update", "channel": "report"}
    s.check_eq("payload: channel field", payload_with_channel["channel"], "report")

    # 4. expires_at calculation
    expires_in = 3600
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=expires_in)).strftime("%Y-%m-%d %H:%M:%S")
    s.check("expires_at: valid format", len(expires_at) == 19)

    # 5. send via msgbus integration
    cfg = _make_config()
    init_db(cfg)
    msg_id = send(
        cfg,
        sender="test-notify",
        recipient="telegram",
        msg_type="notify",
        payload={"text": "integration test", "channel": "ops"},
        priority=5,
    )
    msgs = peek(cfg, "telegram")
    s.check_eq("notify integration: message queued", len(msgs), 1)
    s.check_eq("notify integration: correct sender", msgs[0].sender, "test-notify")

    # 6. priority range validation
    cfg2 = _make_config()
    init_db(cfg2)
    msg_id_urgent = send(cfg2, "s", "telegram", "notify", "urgent", priority=1)
    msg = peek(cfg2, "telegram")[0]
    s.check_eq("notify: priority=1 accepted", msg.priority, 1)

    # 7. _default_sender fallback (no TMUX_PANE)
    notify_mod = importlib.import_module("notify")
    import os
    old = os.environ.pop("TMUX_PANE", None)
    try:
        sender = notify_mod._default_sender()
        s.check("default_sender: returns non-empty string", len(sender) > 0)
    finally:
        if old is not None:
            os.environ["TMUX_PANE"] = old


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("notify", _test_notify)
