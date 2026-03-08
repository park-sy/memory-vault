"""Message Sender — Telegram 전송 (Level 0: 코드).

상사 메시지를 1-3초 간격으로 Telegram boss 토픽에 전송한다.
"""

import random
import sys
import time
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from msgbus import MsgBusConfig, init_db, send
from .parser import BossMessage

# ── Constants ────────────────────────────────────────────────────────────────

BOSS_NAMES_KR = {
    "jinsu": "진수",
    "miyoung": "미영",
    "junghoon": "정훈",
}

MESSAGE_DELAY_RANGE = (1.0, 3.0)  # 메시지 간 지연 (초)


# ── Public API ───────────────────────────────────────────────────────────────


def send_boss_messages(
    messages: List[BossMessage],
    delay: bool = True,
) -> int:
    """상사 메시지를 Telegram boss 그룹으로 전송.

    Args:
        messages: BossMessage 리스트
        delay: 메시지 간 지연 여부 (단톡방 느낌)

    Returns:
        전송된 메시지 수.
    """
    config = MsgBusConfig.default()
    init_db(config)

    sent = 0
    for i, msg in enumerate(messages):
        boss_kr = BOSS_NAMES_KR.get(msg.boss, msg.boss)
        display_text = f"[{boss_kr}] {msg.text}"

        send(
            config,
            sender="ai-boss",
            recipient="telegram",
            msg_type="notify",
            payload={
                "text": display_text,
                "channel": "boss",
            },
        )
        sent += 1

        # 메시지 간 지연 (마지막 메시지 제외)
        if delay and i < len(messages) - 1:
            time.sleep(random.uniform(*MESSAGE_DELAY_RANGE))

    return sent
