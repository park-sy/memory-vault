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
    extras: tuple = ()  # ((name, topic_id), ...) — frozen이므로 tuple of tuples

    def get(self, name: str) -> Optional[int]:
        # 고정 필드 먼저 확인
        fixed = getattr(self, name, None)
        if fixed is not None and name in ("ops", "approval", "report", "clone"):
            return fixed
        # extras에서 검색
        for extra_name, topic_id in self.extras:
            if extra_name == name:
                return topic_id
        return None

    def all_topics(self) -> dict:
        """모든 토픽 (고정 + 동적) 반환."""
        result = {}
        for name in ("ops", "approval", "report", "clone"):
            val = getattr(self, name, None)
            if val is not None:
                result[name] = val
        for extra_name, topic_id in self.extras:
            result[extra_name] = topic_id
        return result


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str
    boss_chat_id: str = ""
    lifelog_chat_id: str = ""
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

    # 고정 토픽
    fixed_keys = {"OPS", "APPROVAL", "REPORT", "CLONE"}
    # 동적 토픽: TELEGRAM_TOPIC_* 중 고정 4개 외 나머지
    extras = []
    prefix = "TELEGRAM_TOPIC_"
    for key, val in os.environ.items():
        if key.startswith(prefix) and val:
            suffix = key[len(prefix):]
            if suffix not in fixed_keys:
                try:
                    extras.append((suffix.lower(), int(val)))
                except ValueError:
                    pass

    topics = TopicConfig(
        ops=_int_or_none("TELEGRAM_TOPIC_OPS"),
        approval=_int_or_none("TELEGRAM_TOPIC_APPROVAL"),
        report=_int_or_none("TELEGRAM_TOPIC_REPORT"),
        clone=_int_or_none("TELEGRAM_TOPIC_CLONE"),
        extras=tuple(extras),
    )

    boss_chat_id = os.environ.get("TELEGRAM_BOSS_CHAT_ID", "")
    lifelog_chat_id = os.environ.get("TELEGRAM_LIFELOG_CHAT_ID", "")

    return TelegramConfig(
        bot_token=bot_token, chat_id=chat_id,
        boss_chat_id=boss_chat_id, lifelog_chat_id=lifelog_chat_id,
        topics=topics,
    )


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


def send_message(
    config: TelegramConfig,
    message: TelegramMessage,
    chat_id: Optional[str] = None,
) -> dict:
    """Send a TelegramMessage object.

    Args:
        chat_id: Override target chat. Defaults to config.chat_id.
    """
    payload = {
        "chat_id": chat_id or config.chat_id,
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


def send_text(
    config: TelegramConfig,
    text: str,
    topic: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> dict:
    """Send a simple text message.

    Args:
        topic: Topic channel name ('ops', 'approval', 'report', 'clone').
        chat_id: Override target chat. Defaults to config.chat_id.
    """
    thread_id = config.topics.get(topic) if topic else None
    return send_message(
        config,
        TelegramMessage(text=text, message_thread_id=thread_id),
        chat_id=chat_id,
    )


def send_with_actions(
    config: TelegramConfig,
    text: str,
    actions: List[str],
    callback_prefix: str,
    topic: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> dict:
    """Send a message with inline keyboard buttons.

    Each action becomes a button. callback_data format: {callback_prefix}:{action}
    topic: 'ops', 'approval', 'report', 'clone'.
    chat_id: Override target chat. Defaults to config.chat_id.
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
    return send_message(config, message, chat_id=chat_id)


def send_document(
    config: TelegramConfig,
    file_path: str,
    caption: Optional[str] = None,
    topic: Optional[str] = None,
    reply_markup: Optional[dict] = None,
) -> dict:
    """Send a file as a Telegram document (multipart/form-data).

    caption is limited to 1024 chars by Telegram API.
    """
    import mimetypes

    url = f"{config.base_url}/sendDocument"
    boundary = "----TelegramBotBoundary9876543210"

    text_parts: list = []

    text_parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
        f"{config.chat_id}\r\n"
    )

    thread_id = config.topics.get(topic) if topic else None
    if thread_id:
        text_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="message_thread_id"\r\n\r\n'
            f"{thread_id}\r\n"
        )

    if caption:
        text_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n\r\n'
            f"{caption[:1024]}\r\n"
        )

    if reply_markup:
        markup_json = json.dumps(reply_markup, ensure_ascii=False)
        text_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="reply_markup"\r\n\r\n'
            f"{markup_json}\r\n"
        )

    text_data = "".join(text_parts).encode("utf-8")

    filename = os.path.basename(file_path)
    mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        file_content = f.read()

    file_header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8")

    closing = f"\r\n--{boundary}--\r\n".encode("utf-8")

    body = text_data + file_header + file_content + closing

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("ok"):
                raise RuntimeError(f"Telegram API error: {result.get('description', 'unknown')}")
            return result.get("result", {})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Telegram connection error: {e.reason}") from e


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


def create_forum_topic(
    config: TelegramConfig,
    name: str,
    icon_color: Optional[int] = None,
) -> dict:
    """Create a new forum topic in the group chat.

    Returns API result with message_thread_id (= topic_id).
    """
    payload = {"chat_id": config.chat_id, "name": name}
    if icon_color is not None:
        payload["icon_color"] = icon_color
    return _api_call(config, "createForumTopic", payload)


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
    """Check if the update comes from an authorized chat (main or boss group)."""
    chat_id = None

    if "message" in update:
        chat_id = str(update["message"].get("chat", {}).get("id", ""))
    elif "callback_query" in update:
        chat_id = str(update["callback_query"].get("message", {}).get("chat", {}).get("id", ""))

    allowed = {str(config.chat_id)}
    if config.boss_chat_id:
        allowed.add(str(config.boss_chat_id))
    if config.lifelog_chat_id:
        allowed.add(str(config.lifelog_chat_id))

    return chat_id in allowed


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


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli_create_topic() -> None:
    """CLI: python3 scripts/telegram_api.py create-topic <name>"""
    import sys as _sys
    if len(_sys.argv) < 3:
        print("Usage: telegram_api.py create-topic <name>", file=_sys.stderr)
        _sys.exit(1)
    topic_name = _sys.argv[2]
    config = load_config()
    result = create_forum_topic(config, topic_name)
    topic_id = result.get("message_thread_id")
    print(json.dumps({"name": topic_name, "topic_id": topic_id}))
    print(f"\nAdd to .env:  TELEGRAM_TOPIC_{topic_name.upper()}={topic_id}", file=_sys.stderr)


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) >= 2 and _sys.argv[1] == "create-topic":
        _cli_create_topic()
    else:
        print("Usage: telegram_api.py create-topic <name>", file=_sys.stderr)
