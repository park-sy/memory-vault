"""web_auto_safety.py — 승인 게이트, rate limit, anti-detection.

Write 작업 보호:
  manual  → 매번 수동 승인 (기본값)
  review  → 실행 후 5분 내 거부 가능 (manual 10회 연속 성공)
  auto    → 즉시 실행, 로그만 (review 30회 연속 무거부)
  에러 1회 → 즉시 manual로 강등
"""
from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone

from web_auto_db import WebAutoDB
from web_auto_models import (
    AdapterFlow,
    AutoResponse,
    SiteAdapter,
    now_iso,
)

logger = logging.getLogger(__name__)

# ── Trust Level Thresholds ──────────────────────────────────────

PROMOTE_TO_REVIEW = 10   # manual → review: 연속 성공 N회
PROMOTE_TO_AUTO = 30     # review → auto: 연속 무거부 N회

# ── User-Agent Pool ─────────────────────────────────────────────

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:123.0) Gecko/20100101 Firefox/123.0",
)

# ── Viewport Pool ──────────────────────────────────────────────

VIEWPORTS = (
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
)


# ── Approval Gate ───────────────────────────────────────────────

def check_approval_gate(
    adapter: SiteAdapter,
    flow: AdapterFlow,
    input_data: str,
) -> dict:
    """Write 플로우 승인 게이트.

    Returns:
        {"allowed": bool, "approval_id": int | None, "message": str}
    """
    if flow.flow_type == "read":
        return {"allowed": True, "approval_id": None, "message": "read flow, no approval needed"}

    trust = adapter.trust_level

    if trust == "auto":
        logger.info("trust=auto, domain=%s flow=%s → auto-approved", adapter.domain, flow.name)
        return {"allowed": True, "approval_id": None, "message": "auto trust level"}

    if trust == "review":
        # review: 실행은 허용하되, approval 기록 남김
        summary = _build_action_summary(adapter, flow, input_data)
        aid = WebAutoDB.create_approval(adapter.domain, flow.name, summary, input_data)
        WebAutoDB.decide_approval(aid, approved=True, reason="review mode auto-approve")
        logger.info("trust=review, domain=%s flow=%s → review-approved (id=%d)", adapter.domain, flow.name, aid)
        return {"allowed": True, "approval_id": aid, "message": "review mode, auto-approved"}

    # trust == "manual"
    summary = _build_action_summary(adapter, flow, input_data)
    aid = WebAutoDB.create_approval(adapter.domain, flow.name, summary, input_data)
    logger.info("trust=manual, domain=%s flow=%s → pending (id=%d)", adapter.domain, flow.name, aid)
    return {
        "allowed": False,
        "approval_id": aid,
        "message": f"Manual approval required. Use: web-auto.py approve {aid}",
    }


def _build_action_summary(adapter: SiteAdapter, flow: AdapterFlow, input_data: str) -> str:
    """승인 요청에 표시할 요약 생성."""
    try:
        inp = json.loads(input_data) if input_data else {}
    except json.JSONDecodeError:
        inp = {}
    step_actions = [s.action for s in flow.steps]
    return (
        f"[{adapter.domain}] {flow.name} ({flow.flow_type}) "
        f"steps={step_actions} input_keys={list(inp.keys())}"
    )


# ── Trust Level Management ──────────────────────────────────────

def evaluate_trust_promotion(adapter: SiteAdapter, flow_name: str) -> str | None:
    """연속 성공 횟수 기반 trust level 승격 판단.

    Returns:
        새 trust level 또는 None (변경 없음)
    """
    successes = WebAutoDB.get_consecutive_successes(adapter.domain, flow_name)

    if adapter.trust_level == "manual" and successes >= PROMOTE_TO_REVIEW:
        logger.info(
            "Trust promotion: %s manual → review (consecutive=%d)",
            adapter.domain, successes,
        )
        return "review"

    if adapter.trust_level == "review" and successes >= PROMOTE_TO_AUTO:
        logger.info(
            "Trust promotion: %s review → auto (consecutive=%d)",
            adapter.domain, successes,
        )
        return "auto"

    return None


def demote_trust(adapter: SiteAdapter) -> str:
    """에러 발생 시 trust level 즉시 manual로 강등."""
    if adapter.trust_level != "manual":
        logger.warning("Trust demotion: %s %s → manual", adapter.domain, adapter.trust_level)
    return "manual"


# ── Rate Limit ──────────────────────────────────────────────────

def check_rate_limit(adapter: SiteAdapter) -> dict:
    """rate limit 확인.

    Returns:
        {"allowed": bool, "message": str}
    """
    if not WebAutoDB.check_rate_limit(adapter.domain, adapter.daily_cap):
        return {
            "allowed": False,
            "message": f"Daily cap reached ({adapter.daily_cap}) for {adapter.domain}",
        }

    last_req = WebAutoDB.get_last_request_time(adapter.domain)
    if last_req:
        try:
            last_dt = datetime.fromisoformat(last_req.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            elapsed = (now_dt - last_dt).total_seconds()
            if elapsed < adapter.rate_limit_seconds:
                wait_s = adapter.rate_limit_seconds - elapsed
                return {
                    "allowed": False,
                    "message": f"Rate limited. Wait {wait_s:.1f}s for {adapter.domain}",
                }
        except (ValueError, TypeError):
            pass

    return {"allowed": True, "message": "ok"}


# ── Anti-Detection ──────────────────────────────────────────────

def random_delay(base_seconds: float) -> float:
    """base ± 30% jitter 딜레이 (초)."""
    jitter = base_seconds * 0.3
    return base_seconds + random.uniform(-jitter, jitter)


def pick_user_agent() -> str:
    """User-Agent 풀에서 하나 선택 (세션 당 고정 권장)."""
    return random.choice(USER_AGENTS)


def pick_viewport() -> dict:
    """뷰포트 사이즈 풀에서 하나 선택."""
    return dict(random.choice(VIEWPORTS))


def check_duplicate_post(domain: str, input_data: str) -> bool:
    """같은 URL 중복 게시 방지."""
    try:
        data = json.loads(input_data) if input_data else {}
    except json.JSONDecodeError:
        return False
    url = data.get("url", data.get("link", ""))
    if not url:
        return False
    return WebAutoDB.has_duplicate_post(domain, url)


# ── Combined Safety Check ──────────────────────────────────────

def run_safety_checks(
    adapter: SiteAdapter,
    flow: AdapterFlow,
    input_data: str,
) -> AutoResponse | None:
    """모든 안전 검사 실행. 실패 시 AutoResponse 반환, 통과 시 None."""

    # 1. 중복 게시 체크 (write only)
    if flow.flow_type == "write" and check_duplicate_post(adapter.domain, input_data):
        return AutoResponse(
            command="run",
            domain=adapter.domain,
            timestamp=now_iso(),
            success=False,
            error="DUPLICATE_POST: same URL already posted successfully",
        )

    # 2. Rate limit
    rl = check_rate_limit(adapter)
    if not rl["allowed"]:
        return AutoResponse(
            command="run",
            domain=adapter.domain,
            timestamp=now_iso(),
            success=False,
            error=f"RATE_LIMITED: {rl['message']}",
        )

    # 3. 승인 게이트 (write only)
    if flow.flow_type == "write":
        gate = check_approval_gate(adapter, flow, input_data)
        if not gate["allowed"]:
            return AutoResponse(
                command="run",
                domain=adapter.domain,
                timestamp=now_iso(),
                success=False,
                error=f"APPROVAL_REQUIRED: {gate['message']}",
                metadata={"approval_id": gate["approval_id"]},
            )

    return None
