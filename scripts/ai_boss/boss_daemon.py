#!/usr/bin/env python3
"""Boss Daemon — MsgBus polling으로 상엽 메시지를 자동 소비하는 데몬.

bridge가 boss 그룹 메시지를 cc-boss recipient로 라우팅하면,
이 데몬이 polling → responder 호출 → Telegram 응답 전송.

Usage:
    python3 scripts/ai_boss/boss_daemon.py
"""

import json
import logging
import signal
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from msgbus import MsgBusConfig, init_db as init_bus, receive, ack
from ai_boss.responder import respond_to_message

# ── Constants ─────────────────────────────────────────────────────────────

VAULT_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = VAULT_DIR / "storage" / "logs"
LOG_FILE = LOG_DIR / "boss-daemon.log"
RECIPIENT = "cc-boss"
POLL_INTERVAL = 3  # seconds


# ── Logging ───────────────────────────────────────────────────────────────

def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("boss-daemon")
    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=2 * 1024 * 1024,  # 2MB
        backupCount=3,
    )
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # stderr에도 출력 (tmux에서 확인 가능)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    return logger


# ── Main Loop ─────────────────────────────────────────────────────────────

def run_daemon() -> None:
    logger = _setup_logging()
    bus_config = MsgBusConfig.default()
    init_bus(bus_config)

    running = True

    def _shutdown(signum, _frame):
        nonlocal running
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down", sig_name)
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Boss daemon started (recipient=%s, poll=%ds)", RECIPIENT, POLL_INTERVAL)

    while running:
        try:
            messages = receive(bus_config, RECIPIENT, limit=1)

            for msg in messages:
                text = msg.payload_dict.get("text", "")
                if not text:
                    logger.warning("Empty payload from msg #%d, skipping", msg.id)
                    ack(bus_config, msg.id)
                    continue

                logger.info(
                    "Processing msg #%d from %s: %s",
                    msg.id, msg.sender, text[:80],
                )

                try:
                    result = respond_to_message(text)
                    logger.info(
                        "Response result: status=%s, tokens=%s",
                        result.get("status"),
                        result.get("tokens_used", "?"),
                    )
                except Exception:
                    logger.exception("Failed to respond to msg #%d", msg.id)

                ack(bus_config, msg.id)

        except Exception:
            logger.exception("Error in poll loop")

        time.sleep(POLL_INTERVAL)

    logger.info("Boss daemon stopped")


if __name__ == "__main__":
    run_daemon()
