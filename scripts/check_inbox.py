#!/usr/bin/env python3
"""check_inbox.py — Inbox check CLI for Claude sessions.

Reads pending messages from the MsgBus for a given recipient.

Usage:
    # Check inbox for cc-pool-1
    python3 scripts/check_inbox.py cc-pool-1

    # JSON output (for script consumption)
    python3 scripts/check_inbox.py cc-pool-1 --json

    # Peek without marking as read
    python3 scripts/check_inbox.py cc-pool-1 --peek

    # Limit results
    python3 scripts/check_inbox.py cc-pool-1 --limit 5

    # Acknowledge a message after processing
    python3 scripts/check_inbox.py --ack 42
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from msgbus import MsgBusConfig, init_db, receive, peek, ack, Message


def _format_message(msg: Message) -> str:
    status_icons = {"pending": "[P]", "read": "[R]", "processed": "[OK]", "expired": "[EX]"}
    icon = status_icons.get(msg.status, "[?]")
    reply_info = f" (reply to #{msg.reply_to})" if msg.reply_to else ""

    lines = [
        f"  {icon} #{msg.id} [{msg.msg_type}] from {msg.sender} P{msg.priority}{reply_info}",
        f"     {msg.created_at}",
    ]

    payload = msg.payload_dict
    if "text" in payload:
        lines.append(f"     {payload['text']}")
    elif "action" in payload:
        lines.append(f"     Action: {payload['action']}")
    else:
        lines.append(f"     {msg.payload[:120]}")

    return "\n".join(lines)


def _message_to_dict(msg: Message) -> dict:
    return {
        "id": msg.id,
        "sender": msg.sender,
        "msg_type": msg.msg_type,
        "priority": msg.priority,
        "payload": msg.payload_dict,
        "created_at": msg.created_at,
        "reply_to": msg.reply_to,
    }


def main():
    parser = argparse.ArgumentParser(description="Check MsgBus inbox")
    parser.add_argument("recipient", nargs="?", help="Recipient identifier (e.g., cc-pool-1)")
    parser.add_argument("--json", dest="as_json", action="store_true", help="JSON output")
    parser.add_argument("--peek", action="store_true", help="View without marking as read")
    parser.add_argument("--limit", type=int, default=10, help="Max messages to retrieve")
    parser.add_argument("--ack", type=int, default=None, dest="ack_id", help="Acknowledge message by ID")

    args = parser.parse_args()

    config = MsgBusConfig.default()
    init_db(config)

    if args.ack_id is not None:
        ack(config, args.ack_id)
        if args.as_json:
            print(json.dumps({"acked": args.ack_id}))
        else:
            print(f"Message #{args.ack_id} acknowledged")
        return

    if not args.recipient:
        parser.error("recipient is required (unless using --ack)")

    if args.peek:
        messages = peek(config, args.recipient, limit=args.limit)
    else:
        messages = receive(config, args.recipient, limit=args.limit)

    if args.as_json:
        print(json.dumps([_message_to_dict(m) for m in messages], ensure_ascii=False))
    elif not messages:
        print("No pending messages.")
    else:
        action = "peeked" if args.peek else "received"
        print(f"{len(messages)} message(s) {action}:\n")
        for msg in messages:
            print(_format_message(msg))
            print()


if __name__ == "__main__":
    main()
