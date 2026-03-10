#!/usr/bin/env python3
"""telegram_bridge.py — Bidirectional Telegram <-> MsgBus bridge daemon.

Runs as a long-lived process (typically in a tmux session).
Dual polling loop:
  1. Telegram long-poll (5s) -> inbound messages/callbacks -> MsgBus
  2. MsgBus poll (1s) -> outbound messages (recipient="telegram") -> Telegram API

Inbound routing:
  /pool1 <text>  -> recipient="cc-pool-1"
  /pool2 <text>  -> recipient="cc-pool-2"
  /orch <text>   -> recipient="cc-orchestration"
  /status        -> recipient="cc-orchestration", type="query"
  plain text     -> recipient="cc-orchestration" (default)

Start:
    python3 scripts/telegram_bridge.py

    # Or in a tmux session:
    tmux new-session -d -s cc-telegram-bridge \
      -c ~/dev/memory-vault \
      "python3 scripts/telegram_bridge.py"
"""

import json
import logging
import logging.handlers
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from msgbus import (
    MsgBusConfig, init_db, send, receive, ack,
    link_channel, find_by_channel_msg, get_message, cleanup_expired,
)
from telegram_api import (
    load_config, send_text, send_with_actions,
    answer_callback_query, edit_message_text,
    get_updates, is_authorized, parse_command,
    TelegramConfig,
)

# ── Config ───────────────────────────────────────────────────────────────────

MSGBUS_POLL_INTERVAL = 1.0      # seconds between MsgBus checks
TELEGRAM_POLL_TIMEOUT = 5       # Telegram long-poll timeout
MAX_BACKOFF = 60                # max exponential backoff seconds
CLEANUP_INTERVAL = 300          # cleanup expired messages every 5 min

# Command -> recipient routing table
VAULT_DIR = Path(__file__).parent.parent
LOG_DIR = VAULT_DIR / "storage" / "logs"

COMMAND_ROUTES = {
    "pool1": "cc-pool-1",
    "pool2": "cc-pool-2",
    "pool3": "cc-pool-3",
    "orch":  "cc-orchestration",
    "status": "cc-orchestration",
    "feature": "cc-factory",
}

DEFAULT_RECIPIENT = "cc-orchestration"


def _thread_id_to_topic(tg_config: TelegramConfig, thread_id: Optional[int]) -> Optional[str]:
    """Reverse-map a Telegram thread_id to a topic name."""
    if not thread_id:
        return None
    topics = tg_config.topics
    # 고정 + 동적 토픽 모두 검색
    for name, topic_id in topics.all_topics().items():
        if topic_id == thread_id:
            return name
    return None

def _setup_logging() -> logging.Logger:
    """Console + rotating file logging for the bridge."""
    logger = logging.getLogger("bridge")
    logger.setLevel(logging.INFO)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(console)

    # File handler (rotating, 5MB x 3)
    log_dir = Path(__file__).parent.parent / "storage" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        str(log_dir / "bridge.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    return logger


log = _setup_logging()


# ── Inbound: Telegram -> MsgBus ─────────────────────────────────────────────

def _is_boss_group(update: dict, tg_config: TelegramConfig) -> bool:
    """Check if the message is from the boss chat group."""
    if not tg_config.boss_chat_id:
        return False
    chat_id = str(update.get("message", {}).get("chat", {}).get("id", ""))
    return chat_id == str(tg_config.boss_chat_id)


def _is_lifelog_group(update: dict, tg_config: TelegramConfig) -> bool:
    """Check if the message is from the lifelog chat group."""
    if not tg_config.lifelog_chat_id:
        return False
    chat_id = str(update.get("message", {}).get("chat", {}).get("id", ""))
    return chat_id == str(tg_config.lifelog_chat_id)


def handle_text_message(
    tg_config: TelegramConfig,
    bus_config: MsgBusConfig,
    update: dict,
) -> None:
    """Process an incoming text message from Telegram."""
    message = update.get("message", {})
    text = message.get("text", "").strip()
    if not text:
        return

    # Lifelog 그룹 메시지 → ingest.py fire-and-forget
    if _is_lifelog_group(update, tg_config):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ingest_script = str(VAULT_DIR / "scripts" / "lifelog" / "ingest.py")
        with open(str(LOG_DIR / "lifelog-ingest.log"), "a") as err_log:
            subprocess.Popen(
                ["python3", ingest_script, text],
                cwd=str(VAULT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=err_log,
            )
        log.info("Inbound (lifelog): '%s' -> ingest.py", text[:50])
        return

    # Boss 그룹 메시지 → cc-boss로 라우팅
    if _is_boss_group(update, tg_config):
        payload_data = {
            "text": text,
            "telegram_from": message.get("from", {}).get("first_name", "unknown"),
            "group": "boss",
        }
        msg_id = send(
            bus_config,
            sender="telegram",
            recipient="cc-boss",
            msg_type="command",
            payload=payload_data,
        )
        log.info("Inbound (boss): '%s' -> cc-boss (msg #%d)", text[:50], msg_id)
        return

    command, arg_text = parse_command(text)

    if command and command in COMMAND_ROUTES:
        recipient = COMMAND_ROUTES[command]
        msg_type = "query" if command == "status" else "command"
        payload_text = arg_text if arg_text else command
    else:
        recipient = DEFAULT_RECIPIENT
        msg_type = "command"
        payload_text = text

    # Identify source topic
    thread_id = message.get("message_thread_id")
    source_topic = _thread_id_to_topic(tg_config, thread_id)

    payload_data = {
        "text": payload_text,
        "telegram_from": message.get("from", {}).get("first_name", "unknown"),
    }
    if source_topic:
        payload_data["source_topic"] = source_topic

    msg_id = send(
        bus_config,
        sender="telegram",
        recipient=recipient,
        msg_type=msg_type,
        payload=payload_data,
    )

    log.info("Inbound: '%s' -> %s [%s] (msg #%d)", text[:50], recipient, source_topic or "general", msg_id)


def handle_callback_query(
    tg_config: TelegramConfig,
    bus_config: MsgBusConfig,
    update: dict,
) -> None:
    """Process an inline keyboard button press."""
    callback = update.get("callback_query", {})
    callback_id = callback.get("id", "")
    callback_data = callback.get("data", "")
    tg_message = callback.get("message", {})
    tg_message_id = tg_message.get("message_id")

    # Parse callback_data: "{msg_id}:{action}"
    if ":" not in callback_data:
        answer_callback_query(tg_config, callback_id, text="Invalid callback")
        return

    prefix, action = callback_data.split(":", 1)

    # Find original message via channel_refs
    original = find_by_channel_msg(bus_config, "telegram", str(tg_message_id))

    # Determine reply recipient (the original sender)
    reply_recipient = original.sender if original else DEFAULT_RECIPIENT
    reply_to_id = original.id if original else None

    # Write callback response to msgbus
    msg_id = send(
        bus_config,
        sender="telegram",
        recipient=reply_recipient,
        msg_type="callback",
        payload={"action": action, "callback_prefix": prefix},
        reply_to=reply_to_id,
    )

    # Answer the callback query (removes loading spinner)
    answer_callback_query(tg_config, callback_id, text=action)

    # Edit the original message to show selected action
    if tg_message_id:
        original_text = tg_message.get("text", "")
        try:
            edit_message_text(
                tg_config,
                tg_message_id,
                f"{original_text}\n\n[{action.upper()} ✓]",
            )
        except RuntimeError as e:
            log.warning("Failed to edit message: %s", e)

    log.info("Callback: action=%s -> %s (msg #%d)", action, reply_recipient, msg_id)


def process_inbound(
    tg_config: TelegramConfig,
    bus_config: MsgBusConfig,
    offset: int,
) -> int:
    """Poll Telegram for updates and route to MsgBus. Returns new offset."""
    updates = get_updates(tg_config, offset=offset, timeout=TELEGRAM_POLL_TIMEOUT)

    for update in updates:
        offset = max(offset, update.get("update_id", 0) + 1)

        if not is_authorized(update, tg_config):
            log.warning("Unauthorized update from chat, skipping")
            continue

        if "message" in update and "text" in update.get("message", {}):
            handle_text_message(tg_config, bus_config, update)
        elif "callback_query" in update:
            handle_callback_query(tg_config, bus_config, update)

    return offset


# ── Outbound: MsgBus -> Telegram ─────────────────────────────────────────────

def process_outbound(
    tg_config: TelegramConfig,
    bus_config: MsgBusConfig,
) -> int:
    """Check MsgBus for outbound messages and send to Telegram. Returns count sent."""
    messages = receive(bus_config, "telegram", limit=5)
    sent_count = 0

    for msg in messages:
        try:
            payload = msg.payload_dict
            text = payload.get("text", msg.payload[:500])

            # ai-boss sender는 이미 [진수] 등 prefix 포함 → sender prefix 생략
            if msg.sender == "ai-boss":
                display_text = text
            else:
                display_text = f"[{msg.sender}] {text}"

            # Determine target topic and chat_id from payload
            topic = payload.get("channel")

            # group 필드도 channel로 처리 (하위 호환)
            if not topic and payload.get("group"):
                topic = payload["group"]

            # boss 채널 → 전용 그룹으로 직접 전송 (토픽 없음)
            target_chat_id = None
            if topic == "boss" and tg_config.boss_chat_id:
                target_chat_id = tg_config.boss_chat_id
                topic = None  # 전용 그룹은 토픽 불필요

            actions = payload.get("actions")
            if actions:
                # Send with inline keyboard
                callback_prefix = str(msg.id)
                result = send_with_actions(
                    tg_config, display_text, actions, callback_prefix,
                    topic=topic, chat_id=target_chat_id,
                )
            else:
                result = send_text(
                    tg_config, display_text, topic=topic,
                    chat_id=target_chat_id,
                )

            # Link the Telegram message ID to the MsgBus message
            tg_msg_id = result.get("message_id")
            if tg_msg_id:
                link_channel(bus_config, msg.id, "telegram", str(tg_msg_id))

            ack(bus_config, msg.id)
            sent_count += 1

            log.info("Outbound: msg #%d -> Telegram (tg_msg=%s)", msg.id, tg_msg_id)

        except RuntimeError as e:
            log.error("Failed to send msg #%d: %s", msg.id, e)
        except Exception as e:
            log.error("Unexpected error sending msg #%d: %s", msg.id, e)

    return sent_count


# ── Main Loop ────────────────────────────────────────────────────────────────

class Bridge:
    """Dual polling loop bridge between Telegram and MsgBus."""

    def __init__(self, tg_config: TelegramConfig, bus_config: MsgBusConfig):
        self.tg_config = tg_config
        self.bus_config = bus_config
        self.running = False
        self.offset = 0
        self.backoff = 0
        self.last_cleanup = time.time()

    def start(self) -> None:
        self.running = True
        init_db(self.bus_config)

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        log.info("Bridge started. Telegram <-> MsgBus")
        log.info("DB: %s", self.bus_config.db_path)

        while self.running:
            try:
                # 1. Telegram long-poll (blocking for up to TELEGRAM_POLL_TIMEOUT seconds)
                self.offset = process_inbound(self.tg_config, self.bus_config, self.offset)

                # 2. MsgBus outbound check
                process_outbound(self.tg_config, self.bus_config)

                # 3. Periodic cleanup
                now = time.time()
                if now - self.last_cleanup > CLEANUP_INTERVAL:
                    expired = cleanup_expired(self.bus_config)
                    if expired:
                        log.info("Cleaned %d expired messages", expired)
                    self.last_cleanup = now

                # Reset backoff on success
                self.backoff = 0

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.backoff = min(self.backoff * 2 if self.backoff > 0 else 1, MAX_BACKOFF)
                log.error("Loop error (backoff %ds): %s", self.backoff, e)
                time.sleep(self.backoff)

        log.info("Bridge stopped.")

    def _handle_signal(self, signum, frame) -> None:
        log.info("Signal %d received, shutting down...", signum)
        self.running = False


def main():
    try:
        tg_config = load_config()
    except ValueError as e:
        log.error("Config error: %s", e)
        log.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env or environment")
        sys.exit(1)

    bus_config = MsgBusConfig.default()
    bridge = Bridge(tg_config, bus_config)
    bridge.start()


if __name__ == "__main__":
    main()
