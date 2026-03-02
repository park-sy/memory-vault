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

        options = [opt.get("label", "") for opt in q.get("options", [])]
        options_str = ", ".join(options) if options else "-"

        # annotations에서 사용자 노트 추출
        note = ""
        q_ann = annotations.get(question_text, {})
        if isinstance(q_ann, dict):
            note = q_ann.get("notes", "")

        rationale = note if note else "auto-captured"

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
                "--tags", "auto-captured",
            ],
            capture_output=True,
            timeout=5,
        )


if __name__ == "__main__":
    main()
