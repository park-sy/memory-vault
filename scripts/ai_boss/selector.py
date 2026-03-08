"""Boss Selector — 페르소나 선택 로직 (Level 0: 코드).

키워드 매칭 + 체크인 타입 기반으로 어떤 상사가 발동할지 결정한다.
"""

from typing import List

# ── Trigger Keywords ─────────────────────────────────────────────────────────

TRIGGER_KEYWORDS: dict[str, list[str]] = {
    "jinsu": [
        "진행", "완료", "마감", "끝", "보고", "PR", "머지", "배포",
        "done", "status", "우선순위", "일정", "계획", "오늘", "내일",
        "이번주", "데드라인", "deadline", "shipped",
    ],
    "miyoung": [
        "지침", "힘들", "고민", "커리어", "성장", "번아웃", "스트레스",
        "의욕", "방향", "목표", "지쳤", "모르겠", "못하겠", "실패",
        "불안", "걱정", "자신감", "동기", "쉬고",
    ],
    "junghoon": [
        "코드", "아키텍처", "설계", "리팩토링", "성능", "테스트", "기술",
        "패턴", "버그", "리뷰", "타입", "DB", "API", "인프라",
        "라이브러리", "프레임워크", "최적화", "보안",
    ],
}

# ── Checkin Boss Mapping ─────────────────────────────────────────────────────

CHECKIN_BOSSES: dict[str, list[str]] = {
    "morning": ["jinsu"],
    "evening": ["jinsu"],
    "weekly": ["jinsu", "miyoung", "junghoon"],
    "monthly": ["miyoung", "junghoon"],
}

# ── All-hands Triggers ───────────────────────────────────────────────────────

ALL_HANDS_KEYWORDS = [
    "전체 피드백", "전원 소집", "다 같이", "모두 의견",
]

DEFAULT_BOSS = "jinsu"


# ── Public API ───────────────────────────────────────────────────────────────

def select_bosses_for_message(
    text: str,
    active_bosses: List[str],
) -> List[str]:
    """메시지 텍스트 기반으로 발동할 상사 선택.

    Returns:
        발동할 상사 이름 리스트 (active_bosses 내에서만).
    """
    text_lower = text.lower()

    # 전원 소집 체크
    for keyword in ALL_HANDS_KEYWORDS:
        if keyword in text_lower:
            return [b for b in ["jinsu", "miyoung", "junghoon"] if b in active_bosses]

    # 키워드 매칭
    matched = []
    for boss, keywords in TRIGGER_KEYWORDS.items():
        if boss not in active_bosses:
            continue
        for kw in keywords:
            if kw.lower() in text_lower:
                matched.append(boss)
                break

    # 매칭 0건 → 기본(진수)
    if not matched:
        return [DEFAULT_BOSS] if DEFAULT_BOSS in active_bosses else active_bosses[:1]

    return matched


def select_bosses_for_checkin(
    checkin_type: str,
    active_bosses: List[str],
) -> List[str]:
    """체크인 타입별 발동 상사 선택.

    Returns:
        발동할 상사 이름 리스트.
    """
    candidates = CHECKIN_BOSSES.get(checkin_type, [DEFAULT_BOSS])
    return [b for b in candidates if b in active_bosses]
