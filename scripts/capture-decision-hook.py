#!/usr/bin/env python3
"""PostToolUse hook — AskUserQuestion 응답을 decision-log에 자동 캡처.

Claude Code가 stdin으로 전달하는 JSON:
{
  "tool_name": "AskUserQuestion",
  "tool_input": { "questions": [...] },
  "tool_response": { "answers": {...}, "annotations": {...} }
}

Exit 0: 정상 (block하지 않음)
"""

import json
import subprocess
import sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = VAULT_DIR / "scripts" / "decision-clone.py"


def _extract_answers(payload: dict) -> dict:
    """tool_response 또는 tool_input에서 answers 추출. 여러 포맷 대응."""
    # 1) tool_response가 dict이고 answers 포함
    resp = payload.get("tool_response", {})
    if isinstance(resp, dict):
        answers = resp.get("answers")
        if answers and isinstance(answers, dict):
            return answers

    # 2) tool_response가 문자열이면 JSON 파싱 시도
    if isinstance(resp, str):
        try:
            parsed = json.loads(resp)
            if isinstance(parsed, dict) and "answers" in parsed:
                return parsed["answers"]
        except (json.JSONDecodeError, TypeError):
            pass

    # 3) tool_input.answers (permission component가 채운 경우)
    inp = payload.get("tool_input", {})
    if isinstance(inp, dict):
        answers = inp.get("answers")
        if answers and isinstance(answers, dict):
            return answers

    return {}


def _extract_annotations(payload: dict) -> dict:
    """annotations에서 사용자 노트 추출."""
    for source in [payload.get("tool_response", {}), payload.get("tool_input", {})]:
        if isinstance(source, dict):
            ann = source.get("annotations")
            if ann and isinstance(ann, dict):
                return ann
    return {}


def _has_question_ending(text: str) -> bool:
    """물음표 또는 한국어 질문 종결어미로 끝나는지 판별."""
    stripped = text.strip().rstrip(".")
    if stripped.endswith("?"):
        return True
    korean_endings = [
        "거야", "는거야", "건가", "일까", "할까", "볼까",
        "생각엔", "어때", "같아", "뭐야", "는데",
    ]
    return any(stripped.endswith(e) for e in korean_endings)


def _has_exploration_marker(text: str) -> bool:
    """탐색/반문 마커가 포함되어 있는지 판별."""
    markers = [
        "뭐야", "설명해", "어때", "말해봐", "뭐가 더",
        "다시 말해", "예를 들어", "예를들어", "너 생각",
        "내 생각이 어때", "아닌가", "아닐까", "어떻게 생각",
        "뭐가 중요", "이런거 말고", "개념적인거 말고",
    ]
    return any(m in text for m in markers)


def _is_exploratory(answer: str, options: list) -> bool:
    """선택이 아니라 탐색/질문인지 판별. 규칙 기반, LLM 0."""
    stripped = answer.strip()

    # 1. 질문 종결 → exploratory
    if _has_question_ending(stripped):
        return True

    # 2. 옵션 라벨과 정확히 일치 → 명확한 선택 (not exploratory)
    option_labels = {opt.get("label", "") for opt in options}
    if stripped in option_labels:
        return False

    # 3. 탐색/반문 마커 → exploratory
    if _has_exploration_marker(stripped):
        return True

    return False


def _clean_rationale(answer: str, note: str, options: list) -> str:
    """chosen과 rationale 중복 방지. Other 선택 시 rationale 분리."""
    if note:
        return note
    # Other 선택 (옵션에 없는 자유 입력)이면 rationale을 "user-input"으로
    option_labels = {opt.get("label", "") for opt in options}
    if answer.strip() not in option_labels:
        return "user-input"
    return "auto-captured"


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        payload = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return

    questions = payload.get("tool_input", {}).get("questions", [])
    answers = _extract_answers(payload)
    annotations = _extract_annotations(payload)

    if not questions or not answers:
        return

    for q in questions:
        question_text = q.get("question", "")
        answer = answers.get(question_text, "")
        if not answer or not question_text:
            continue

        q_options = q.get("options", [])
        options_labels = [opt.get("label", "") for opt in q_options]
        options_str = ", ".join(options_labels) if options_labels else "-"

        # annotations에서 사용자 노트 추출
        note = ""
        q_ann = annotations.get(question_text, {})
        if isinstance(q_ann, dict):
            note = q_ann.get("notes", "")

        rationale = _clean_rationale(answer, note, q_options)

        # 탐색/질문이면 태그에 exploratory 추가
        tags = "auto-captured"
        if _is_exploratory(answer, q_options):
            tags = "auto-captured, exploratory"

        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "add",
                "uncategorized",
                question_text,
                answer,
                rationale,
                "--options", options_str,
                "--confidence", "medium",
                "--tags", tags,
            ],
            capture_output=True,
            timeout=5,
        )


if __name__ == "__main__":
    main()
