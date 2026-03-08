"""Prompt Builder — 체크인/응답용 프롬프트 조합 (Level 1: 정형 LLM).

context.md + 활성 태스크 + 최근 피드백 + 페르소나 정의를 조합해서
Claude CLI에 전달할 프롬프트를 만든다.
"""

from pathlib import Path
from typing import List, Optional

from . import db

# ── Constants ────────────────────────────────────────────────────────────────

VAULT_DIR = Path(__file__).resolve().parent.parent.parent
BOSSES_DIR = VAULT_DIR / "03-projects" / "ai-boss" / "bosses"
CONTEXT_PATH = VAULT_DIR / "03-projects" / "ai-boss" / "context.md"

# ── Persona Loading ──────────────────────────────────────────────────────────


def _load_persona(boss_name: str) -> str:
    """보스 페르소나 파일 로드."""
    path = BOSSES_DIR / f"{boss_name}.md"
    if not path.exists():
        return f"# {boss_name}\n(페르소나 파일 없음)"
    return path.read_text(encoding="utf-8")


def _load_context() -> str:
    """온보딩 컨텍스트 로드."""
    if not CONTEXT_PATH.exists():
        return "(컨텍스트 미작성)"
    return CONTEXT_PATH.read_text(encoding="utf-8")


# ── Task Summary ─────────────────────────────────────────────────────────────


def _format_tasks(tasks: List[db.Task]) -> str:
    """활성 태스크를 텍스트로 포맷."""
    if not tasks:
        return "(활성 태스크 없음)"
    lines = []
    for t in tasks[:15]:  # 최대 15개
        status_icon = {"active": "🔵", "blocked": "🔴"}.get(t.status, "⚪")
        due = f" (마감: {t.due_date})" if t.due_date else ""
        blocked = f" [차단: {t.blocked_reason}]" if t.blocked_reason else ""
        lines.append(f"- {status_icon} [{t.horizon}] {t.title}{due}{blocked}")
    return "\n".join(lines)


def _format_recent_feedback(feedbacks: List[db.Feedback]) -> str:
    """최근 피드백을 텍스트로 포맷."""
    if not feedbacks:
        return "(최근 피드백 없음)"
    lines = []
    for f in feedbacks[:5]:
        lines.append(f"- [{f.boss}] {f.content[:100]}")
    return "\n".join(lines)


# ── Public API ───────────────────────────────────────────────────────────────


def build_checkin_prompt(
    checkin_type: str,
    bosses: List[str],
    db_path: str = db.DB_PATH,
) -> str:
    """체크인용 프롬프트 조합.

    Args:
        checkin_type: morning, evening, weekly, monthly
        bosses: 발동할 상사 이름 리스트
        db_path: DB 경로

    Returns:
        Claude CLI에 전달할 전체 프롬프트 문자열.
    """
    context = _load_context()
    tasks = db.get_active_tasks(db_path)
    recent_fb = db.get_recent_feedback(5, db_path)

    persona_sections = []
    for boss in bosses:
        persona_sections.append(_load_persona(boss))

    checkin_desc = {
        "morning": "아침 체크인. 오늘 할 일 정리, 우선순위 확인, 동기부여.",
        "evening": "저녁 리캡. 오늘 성과 정리, 잘한 점 인정, 내일 준비.",
        "weekly": "주간 리뷰. 한 주 회고, 성장 포인트, 다음 주 방향, 감정 체크.",
        "monthly": "월간 회고. 장기 목표 점검, 성장 지표, 커리어 방향.",
    }.get(checkin_type, "체크인")

    boss_names = ", ".join(bosses)

    return f"""너는 상엽의 AI 상사 패널이다. 지금은 {checkin_type} 체크인이다.

## 체크인 설명
{checkin_desc}

## 발동 상사
{boss_names}

## 페르소나
{chr(10).join(persona_sections)}

## 상엽 컨텍스트
{context}

## 현재 활성 태스크
{_format_tasks(tasks)}

## 최근 피드백
{_format_recent_feedback(recent_fb)}

## 출력 규칙
- 반드시 JSON 배열로 출력. 다른 텍스트 없이 JSON만.
- 각 상사별 1개 메시지. 형식: [{{"boss": "이름", "text": "메시지"}}, ...]
- 각 상사의 말투와 관점을 정확히 반영.
- 한국어로 작성.
- 메시지는 자연스러운 대화체. 존댓말 안 씀.
- 각 메시지 100자 내외. 간결하게.
"""


def build_response_prompt(
    user_message: str,
    bosses: List[str],
    db_path: str = db.DB_PATH,
) -> str:
    """사용자 메시지에 대한 응답 프롬프트 조합.

    Args:
        user_message: 상엽이 보낸 메시지
        bosses: 발동할 상사 이름 리스트
        db_path: DB 경로

    Returns:
        Claude CLI에 전달할 전체 프롬프트 문자열.
    """
    context = _load_context()
    tasks = db.get_active_tasks(db_path)
    recent_fb = db.get_recent_feedback(5, db_path)

    persona_sections = []
    for boss in bosses:
        persona_sections.append(_load_persona(boss))

    boss_names = ", ".join(bosses)

    return f"""너는 상엽의 AI 상사 패널이다. 상엽이 메시지를 보냈다.

## 발동 상사
{boss_names}

## 페르소나
{chr(10).join(persona_sections)}

## 상엽 컨텍스트
{context}

## 현재 활성 태스크
{_format_tasks(tasks)}

## 최근 피드백
{_format_recent_feedback(recent_fb)}

## 상엽의 메시지
{user_message}

## 출력 규칙
- 반드시 JSON 배열로 출력. 다른 텍스트 없이 JSON만.
- 발동된 상사만 메시지 작성. 형식: [{{"boss": "이름", "text": "메시지"}}, ...]
- 각 상사의 말투와 관점을 정확히 반영.
- 한국어로 작성.
- 메시지는 자연스러운 대화체. 존댓말 안 씀.
- 상엽 메시지에 적절히 반응. 단순 인사면 짧게, 깊은 고민이면 깊게.
- 각 메시지 150자 내외. 필요 시 더 길어도 됨.
"""
