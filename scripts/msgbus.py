#!/usr/bin/env python3
"""msgbus.py — SQLite Message Bus for cross-platform communication.

Platform-independent message bus with channel reference mapping.
Extends the message bus with channel_refs for Telegram/Slack/etc.

Usage (Library):
    from msgbus import MsgBusConfig, init_db, send, receive, ack

    config = MsgBusConfig.default()
    init_db(config)
    msg_id = send(config, "cc-pool-1", "telegram", "notify", {"text": "hi"})
    messages = receive(config, "cc-pool-1")
    ack(config, msg_id)

Usage (CLI):
    python3 msgbus.py init
    python3 msgbus.py send --from X --to Y --type notify --payload '{"text":"hi"}'
    python3 msgbus.py receive <recipient>
    python3 msgbus.py ack <msg_id>
    python3 msgbus.py link <msg_id> <channel> <channel_msg_id>
    python3 msgbus.py find-by-channel <channel> <channel_msg_id>
    python3 msgbus.py cleanup [--days 7]
    python3 msgbus.py status
"""

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Union


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MsgBusConfig:
    db_path: str
    wal_mode: bool = True

    @staticmethod
    def default():
        db = str(Path(__file__).parent.parent / "storage" / "msgbus.db")
        return MsgBusConfig(db_path=db)


@dataclass(frozen=True)
class Message:
    id: int
    created_at: str
    sender: str
    recipient: str
    msg_type: str
    priority: int
    payload: str
    status: str
    reply_to: Optional[int]
    expires_at: Optional[str]

    @property
    def payload_dict(self) -> dict:
        try:
            return json.loads(self.payload)
        except (json.JSONDecodeError, TypeError):
            return {"raw": self.payload}


@dataclass(frozen=True)
class ChannelRef:
    id: int
    message_id: int
    channel: str
    channel_msg_id: str


# ── Constants ────────────────────────────────────────────────────────────────

VALID_MSG_TYPES = (
    "task", "result", "query", "ack", "broadcast",
    "handoff", "notify", "command", "callback",
)

VALID_STATUSES = ("pending", "read", "processed", "expired")

SCHEMA = """\
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT DEFAULT (datetime('now')),
    sender      TEXT NOT NULL,
    recipient   TEXT NOT NULL,
    msg_type    TEXT NOT NULL,
    priority    INTEGER DEFAULT 5 CHECK(priority BETWEEN 1 AND 9),
    payload     TEXT NOT NULL,
    status      TEXT DEFAULT 'pending' CHECK(status IN ('pending','read','processed','expired')),
    reply_to    INTEGER REFERENCES messages(id),
    expires_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_msg_recipient_status ON messages(recipient, status);
CREATE INDEX IF NOT EXISTS idx_msg_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_msg_reply_to ON messages(reply_to);

CREATE TABLE IF NOT EXISTS channel_refs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    channel         TEXT NOT NULL,
    channel_msg_id  TEXT NOT NULL,
    UNIQUE(message_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_channel_lookup ON channel_refs(channel, channel_msg_id);
"""


# ── Database Connection ──────────────────────────────────────────────────────

@contextmanager
def _connect(config: MsgBusConfig):
    """Context manager for database connections with WAL mode and Row factory."""
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.db_path)
    conn.row_factory = sqlite3.Row
    if config.wal_mode:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        created_at=row["created_at"],
        sender=row["sender"],
        recipient=row["recipient"],
        msg_type=row["msg_type"],
        priority=row["priority"],
        payload=row["payload"],
        status=row["status"],
        reply_to=row["reply_to"],
        expires_at=row["expires_at"],
    )


def _row_to_channel_ref(row: sqlite3.Row) -> ChannelRef:
    return ChannelRef(
        id=row["id"],
        message_id=row["message_id"],
        channel=row["channel"],
        channel_msg_id=row["channel_msg_id"],
    )


# ── Public API ───────────────────────────────────────────────────────────────

def init_db(config: MsgBusConfig) -> None:
    """Create tables and indexes (idempotent)."""
    with _connect(config) as conn:
        conn.executescript(SCHEMA)


def send(
    config: MsgBusConfig,
    sender: str,
    recipient: str,
    msg_type: str,
    payload: Union[dict, list, str],
    priority: int = 5,
    reply_to: Optional[int] = None,
    expires_at: Optional[str] = None,
) -> int:
    """Send a message. Returns the new message ID."""
    if msg_type not in VALID_MSG_TYPES:
        raise ValueError(f"Invalid msg_type: {msg_type}. Must be one of {VALID_MSG_TYPES}")
    if not 1 <= priority <= 9:
        raise ValueError(f"Priority must be 1-9, got {priority}")

    payload_str = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)

    with _connect(config) as conn:
        cur = conn.execute(
            """INSERT INTO messages
               (sender, recipient, msg_type, priority, payload, reply_to, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sender, recipient, msg_type, priority, payload_str, reply_to, expires_at),
        )
        return cur.lastrowid


def receive(config: MsgBusConfig, recipient: str, limit: int = 10) -> List[Message]:
    """Fetch pending messages for recipient. Atomically marks them as 'read'."""
    with _connect(config) as conn:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE recipient = ? AND status = 'pending'
               ORDER BY priority ASC, created_at ASC
               LIMIT ?""",
            (recipient, limit),
        ).fetchall()

        messages = [_row_to_message(row) for row in rows]
        if messages:
            ids = [m.id for m in messages]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE messages SET status = 'read' WHERE id IN ({placeholders})",
                ids,
            )
        return messages


def peek(config: MsgBusConfig, recipient: str, limit: int = 10) -> List[Message]:
    """View pending messages without marking as read."""
    with _connect(config) as conn:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE recipient = ? AND status = 'pending'
               ORDER BY priority ASC, created_at ASC
               LIMIT ?""",
            (recipient, limit),
        ).fetchall()
        return [_row_to_message(row) for row in rows]


def ack(config: MsgBusConfig, message_id: int) -> None:
    """Mark a message as processed."""
    with _connect(config) as conn:
        cur = conn.execute(
            "UPDATE messages SET status = 'processed' WHERE id = ?",
            (message_id,),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Message #{message_id} not found")


def get_message(config: MsgBusConfig, message_id: int) -> Optional[Message]:
    """Get a single message by ID."""
    with _connect(config) as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        return _row_to_message(row) if row else None


def link_channel(
    config: MsgBusConfig,
    message_id: int,
    channel: str,
    channel_msg_id: str,
) -> None:
    """Link a platform-specific message ID to a msgbus message."""
    with _connect(config) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO channel_refs
               (message_id, channel, channel_msg_id)
               VALUES (?, ?, ?)""",
            (message_id, channel, channel_msg_id),
        )


def find_by_channel_msg(
    config: MsgBusConfig,
    channel: str,
    channel_msg_id: str,
) -> Optional[Message]:
    """Find a msgbus message by its platform-specific message ID."""
    with _connect(config) as conn:
        ref_row = conn.execute(
            """SELECT message_id FROM channel_refs
               WHERE channel = ? AND channel_msg_id = ?""",
            (channel, channel_msg_id),
        ).fetchone()

        if not ref_row:
            return None

        msg_row = conn.execute(
            "SELECT * FROM messages WHERE id = ?",
            (ref_row["message_id"],),
        ).fetchone()
        return _row_to_message(msg_row) if msg_row else None


def cleanup_expired(config: MsgBusConfig) -> int:
    """Expire messages past their expires_at timestamp. Returns count."""
    with _connect(config) as conn:
        cur = conn.execute(
            """UPDATE messages SET status = 'expired'
               WHERE expires_at IS NOT NULL
               AND expires_at < datetime('now')
               AND status = 'pending'"""
        )
        return cur.rowcount


def cleanup_old(config: MsgBusConfig, days: int = 7) -> int:
    """Delete old processed/expired messages. Returns count deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _connect(config) as conn:
        # Nullify reply_to references to avoid FK violations
        conn.execute(
            """UPDATE messages SET reply_to = NULL
               WHERE reply_to IN (
                   SELECT id FROM messages
                   WHERE status IN ('processed', 'expired') AND created_at < ?
               )""",
            (cutoff,),
        )
        cur = conn.execute(
            "DELETE FROM messages WHERE status IN ('processed', 'expired') AND created_at < ?",
            (cutoff,),
        )
        return cur.rowcount


def count_pending(config: MsgBusConfig, recipient: str) -> int:
    """Count pending messages for a recipient."""
    with _connect(config) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE recipient = ? AND status = 'pending'",
            (recipient,),
        ).fetchone()
        return row["cnt"]


def status(config: MsgBusConfig) -> dict:
    """Return aggregate stats."""
    with _connect(config) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM messages GROUP BY status"
        ).fetchall()
        stats = {row["status"]: row["cnt"] for row in rows}

        total = conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()["cnt"]
        stats["total"] = total

        pending_rows = conn.execute(
            """SELECT recipient, COUNT(*) as cnt FROM messages
               WHERE status = 'pending' GROUP BY recipient"""
        ).fetchall()
        stats["pending_by_recipient"] = {r["recipient"]: r["cnt"] for r in pending_rows}

        return stats


# ── CLI ──────────────────────────────────────────────────────────────────────

def _format_message(msg: Message) -> str:
    priority_icon = "!" * max(1, 6 - msg.priority)
    status_icons = {"pending": "[P]", "read": "[R]", "processed": "[OK]", "expired": "[EX]"}
    status_icon = status_icons.get(msg.status, "[?]")
    reply_info = f" (reply to #{msg.reply_to})" if msg.reply_to else ""
    payload_preview = msg.payload[:100]
    return (
        f"  {status_icon} #{msg.id} [{msg.msg_type}] "
        f"{msg.sender} -> {msg.recipient} "
        f"P{msg.priority}{priority_icon}{reply_info}\n"
        f"     {msg.created_at} | {payload_preview}"
    )


def main():
    parser = argparse.ArgumentParser(description="SQLite Message Bus")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize message bus database")

    p_send = sub.add_parser("send", help="Send a message")
    p_send.add_argument("--from", dest="sender", required=True)
    p_send.add_argument("--to", dest="recipient", required=True)
    p_send.add_argument("--type", dest="msg_type", default="notify", choices=VALID_MSG_TYPES)
    p_send.add_argument("--priority", type=int, default=5)
    p_send.add_argument("--payload", required=True)
    p_send.add_argument("--reply-to", type=int, default=None)
    p_send.add_argument("--expires-at", default=None)

    p_recv = sub.add_parser("receive", help="Receive pending messages")
    p_recv.add_argument("recipient")
    p_recv.add_argument("--limit", type=int, default=10)
    p_recv.add_argument("--json", dest="as_json", action="store_true")

    p_ack = sub.add_parser("ack", help="Acknowledge a message")
    p_ack.add_argument("msg_id", type=int)

    p_link = sub.add_parser("link", help="Link channel message ID")
    p_link.add_argument("msg_id", type=int)
    p_link.add_argument("channel")
    p_link.add_argument("channel_msg_id")

    p_find = sub.add_parser("find-by-channel", help="Find message by channel ref")
    p_find.add_argument("channel")
    p_find.add_argument("channel_msg_id")

    p_clean = sub.add_parser("cleanup", help="Clean old messages")
    p_clean.add_argument("--days", type=int, default=7)

    p_count = sub.add_parser("count-pending", help="Count pending messages for recipient")
    p_count.add_argument("recipient")

    sub.add_parser("status", help="Show message bus status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = MsgBusConfig.default()

    if args.command == "init":
        init_db(config)
        print(f"MsgBus initialized at {config.db_path}")

    elif args.command == "send":
        init_db(config)
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            payload = args.payload

        msg_id = send(
            config,
            sender=args.sender,
            recipient=args.recipient,
            msg_type=args.msg_type,
            payload=payload,
            priority=args.priority,
            reply_to=args.reply_to,
            expires_at=args.expires_at,
        )
        print(msg_id)

    elif args.command == "receive":
        init_db(config)
        messages = receive(config, args.recipient, limit=args.limit)
        if args.as_json:
            data = [
                {
                    "id": m.id, "sender": m.sender, "msg_type": m.msg_type,
                    "priority": m.priority, "payload": m.payload_dict,
                    "created_at": m.created_at, "reply_to": m.reply_to,
                }
                for m in messages
            ]
            print(json.dumps(data, ensure_ascii=False))
        elif not messages:
            print("No pending messages.")
        else:
            print(f"{len(messages)} message(s):\n")
            for msg in messages:
                print(_format_message(msg))
                print()

    elif args.command == "ack":
        init_db(config)
        ack(config, args.msg_id)
        print(f"Message #{args.msg_id} marked as processed")

    elif args.command == "link":
        init_db(config)
        link_channel(config, args.msg_id, args.channel, args.channel_msg_id)
        print(f"Linked msg #{args.msg_id} -> {args.channel}:{args.channel_msg_id}")

    elif args.command == "find-by-channel":
        init_db(config)
        msg = find_by_channel_msg(config, args.channel, args.channel_msg_id)
        if msg:
            print(_format_message(msg))
        else:
            print("Not found")

    elif args.command == "cleanup":
        init_db(config)
        expired = cleanup_expired(config)
        deleted = cleanup_old(config, days=args.days)
        print(f"Expired: {expired}, Deleted: {deleted}")

    elif args.command == "count-pending":
        init_db(config)
        count = count_pending(config, args.recipient)
        print(count)

    elif args.command == "status":
        init_db(config)
        stats = status(config)
        print("=== MsgBus Status ===")
        print(f"  Total:     {stats.get('total', 0)}")
        print(f"  Pending:   {stats.get('pending', 0)}")
        print(f"  Read:      {stats.get('read', 0)}")
        print(f"  Processed: {stats.get('processed', 0)}")
        print(f"  Expired:   {stats.get('expired', 0)}")
        pending = stats.get("pending_by_recipient", {})
        if pending:
            print("\n  Pending by recipient:")
            for recipient, cnt in sorted(pending.items()):
                print(f"    {recipient}: {cnt}")


if __name__ == "__main__":
    main()
