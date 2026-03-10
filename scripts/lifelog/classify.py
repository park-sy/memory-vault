"""Lifelog classifier — uses claude CLI (Haiku) for text classification."""

import json
import subprocess
import sys
from typing import Optional

CLASSIFY_PROMPT = """\
You are a life-log classifier. Given a short text entry from a person's daily life, classify it.

Return ONLY a JSON object with these fields:
- "categories": array of 1-3 category strings from this guide list (but you may add new ones if none fit):
  work, learning, side-project, food, expense, social, health, thought, life, travel, entertainment, exercise
- "tags": array of 1-5 short keyword tags (Korean or English, specific nouns/names)
- "sentiment": one of "positive", "neutral", "negative"

Examples:
Input: "점심에 파스타 먹었다"
Output: {"categories": ["food"], "tags": ["파스타", "점심"], "sentiment": "neutral"}

Input: "PR 3개 올렸다. 힘들었지만 뿌듯"
Output: {"categories": ["work"], "tags": ["PR", "코드리뷰"], "sentiment": "positive"}

Input: "영수랑 강남에서 저녁"
Output: {"categories": ["social", "food"], "tags": ["영수", "강남", "저녁"], "sentiment": "positive"}

Now classify this entry:
"""


def classify_text(text: str) -> Optional[dict]:
    """Classify text using claude CLI with Haiku model.

    Returns {"categories": [...], "tags": [...], "sentiment": "..."} or None on failure.
    """
    prompt = CLASSIFY_PROMPT + text

    try:
        result = subprocess.run(
            [
                "claude", "-p", prompt,
                "--model", "haiku",
                "--output-format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            print(f"[classify] claude CLI error: {result.stderr[:200]}", file=sys.stderr)
            return None

        response = json.loads(result.stdout)

        # claude --output-format json wraps response in {"result": "..."}
        raw_text = response.get("result", result.stdout)
        if isinstance(raw_text, str):
            # Extract JSON from the response text
            parsed = _extract_json(raw_text)
        else:
            parsed = raw_text

        if not parsed:
            return None

        return _validate_classification(parsed)

    except subprocess.TimeoutExpired:
        print("[classify] Timeout (30s)", file=sys.stderr)
        return None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[classify] Parse error: {e}", file=sys.stderr)
        return None


def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON object from text that may contain surrounding prose."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find JSON object in text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _validate_classification(data: dict) -> Optional[dict]:
    """Validate and normalize classification result."""
    categories = data.get("categories", [])
    tags = data.get("tags", [])
    sentiment = data.get("sentiment", "neutral")

    if not isinstance(categories, list):
        return None
    if not isinstance(tags, list):
        tags = []

    valid_sentiments = {"positive", "neutral", "negative"}
    if sentiment not in valid_sentiments:
        sentiment = "neutral"

    return {
        "categories": [str(c) for c in categories[:5]],
        "tags": [str(t) for t in tags[:10]],
        "sentiment": sentiment,
    }
