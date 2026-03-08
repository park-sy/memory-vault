#!/usr/bin/env python3
"""Stop hook — 세션 로그 미작성 경고.

세션 종료 시 오늘 날짜의 세션 파일이 없으면 user-facing 경고를 출력한다.
Claude가 이 경고를 보고 세션 로그를 작성하도록 유도.
"""

import sys
from datetime import datetime
from pathlib import Path

VAULT_DIR = Path(__file__).parent.parent
SESSIONS_DIR = VAULT_DIR / "05-sessions"


def main() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    session_file = SESSIONS_DIR / f"{today}.md"

    if not session_file.exists():
        # user-prompt output이 Claude에게 보임
        print(
            f"[session-log-check] 오늘({today}) 세션 로그가 없습니다. "
            f"05-sessions/{today}.md 작성이 필요합니다.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
