#!/usr/bin/env python3
"""notify.py — Outbound notification CLI for Claude sessions.

Sends notifications through the MsgBus. The telegram_bridge daemon
picks up messages with recipient="telegram" and forwards them.

Usage:
    # Simple text notification
    python3 scripts/notify.py "Build complete"

    # Notification with inline action buttons
    python3 scripts/notify.py "Plan ready for review" --actions approve reject

    # Specify sender (defaults to hostname or "claude")
    python3 scripts/notify.py "Task done" --sender cc-pool-1

    # Set priority (1=urgent, 5=normal, 9=low)
    python3 scripts/notify.py "CRITICAL: Token limit" --priority 1

    # Set expiration
    python3 scripts/notify.py "Review by EOD" --expires-in 3600

    # Send to specific topic channel
    python3 scripts/notify.py "Plan ready" --channel approval --actions approve reject
    python3 scripts/notify.py "Build done" --channel report
"""

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow importing sibling modules
sys.path.insert(0, str(Path(__file__).parent))

from msgbus import MsgBusConfig, init_db, send


def _default_sender() -> str:
    """Derive sender name from TMUX pane or hostname."""
    tmux_pane = os.environ.get("TMUX_PANE", "")
    if tmux_pane:
        # Try to get tmux session name
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#S"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
    return socket.gethostname()


def main():
    parser = argparse.ArgumentParser(
        description="Send notifications via MsgBus (picked up by telegram_bridge)"
    )
    parser.add_argument("message", help="Notification message text")
    parser.add_argument(
        "--actions", nargs="+", default=None,
        help="Inline action buttons (e.g., approve reject defer)",
    )
    parser.add_argument(
        "--sender", default=None,
        help="Sender identifier (default: tmux session name or hostname)",
    )
    parser.add_argument(
        "--priority", type=int, default=5, choices=range(1, 10),
        help="Priority 1-9 (1=urgent, 5=normal)",
    )
    parser.add_argument(
        "--expires-in", type=int, default=None,
        help="Seconds until message expires",
    )
    parser.add_argument(
        "--recipient", default="telegram",
        help="Recipient (default: telegram)",
    )
    parser.add_argument(
        "--channel", default=None,
        choices=["ops", "approval", "report", "clone"],
        help="Telegram topic channel",
    )

    args = parser.parse_args()

    sender = args.sender or _default_sender()

    payload = {"text": args.message}
    if args.actions:
        payload["actions"] = args.actions
    if args.channel:
        payload["channel"] = args.channel

    expires_at = None
    if args.expires_in:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=args.expires_in)).strftime("%Y-%m-%d %H:%M:%S")

    config = MsgBusConfig.default()
    init_db(config)

    msg_id = send(
        config,
        sender=sender,
        recipient=args.recipient,
        msg_type="notify",
        payload=payload,
        priority=args.priority,
        expires_at=expires_at,
    )

    print(json.dumps({"msg_id": msg_id, "sender": sender, "recipient": args.recipient}))


if __name__ == "__main__":
    main()
