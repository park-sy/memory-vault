"""Token Gate — token-aware concurrency control for worker scaling.

Checks token budget availability before allowing new worker creation.
Integrates with whos-life Token Monitor for rate limit data.

Fallback: if Token Monitor is unavailable, uses hard MAX_POOL_SIZE cap.
"""

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from .config import (
    MAX_POOL_SIZE, WHOS_LIFE_DIR, WHOS_LIFE_CLI,
    get_runtime_int,
)

log = logging.getLogger("factory.token_gate")

# Token budget thresholds
UTILIZATION_HARD_LIMIT = 85.0    # Never scale if any window > 85%
UTILIZATION_SOFT_LIMIT = 70.0    # Warn but allow if < 85%
ESTIMATED_PCT_PER_WORKER = 5.0   # Estimated token cost per active worker session


@dataclass(frozen=True)
class TokenBudget:
    """Current token budget status."""
    available: bool           # Can we create a new worker?
    utilization_pct: float    # Current highest utilization across windows
    headroom_pct: float       # Remaining before hard limit
    max_workers: int          # Effective max workers given budget
    source: str               # "token_monitor" or "fallback"
    reason: str               # Human-readable explanation


def check_budget(current_worker_count: int) -> TokenBudget:
    """Check if token budget allows creating another worker.

    Returns a TokenBudget indicating whether scaling is permitted.
    """
    # Try Token Monitor first
    monitor_data = _query_token_monitor()
    if monitor_data is not None:
        return _evaluate_budget(monitor_data, current_worker_count)

    # Fallback: hard cap
    return _fallback_budget(current_worker_count)


def _query_token_monitor() -> Optional[dict]:
    """Query whos-life token-monitor for rate limit status."""
    if not WHOS_LIFE_DIR.exists():
        return None

    try:
        result = subprocess.run(
            [
                sys.executable, WHOS_LIFE_CLI,
                "feature", "token-monitor", "get-status", "--json",
            ],
            capture_output=True, text=True, timeout=15,
            cwd=str(WHOS_LIFE_DIR),
        )

        if result.returncode != 0:
            log.debug("Token monitor unavailable: %s", result.stderr[:100])
            return None

        data = json.loads(result.stdout)
        return data

    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        log.debug("Token monitor query failed: %s", e)
        return None


def _evaluate_budget(data: dict, current_worker_count: int) -> TokenBudget:
    """Evaluate token budget from Token Monitor data."""
    # Find highest utilization across all windows
    windows = data.get("windows", data.get("rate_limits", []))
    if not windows:
        return _fallback_budget(current_worker_count)

    max_util = 0.0
    for window in windows:
        util = float(window.get("utilization", window.get("utilization_pct", 0)))
        if util > max_util:
            max_util = util

    headroom = UTILIZATION_HARD_LIMIT - max_util
    estimated_new_worker_cost = ESTIMATED_PCT_PER_WORKER

    # Calculate max workers based on headroom
    if headroom <= 0:
        effective_max = current_worker_count  # Don't scale at all
    else:
        max_pool = get_runtime_int("max_pool_size", MAX_POOL_SIZE)
        additional = int(headroom / estimated_new_worker_cost)
        effective_max = min(current_worker_count + additional, max_pool)

    can_scale = (
        max_util < UTILIZATION_HARD_LIMIT
        and current_worker_count < effective_max
    )

    if max_util >= UTILIZATION_HARD_LIMIT:
        reason = f"토큰 사용률 {max_util:.1f}% — 하드 리밋 {UTILIZATION_HARD_LIMIT:.0f}% 초과"
    elif max_util >= UTILIZATION_SOFT_LIMIT:
        reason = f"토큰 사용률 {max_util:.1f}% — 소프트 리밋 경고 (스케일 가능)"
    elif not can_scale:
        reason = f"워커 수 상한 도달 ({effective_max})"
    else:
        reason = f"토큰 여유 {headroom:.1f}% — 스케일 가능"

    if max_util >= UTILIZATION_SOFT_LIMIT:
        log.warning("Token utilization at %.1f%% (soft limit: %.0f%%)", max_util, UTILIZATION_SOFT_LIMIT)

    return TokenBudget(
        available=can_scale,
        utilization_pct=max_util,
        headroom_pct=max(headroom, 0.0),
        max_workers=effective_max,
        source="token_monitor",
        reason=reason,
    )


def _fallback_budget(current_worker_count: int) -> TokenBudget:
    """Fallback when Token Monitor is unavailable — use hard cap."""
    max_pool = get_runtime_int("max_pool_size", MAX_POOL_SIZE)
    can_scale = current_worker_count < max_pool
    reason = (
        f"Token Monitor 미연결 — 하드 캡 {max_pool} 적용"
        if can_scale
        else f"풀 상한 {max_pool} 도달"
    )

    return TokenBudget(
        available=can_scale,
        utilization_pct=0.0,
        headroom_pct=100.0,
        max_workers=max_pool,
        source="fallback",
        reason=reason,
    )
