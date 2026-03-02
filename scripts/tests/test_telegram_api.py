"""test_telegram_api.py — telegram_api.py tests (~12 assertions)."""

import os
import sys
import types
from pathlib import Path
from typing import List
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import Suite, run_suite, TestResult, EnvBackup
import telegram_api
from telegram_api import (
    TelegramConfig, TopicConfig, TelegramMessage,
    parse_command, is_authorized, load_config,
)


def _test_telegram_api(s: Suite) -> None:
    # ── parse_command tests ──

    # 1. basic command
    cmd, arg = parse_command("/pool1 review this code")
    s.check_eq("parse_command: basic cmd", cmd, "pool1")
    s.check_eq("parse_command: basic arg", arg, "review this code")

    # 2. command with @botname
    cmd2, arg2 = parse_command("/status@mybot")
    s.check_eq("parse_command: @botname stripped", cmd2, "status")

    # 3. no command (plain text)
    cmd3, arg3 = parse_command("just regular text")
    s.check_none("parse_command: no command = None", cmd3)
    s.check_eq("parse_command: text preserved", arg3, "just regular text")

    # 4. empty input
    cmd4, arg4 = parse_command("")
    s.check_none("parse_command: empty = None", cmd4)

    # 5. command only (no args)
    cmd5, arg5 = parse_command("/status")
    s.check_eq("parse_command: no args = empty", arg5, "")

    # ── is_authorized tests ──

    config = TelegramConfig(bot_token="fake:token", chat_id="12345")

    # 6. authorized message
    update_ok = {"message": {"chat": {"id": 12345}, "text": "hi"}}
    s.check("is_authorized: matching chat_id", is_authorized(update_ok, config))

    # 7. unauthorized message
    update_bad = {"message": {"chat": {"id": 99999}, "text": "hi"}}
    s.check("is_authorized: wrong chat_id = False", not is_authorized(update_bad, config))

    # 8. callback_query authorization
    update_cb = {
        "callback_query": {
            "message": {"chat": {"id": 12345}},
            "data": "plan_42:approve",
        },
    }
    s.check("is_authorized: callback_query", is_authorized(update_cb, config))

    # ── TelegramConfig / TopicConfig tests ──

    # 9. base_url construction
    cfg = TelegramConfig(bot_token="123:ABC", chat_id="456")
    s.check_eq("TelegramConfig: base_url", cfg.base_url, "https://api.telegram.org/bot123:ABC")

    # 10. TopicConfig.get
    topics = TopicConfig(ops=100, approval=200)
    s.check_eq("TopicConfig: get ops", topics.get("ops"), 100)
    s.check_none("TopicConfig: get nonexistent", topics.get("nonexistent"))

    # 11. TelegramMessage: reply_markup frozen
    msg = TelegramMessage(
        text="test",
        reply_markup={"inline_keyboard": [[{"text": "OK"}]]},
    )
    s.check_is_instance("TelegramMessage: reply_markup frozen", msg.reply_markup, types.MappingProxyType)

    # 12. load_config: missing token raises ValueError
    with EnvBackup(["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        # Patch _load_dotenv to prevent .env file from injecting values
        with patch.object(telegram_api, '_load_dotenv', lambda: None):
            s.check_raises("load_config: no token raises ValueError", ValueError,
                           lambda: load_config())


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("telegram-api", _test_telegram_api)
