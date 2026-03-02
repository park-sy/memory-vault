"""Intent Parser — parse /feature commands from MsgBus messages.

Two-level parsing:
  Level 0 — rule-based regex matching (zero tokens, handles clear commands)
  Level 1 — LLM-based natural language parsing (fallback for ambiguous input)
"""

import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("factory.intent")


@dataclass(frozen=True)
class Intent:
    action: str          # "create", "status", "list", "approve", "detail", "config", "help"
    title: Optional[str] = None
    task_id: Optional[int] = None
    config_key: Optional[str] = None
    config_value: Optional[str] = None
    raw_text: str = ""
    confidence: float = 1.0   # 0.0-1.0; Level 0 always 1.0
    parse_level: int = 0      # 0 = rule-based, 1 = LLM


# ── Level 0: Rule-based Patterns ─────────────────────────────────────────────

_APPROVE_PATTERN = re.compile(
    r"^(?:approve|승인)\s+(?:#?(\d+)|(\w+))$", re.IGNORECASE,
)
_DETAIL_PATTERN = re.compile(
    r"^(?:detail|상세)\s+#?(\d+)$", re.IGNORECASE,
)
_CONFIG_PATTERN = re.compile(
    r"^config\s+(\w+)\s+(\w+)$", re.IGNORECASE,
)

# Natural language hints that map to actions (Level 0 keyword detection)
_NL_STATUS_HINTS = {"지금 어때", "현황", "진행", "파이프라인", "뭐 하고 있어", "어디까지"}
_NL_LIST_HINTS = {"뭐 있어", "태스크", "작업 목록"}
_NL_APPROVE_HINTS = {"승인해", "허락", "진행해", "고고", "ㄱㄱ"}


def parse(text: str) -> Intent:
    """Parse a /feature command text into an Intent (Level 0 + Level 1 fallback)."""
    l0 = _parse_level0(text)
    if l0 is not None:
        return l0

    # Level 0 produced "create" — check if it's actually ambiguous
    cleaned = text.strip()
    if _is_ambiguous(cleaned):
        l1 = _parse_level1(cleaned)
        if l1 is not None:
            return l1

    # Default: create
    return Intent(action="create", title=cleaned, raw_text=text, confidence=0.7, parse_level=0)


def _parse_level0(text: str) -> Optional[Intent]:
    """Level 0: deterministic rule-based parsing. Returns None if no clear match."""
    cleaned = text.strip()
    if not cleaned:
        return Intent(action="help", raw_text=text)

    lower = cleaned.lower()

    # Exact matches
    if lower in ("status", "상태"):
        return Intent(action="status", raw_text=text)

    if lower in ("list", "목록"):
        return Intent(action="list", raw_text=text)

    if lower in ("help", "도움", "?"):
        return Intent(action="help", raw_text=text)

    # Config command
    config_match = _CONFIG_PATTERN.match(cleaned)
    if config_match:
        return Intent(
            action="config",
            config_key=config_match.group(1),
            config_value=config_match.group(2),
            raw_text=text,
        )

    # Approve command
    approve_match = _APPROVE_PATTERN.match(cleaned)
    if approve_match:
        task_id_str = approve_match.group(1)
        name = approve_match.group(2)
        if task_id_str:
            return Intent(action="approve", task_id=int(task_id_str), raw_text=text)
        return Intent(action="approve", title=name, raw_text=text)

    # Detail command
    detail_match = _DETAIL_PATTERN.match(cleaned)
    if detail_match:
        return Intent(action="detail", task_id=int(detail_match.group(1)), raw_text=text)

    # Natural language keyword detection (still Level 0)
    for hint in _NL_STATUS_HINTS:
        if hint in lower:
            return Intent(action="status", raw_text=text, confidence=0.9)

    for hint in _NL_LIST_HINTS:
        if hint in lower:
            return Intent(action="list", raw_text=text, confidence=0.9)

    for hint in _NL_APPROVE_HINTS:
        if hint in lower:
            # Try to extract task_id from text
            numbers = re.findall(r"#?(\d+)", cleaned)
            if numbers:
                return Intent(action="approve", task_id=int(numbers[0]), raw_text=text, confidence=0.9)
            return Intent(action="approve", raw_text=text, confidence=0.8)

    # No clear match — return None to signal Level 1 should try
    return None


def _is_ambiguous(text: str) -> bool:
    """Heuristic: is this text ambiguous enough to warrant LLM parsing?"""
    lower = text.lower()
    # Short text with question marks or Korean particles suggesting a question
    if "?" in text or "까" in lower:
        return True
    # Text mentioning existing features (could be status/detail, not create)
    if any(w in lower for w in ("어떻게", "보여줘", "알려줘", "확인")):
        return True
    # Contains a task ID reference mixed with other text
    if re.search(r"#\d+", text) and len(text.split()) > 2:
        return True
    return False


# ── Level 1: LLM-based Parsing ──────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """\
You are a command parser for Feature Factory. Parse the user's natural language into a JSON intent.

Available actions:
- create: User wants to create a new feature. Extract the feature title.
- status: User wants to see pipeline status.
- list: User wants to see active tasks.
- approve: User wants to approve a task. Extract task_id if mentioned.
- detail: User wants details on a specific task. Extract task_id.
- config: User wants to change settings. Extract key and value.
- help: User needs help.

Respond with ONLY a JSON object:
{"action": "...", "title": "...", "task_id": null, "config_key": null, "config_value": null, "confidence": 0.9}

Rules:
- confidence: 0.0-1.0 how confident you are
- task_id: integer or null
- title: string or null (only for create action)
- If the user asks about a specific task, use "detail" not "status"
- If user says something like "7번 어떻게 되고 있어?", that's detail with task_id=7
"""


def _parse_level1(text: str) -> Optional[Intent]:
    """Level 1: LLM-based intent parsing for ambiguous inputs."""
    try:
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import subprocess, sys, json; "
                "r = subprocess.run("
                "['claude', '-p', sys.argv[1], '--system', sys.argv[2], "
                "'--output-format', 'json', '--no-session-persistence', "
                "'--model', 'haiku'], "
                "capture_output=True, text=True, timeout=30); "
                "d = json.loads(r.stdout) if r.returncode == 0 else {}; "
                "print(d.get('result', ''))",
                text, _LLM_SYSTEM_PROMPT,
            ],
            capture_output=True, text=True, timeout=45,
        )

        if result.returncode != 0:
            log.warning("Level 1 LLM call failed: %s", result.stderr[:200])
            return None

        raw = result.stdout.strip()
        # Extract JSON from response (LLM may wrap in markdown)
        json_str = _extract_json(raw)
        if not json_str:
            log.warning("Level 1: no JSON in response: %s", raw[:200])
            return None

        data = json.loads(json_str)
        action = data.get("action", "help")
        confidence = float(data.get("confidence", 0.5))

        # Only trust LLM if confidence is reasonable
        if confidence < 0.4:
            log.info("Level 1 low confidence (%.2f), falling back to create", confidence)
            return None

        return Intent(
            action=action,
            title=data.get("title"),
            task_id=data.get("task_id"),
            config_key=data.get("config_key"),
            config_value=data.get("config_value"),
            raw_text=text,
            confidence=confidence,
            parse_level=1,
        )

    except (subprocess.SubprocessError, json.JSONDecodeError, ValueError) as e:
        log.warning("Level 1 parsing failed: %s", e)
        return None


def _extract_json(text: str) -> Optional[str]:
    """Extract a JSON object from text that may contain markdown fences."""
    # Try direct parse
    text = text.strip()
    if text.startswith("{"):
        return text

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1)

    # Try finding any JSON object
    match = re.search(r"\{[^{}]*\}", text)
    if match:
        return match.group(0)

    return None
