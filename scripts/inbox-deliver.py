#!/usr/bin/env python3
"""inbox-deliver.py — Stop hook: pending msgbus 메시지를 워커 세션에 전달.

Claude Code 세션이 응답을 완료(Stop)할 때마다 실행.
CC_SESSION 환경변수로 자기 세션명을 식별하고,
msgbus.db에서 pending 메시지를 조회하여 tmux send-keys로 주입.

pool 워커가 아닌 세션(CC_SESSION 미설정)에서는 즉시 종료.

동작 흐름:
    1. CC_SESSION 확인 (없으면 exit)
    2. 중복 방지 lockfile 확인 (30초 이내 재실행 방지)
    3. msgbus.db에서 pending 메시지 조회
    4. 메시지를 포맷하여 tmux send-keys로 주입
    5. 전달된 메시지를 'read'로 마킹
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VAULT_DIR / "scripts"))

from msgbus import MsgBusConfig, init_db, receive, peek  # noqa: E402

SESSION = os.environ.get("CC_SESSION", "")
LOCK_DIR = Path(tempfile.gettempdir())
LOCK_COOLDOWN = 30  # seconds


def _check_lockfile() -> bool:
    """Lockfile이 유효하면 True (스킵해야 함)."""
    lockfile = LOCK_DIR / f"cc-inbox-deliver-{SESSION}.lock"
    if lockfile.exists():
        try:
            age = time.time() - lockfile.stat().st_mtime
            if age < LOCK_COOLDOWN:
                return True
        except OSError:
            pass
    return False


def _touch_lockfile() -> None:
    lockfile = LOCK_DIR / f"cc-inbox-deliver-{SESSION}.lock"
    lockfile.touch()


def _tmux_session_exists(session: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", session],
        capture_output=True,
        timeout=5,
    )
    return result.returncode == 0


def _send_to_tmux(session: str, text: str) -> bool:
    """tmux send-keys로 텍스트 전달. 500자 초과 시 paste-buffer 사용."""
    try:
        if len(text) > 500:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", prefix="cc-inbox-", suffix=".txt", delete=False,
            )
            tmp.write(text)
            tmp.close()
            subprocess.run(
                ["tmux", "load-buffer", tmp.name],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["tmux", "paste-buffer", "-t", session],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", session, "Enter"],
                capture_output=True, timeout=5,
            )
            os.unlink(tmp.name)
        else:
            subprocess.run(
                ["tmux", "send-keys", "-t", session, text, "Enter"],
                capture_output=True, timeout=5,
            )
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False


def _format_messages(messages: list) -> str:
    """메시지 목록을 워커가 이해할 수 있는 텍스트로 포맷."""
    if len(messages) == 1:
        msg = messages[0]
        payload = msg.payload[:500]
        return (
            f"[msgbus #{msg.id}] {msg.sender} -> {msg.msg_type}: "
            f"{payload}"
        )

    lines = [f"[msgbus] {len(messages)}건의 메시지:"]
    for msg in messages:
        payload = msg.payload[:300]
        lines.append(
            f"  #{msg.id} [{msg.msg_type}] from {msg.sender}: {payload}"
        )
    return "\n".join(lines)


def main() -> None:
    if not SESSION:
        sys.exit(0)

    if _check_lockfile():
        sys.exit(0)

    config = MsgBusConfig.default()
    init_db(config)

    # Peek first (don't mark read yet)
    pending = peek(config, SESSION, limit=5)
    if not pending:
        sys.exit(0)

    # tmux 세션 존재 확인
    if not _tmux_session_exists(SESSION):
        sys.exit(0)

    # Receive (mark as read)
    messages = receive(config, SESSION, limit=5)
    if not messages:
        sys.exit(0)

    # Format and deliver
    text = _format_messages(messages)
    if _send_to_tmux(SESSION, text):
        _touch_lockfile()


if __name__ == "__main__":
    main()
