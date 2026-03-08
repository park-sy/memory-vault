"""Session Scanner — JSONL 토큰 스캐너.

Claude JSONL 세션 파일에서 assistant 메시지의 usage 필드를 파싱하여
토큰 사용량을 합산한다.
"""

import json
import logging
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("factory.scanner")

# Claude projects directory
_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class TokenScanResult:
    """JSONL 세션 파일의 토큰 사용량 합산 결과."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    request_count: int
    session_id: str

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
        )


def scan_session_tokens(
    project_dir: str,
    after_time: float,
) -> Optional[TokenScanResult]:
    """assignment 이후 생성/수정된 JSONL 세션 파일에서 토큰 합산.

    Args:
        project_dir: 프로젝트 디렉토리 절대 경로 (e.g. "/Users/hiyeop/dev/whos-life")
        after_time: 이 unix timestamp 이후 수정된 파일만 스캔

    Returns:
        TokenScanResult or None (파일 없거나 토큰 0일 때)
    """
    encoded = _encode_project_path(project_dir)
    scan_dir = _CLAUDE_PROJECTS_DIR / encoded

    if not scan_dir.is_dir():
        log.debug("Scan dir not found: %s", scan_dir)
        return None

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_creation = 0
    request_count = 0
    model_counter: Counter = Counter()
    last_session_id = ""

    for jsonl_path in scan_dir.glob("*.jsonl"):
        try:
            mtime = jsonl_path.stat().st_mtime
        except OSError:
            continue

        if mtime <= after_time:
            continue

        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                usage = _parse_assistant_usage(line)
                if usage is None:
                    continue

                total_input += usage["input_tokens"]
                total_output += usage["output_tokens"]
                total_cache_read += usage["cache_read_tokens"]
                total_cache_creation += usage["cache_creation_tokens"]
                request_count += 1
                model_counter[usage["model"]] += 1

                if usage["session_id"]:
                    last_session_id = usage["session_id"]

    if request_count == 0:
        return None

    top_model = model_counter.most_common(1)[0][0] if model_counter else "unknown"

    return TokenScanResult(
        model=top_model,
        input_tokens=total_input,
        output_tokens=total_output,
        cache_read_tokens=total_cache_read,
        cache_creation_tokens=total_cache_creation,
        request_count=request_count,
        session_id=last_session_id,
    )


def _parse_assistant_usage(line: str) -> Optional[dict]:
    """JSONL 한 줄 파싱 → usage dict 또는 None.

    Returns:
        {"model", "input_tokens", "output_tokens",
         "cache_read_tokens", "cache_creation_tokens", "session_id"}
    """
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    if data.get("type") != "assistant":
        return None

    msg = data.get("message", {})
    usage = msg.get("usage")
    if not usage:
        return None

    return {
        "model": msg.get("model", "unknown"),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
        "session_id": data.get("sessionId", ""),
    }


def _encode_project_path(path: str) -> str:
    """프로젝트 절대 경로를 Claude 디렉토리명으로 인코딩.

    '/Users/hiyeop/dev/whos-life' → '-Users-hiyeop-dev-whos-life'
    """
    return path.replace("/", "-")
