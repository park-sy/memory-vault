#!/usr/bin/env python3
"""telegram_api.py — Telegram Bot API wrapper using stdlib only.

No SDK dependencies. Uses urllib + json for all HTTP communication.

Usage (Library):
    from telegram_api import load_config, send_text, send_with_actions, get_updates

    config = load_config()
    send_text(config, "Hello from Claude!")
    send_with_actions(config, "Approve?", ["approve", "reject"], "plan_42")
    updates = get_updates(config, offset=0)
"""

import json
import os
import types
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Union


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TopicConfig:
    ops: Optional[int] = None
    approval: Optional[int] = None
    report: Optional[int] = None
    clone: Optional[int] = None

    def get(self, name: str) -> Optional[int]:
        return getattr(self, name, None)


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str
    topics: TopicConfig = TopicConfig()
    api_base: str = "https://api.telegram.org"
    timeout: int = 10

    def __repr__(self) -> str:
        masked = self.bot_token[:6] + "..." if len(self.bot_token) > 6 else "***"
        return f"TelegramConfig(bot_token={masked!r}, chat_id={self.chat_id!r})"

    @property
    def base_url(self) -> str:
        return f"{self.api_base}/bot{self.bot_token}"


@dataclass(frozen=True)
class TelegramMessage:
    text: str
    parse_mode: str = "Markdown"
    reply_to_message_id: Optional[int] = None
    reply_markup: Optional[Union[dict, types.MappingProxyType]] = None
    message_thread_id: Optional[int] = None

    def __post_init__(self) -> None:
        if isinstance(self.reply_markup, dict):
            object.__setattr__(self, "reply_markup", types.MappingProxyType(self.reply_markup))


# ── Config Loading ───────────────────────────────────────────────────────────

def load_config() -> TelegramConfig:
    """Load Telegram config from environment variables.

    Tries .env file first (dotenv-like), then falls back to env vars.
    """
    _load_dotenv()

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID not set")

    def _int_or_none(key: str) -> Optional[int]:
        val = os.environ.get(key, "")
        return int(val) if val else None

    topics = TopicConfig(
        ops=_int_or_none("TELEGRAM_TOPIC_OPS"),
        approval=_int_or_none("TELEGRAM_TOPIC_APPROVAL"),
        report=_int_or_none("TELEGRAM_TOPIC_REPORT"),
        clone=_int_or_none("TELEGRAM_TOPIC_CLONE"),
    )

    return TelegramConfig(bot_token=bot_token, chat_id=chat_id, topics=topics)


def _load_dotenv() -> None:
    """Minimal .env file loader. No external dependencies."""
    from pathlib import Path
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip inline comments (only for unquoted values)
            if not (value.startswith("'") or value.startswith('"')):
                value = value.split("#", 1)[0].strip()
            value = value.strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


# ── API Calls ────────────────────────────────────────────────────────────────

def _json_default(obj):
    """JSON serializer for types not supported by default (e.g., MappingProxyType)."""
    if isinstance(obj, types.MappingProxyType):
        return dict(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _api_call(config: TelegramConfig, method: str, payload: dict) -> dict:
    """Make a Telegram Bot API call. Returns parsed JSON response."""
    url = f"{config.base_url}/{method}"
    data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("ok"):
                raise RuntimeError(f"Telegram API error: {result.get('description', 'unknown')}")
            return result.get("result", {})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Telegram connection error: {e.reason}") from e


def send_message(config: TelegramConfig, message: TelegramMessage) -> dict:
    """Send a TelegramMessage object."""
    payload = {
        "chat_id": config.chat_id,
        "text": message.text,
        "parse_mode": message.parse_mode,
    }
    if message.reply_to_message_id:
        payload["reply_to_message_id"] = message.reply_to_message_id
    if message.reply_markup:
        payload["reply_markup"] = message.reply_markup
    if message.message_thread_id:
        payload["message_thread_id"] = message.message_thread_id
    return _api_call(config, "sendMessage", payload)


def send_text(config: TelegramConfig, text: str, topic: Optional[str] = None) -> dict:
    """Send a simple text message. topic: 'ops', 'approval', 'report', 'clone'."""
    thread_id = config.topics.get(topic) if topic else None
    return send_message(config, TelegramMessage(text=text, message_thread_id=thread_id))


def send_with_actions(
    config: TelegramConfig,
    text: str,
    actions: List[str],
    callback_prefix: str,
    topic: Optional[str] = None,
) -> dict:
    """Send a message with inline keyboard buttons.

    Each action becomes a button. callback_data format: {callback_prefix}:{action}
    topic: 'ops', 'approval', 'report', 'clone'.
    """
    buttons = []
    for action in actions:
        callback_data = f"{callback_prefix}:{action}"
        if len(callback_data.encode("utf-8")) > 64:
            raise ValueError(f"callback_data exceeds 64 bytes: '{callback_data}'")
        buttons.append({"text": action, "callback_data": callback_data})
    reply_markup = {"inline_keyboard": [buttons]}
    thread_id = config.topics.get(topic) if topic else None
    message = TelegramMessage(text=text, reply_markup=reply_markup, message_thread_id=thread_id)
    return send_message(config, message)


def answer_callback_query(
    config: TelegramConfig,
    callback_query_id: str,
    text: Optional[str] = None,
) -> dict:
    """Answer a callback query (acknowledge button press)."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return _api_call(config, "answerCallbackQuery", payload)


def edit_message_text(
    config: TelegramConfig,
    message_id: int,
    text: str,
    parse_mode: str = "Markdown",
) -> dict:
    """Edit an existing message's text (removes inline keyboard)."""
    payload = {
        "chat_id": config.chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    return _api_call(config, "editMessageText", payload)


def get_updates(
    config: TelegramConfig,
    offset: int = 0,
    timeout: int = 5,
    allowed_updates: Optional[List[str]] = None,
) -> List[dict]:
    """Long-poll for updates from Telegram."""
    url = f"{config.base_url}/getUpdates"
    params = {"offset": offset, "timeout": timeout}
    if allowed_updates:
        params["allowed_updates"] = json.dumps(allowed_updates)

    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"

    try:
        with urllib.request.urlopen(full_url, timeout=timeout + 5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("result", []) if result.get("ok") else []
    except urllib.error.URLError as e:
        raise RuntimeError(f"Telegram poll failed: {e.reason}") from e
    except TimeoutError:
        # Timeout is expected for long-polling when no updates arrive
        return []


# ── Helpers ──────────────────────────────────────────────────────────────────

def is_authorized(update: dict, config: TelegramConfig) -> bool:
    """Check if the update comes from the authorized chat."""
    chat_id = None

    if "message" in update:
        chat_id = str(update["message"].get("chat", {}).get("id", ""))
    elif "callback_query" in update:
        chat_id = str(update["callback_query"].get("message", {}).get("chat", {}).get("id", ""))

    return chat_id == str(config.chat_id)


def parse_command(text: str) -> tuple:
    """Parse Telegram command text.

    Returns (command, argument_text) or (None, text) if not a command.
    Example: "/pool1 review this" -> ("pool1", "review this")
    """
    if not text or not text.startswith("/"):
        return (None, text or "")

    parts = text.split(None, 1)
    command = parts[0][1:]  # strip leading /
    # Remove @botname suffix if present
    command = command.split("@")[0]
    arg_text = parts[1] if len(parts) > 1 else ""
    return (command, arg_text)
