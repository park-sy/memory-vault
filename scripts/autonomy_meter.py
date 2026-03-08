#!/usr/bin/env python3
"""autonomy_meter.py — 자율성 레벨 측정기 (Phase 1).

기존 MsgBus + Feature Factory DB에서 데이터를 읽어
HIR, UET, AGR, DAR 4개 지표를 계산하고 L1~L4 레벨을 판정한다.

Phase 1: 스키마 변경 없이 현재 데이터만 사용.
- HIR: MsgBus에서 상엽(telegram) → 에이전트 메시지 빈도
- UET: 상엽 메시지 간 gap으로 무인 실행 시간 추정
- AGR: Phase 2에서 work_queue.created_by 추가 후 활성화 (현재 0)
- DAR: pending_approvals에서 자동 통과 vs 승인 요청 비율

Usage:
    python3 scripts/autonomy_meter.py                # 최근 7일 요약
    python3 scripts/autonomy_meter.py --days 30      # 최근 30일
    python3 scripts/autonomy_meter.py --json          # JSON 출력
    python3 scripts/autonomy_meter.py --history        # 일별 추이
"""

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── Paths ────────────────────────────────────────────────────────────────────

VAULT_DIR = Path(__file__).parent.parent
STORAGE_DIR = VAULT_DIR / "storage"
MSGBUS_DB = str(STORAGE_DIR / "msgbus.db")      # was mailbox.db
FACTORY_DB = str(STORAGE_DIR / "feature-factory.db")

# mailbox.db가 실제 이름일 수 있음 — 둘 다 체크
_MSGBUS_CANDIDATES = [
    STORAGE_DIR / "msgbus.db",
    STORAGE_DIR / "mailbox.db",
]


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Metrics:
    hir: float    # Human Intervention Rate (per hour)
    uet: float    # Unattended Execution Time ratio (0~1)
    agr: float    # AI-Generated task Ratio (0~1)
    dar: float    # Decision Autonomy Rate (0~1)


@dataclass(frozen=True)
class LevelResult:
    level: int
    metrics: Metrics
    bottleneck: str
    detail: str
    period_days: int
    sample_counts: dict
    confidence: str       # "sufficient" | "insufficient"
    insufficient_reasons: tuple  # 어떤 최소 조건이 미달인지


# ── DB Helpers ───────────────────────────────────────────────────────────────

def _find_msgbus_db() -> Optional[str]:
    for p in _MSGBUS_CANDIDATES:
        if p.exists():
            return str(p)
    return None


@contextmanager
def _connect(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ── Metric Calculators ───────────────────────────────────────────────────────

def calc_hir(days: int) -> tuple[float, dict]:
    """Human Intervention Rate: 시간당 상엽 개입 횟수.

    MsgBus에서 sender='telegram' 메시지를 상엽 개입으로 간주.
    """
    db_path = _find_msgbus_db()
    if not db_path:
        return 0.0, {"human_messages": 0, "total_hours": 0, "source": "no_db"}

    with _connect(db_path) as conn:
        # 상엽이 보낸 메시지 (telegram → 에이전트)
        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM messages
               WHERE sender = 'telegram'
                 AND msg_type IN ('task', 'command', 'notify')
                 AND created_at > datetime('now', ?)""",
            (f"-{days} days",),
        ).fetchone()
        human_msgs = row["cnt"] if row else 0

        # 전체 실행 시간 추정: 기간 내 첫 메시지 ~ 마지막 메시지
        span_row = conn.execute(
            """SELECT
                MIN(created_at) as first_at,
                MAX(created_at) as last_at
               FROM messages
               WHERE created_at > datetime('now', ?)""",
            (f"-{days} days",),
        ).fetchone()

        total_hours = days * 24  # fallback: 기간 전체
        if span_row and span_row["first_at"] and span_row["last_at"]:
            try:
                first = datetime.fromisoformat(span_row["first_at"])
                last = datetime.fromisoformat(span_row["last_at"])
                span_hours = (last - first).total_seconds() / 3600
                if span_hours > 0:
                    total_hours = span_hours
            except (ValueError, TypeError):
                pass

    hir = human_msgs / total_hours if total_hours > 0 else 0.0
    detail = {
        "human_messages": human_msgs,
        "total_hours": round(total_hours, 1),
        "source": db_path,
    }
    return round(hir, 3), detail


def calc_uet(days: int) -> tuple[float, dict]:
    """Unattended Execution Time: 무인 실행 시간 비율.

    상엽 메시지 타임스탬프 간 gap을 측정.
    gap > 30분이면 "무인 구간"으로 간주.
    """
    db_path = _find_msgbus_db()
    if not db_path:
        return 0.0, {"unattended_hours": 0, "active_hours": 0, "source": "no_db"}

    gap_threshold_minutes = 30

    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT created_at FROM messages
               WHERE sender = 'telegram'
                 AND created_at > datetime('now', ?)
               ORDER BY created_at""",
            (f"-{days} days",),
        ).fetchall()

    if len(rows) < 2:
        return 0.0, {
            "unattended_hours": 0,
            "active_hours": 0,
            "message_count": len(rows),
            "source": db_path,
        }

    timestamps = []
    for r in rows:
        try:
            timestamps.append(datetime.fromisoformat(r["created_at"]))
        except (ValueError, TypeError):
            continue

    if len(timestamps) < 2:
        return 0.0, {"unattended_hours": 0, "active_hours": 0, "source": db_path}

    attended_minutes = 0.0
    unattended_minutes = 0.0

    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60
        if gap <= gap_threshold_minutes:
            attended_minutes += gap
        else:
            unattended_minutes += gap

    total = attended_minutes + unattended_minutes
    uet = unattended_minutes / total if total > 0 else 0.0

    detail = {
        "unattended_hours": round(unattended_minutes / 60, 1),
        "attended_hours": round(attended_minutes / 60, 1),
        "message_count": len(timestamps),
        "gap_threshold_min": gap_threshold_minutes,
        "source": db_path,
    }
    return round(uet, 3), detail


def calc_agr(days: int) -> tuple[float, dict]:
    """AI-Generated task Ratio: AI가 생성한 태스크 비율.

    Phase 1: work_queue에 created_by 컬럼이 없으므로 항상 0.
    Phase 2에서 활성화.
    """
    return 0.0, {"status": "phase2_pending", "note": "work_queue.created_by 컬럼 추가 후 활성화"}


def calc_dar(days: int) -> tuple[float, dict]:
    """Decision Autonomy Rate: 자율 판단 비율.

    pending_approvals에서 승인 요청 대비 자동 통과 비율.
    supervision=off일 때 게이트를 건너뛴 횟수를 factory_events에서 추정.
    """
    factory_path = Path(FACTORY_DB)
    if not factory_path.exists():
        return 0.0, {"approvals": 0, "auto_passed": 0, "source": "no_db"}

    with _connect(FACTORY_DB) as conn:
        # 승인 요청 수
        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM pending_approvals
               WHERE created_at > datetime('now', ?)""",
            (f"-{days} days",),
        ).fetchone()
        approval_count = row["cnt"] if row else 0

        # 자동 통과 이벤트 (supervision off 시 gate skip)
        auto_row = conn.execute(
            """SELECT COUNT(*) as cnt FROM factory_events
               WHERE event_type IN ('gate_auto_passed', 'gate_skipped')
                 AND created_at > datetime('now', ?)""",
            (f"-{days} days",),
        ).fetchone()
        auto_passed = auto_row["cnt"] if auto_row else 0

    total_gates = approval_count + auto_passed
    dar = auto_passed / total_gates if total_gates > 0 else 0.0

    detail = {
        "approval_requests": approval_count,
        "auto_passed": auto_passed,
        "total_gates": total_gates,
        "source": FACTORY_DB,
    }
    return round(dar, 3), detail


# ── Level Judgment ───────────────────────────────────────────────────────────

_LEVEL_THRESHOLDS = [
    # (level, hir_max, agr_min, uet_min, dar_min)
    (4, 0.1, 0.6, 0.9, 0.7),
    (3, 0.5, 0.2, 0.7, 0.3),
    (2, 2.0, 0.0, 0.3, 0.0),
]

_BOTTLENECK_LABELS = {
    "hir": "Human Intervention Rate (상엽 개입 빈도가 높음)",
    "agr": "AI-Generated Ratio (AI 태스크 생성이 적음)",
    "uet": "Unattended Execution (무인 실행 시간이 짧음)",
    "dar": "Decision Autonomy (자율 판단 비율이 낮음)",
}

# ── Minimum Sample Requirements ──────────────────────────────────────────────
# 데이터가 부족하면 지표가 낮아도 상위 레벨로 판정하지 않는다.
# "데이터 없음"과 "진짜 자율적"을 구분하기 위한 안전장치.

_MIN_SAMPLES = {
    # L2 이상 판정에 필요한 최소 조건
    "min_human_messages": 50,     # HIR: 하루 ~7건 × 7일
    "min_total_gates": 20,        # DAR: 4~5 게이트 × 4~5 태스크
    "min_tasks": 10,              # AGR: 비율 의미 있으려면 최소 10개
    "min_execution_hours": 72,    # 최소 3일 가동해야 패턴 관측 가능
}


def check_sample_sufficiency(sample_counts: dict) -> tuple[bool, list]:
    """최소 샘플 조건 충족 여부 확인. (sufficient, reasons)."""
    reasons = []

    hir_data = sample_counts.get("hir", {})
    human_msgs = hir_data.get("human_messages", 0)
    total_hours = hir_data.get("total_hours", 0)

    if human_msgs < _MIN_SAMPLES["min_human_messages"]:
        reasons.append(
            f"HIR: 메시지 {human_msgs}건 < 최소 {_MIN_SAMPLES['min_human_messages']}건"
        )

    if total_hours < _MIN_SAMPLES["min_execution_hours"]:
        reasons.append(
            f"UET: 실행시간 {total_hours:.1f}h < 최소 {_MIN_SAMPLES['min_execution_hours']}h"
        )

    dar_data = sample_counts.get("dar", {})
    total_gates = dar_data.get("total_gates", 0)
    if total_gates < _MIN_SAMPLES["min_total_gates"]:
        reasons.append(
            f"DAR: 게이트 {total_gates}건 < 최소 {_MIN_SAMPLES['min_total_gates']}건"
        )

    return len(reasons) == 0, reasons


def judge_level(metrics: Metrics, sample_counts: Optional[dict] = None) -> tuple[int, str, str, str, tuple]:
    """4개 지표로 레벨 판정. 병목 기반 — 가장 낮은 지표가 레벨 결정.

    Returns: (level, bottleneck, detail, confidence, insufficient_reasons)
    """
    # 샘플 충분성 체크 — 부족하면 L1 고정
    confidence = "sufficient"
    insufficient_reasons = ()

    if sample_counts is not None:
        sufficient, reasons = check_sample_sufficiency(sample_counts)
        if not sufficient:
            confidence = "insufficient"
            insufficient_reasons = tuple(reasons)
            bottleneck = _find_bottleneck(metrics, 1)
            return 1, bottleneck, _level_description(1), confidence, insufficient_reasons

    for level, hir_max, agr_min, uet_min, dar_min in _LEVEL_THRESHOLDS:
        if (metrics.hir <= hir_max
                and metrics.agr >= agr_min
                and metrics.uet >= uet_min
                and metrics.dar >= dar_min):
            bottleneck = _find_bottleneck(metrics, level)
            detail = _level_description(level)
            return level, bottleneck, detail, confidence, insufficient_reasons

    bottleneck = _find_bottleneck(metrics, 1)
    return 1, bottleneck, _level_description(1), confidence, insufficient_reasons


def _find_bottleneck(metrics: Metrics, current_level: int) -> str:
    """다음 레벨로 올라가려면 어떤 지표를 개선해야 하는지."""
    if current_level >= 4:
        return "none (max level)"

    target_idx = next(
        (i for i, (lv, *_) in enumerate(_LEVEL_THRESHOLDS) if lv == current_level + 1),
        None,
    )
    if target_idx is None:
        return "unknown"

    _, hir_max, agr_min, uet_min, dar_min = _LEVEL_THRESHOLDS[target_idx]

    gaps = {}
    if metrics.hir > hir_max:
        gaps["hir"] = metrics.hir - hir_max
    if metrics.agr < agr_min:
        gaps["agr"] = agr_min - metrics.agr
    if metrics.uet < uet_min:
        gaps["uet"] = uet_min - metrics.uet
    if metrics.dar < dar_min:
        gaps["dar"] = dar_min - metrics.dar

    if not gaps:
        return "none (ready for next level)"

    worst = max(gaps, key=gaps.get)
    return _BOTTLENECK_LABELS.get(worst, worst)


def _level_description(level: int) -> str:
    descriptions = {
        1: "L1: 상엽 지시 → 에이전트 실행 (완전 수동)",
        2: "L2: 에이전트가 백로그에서 다음 작업 자동 선택",
        3: "L3: 에이전트가 파생 작업을 스스로 생성",
        4: "L4: 목표 기반 자율 계획·실행",
    }
    return descriptions.get(level, f"L{level}: unknown")


# ── Main Calculation ─────────────────────────────────────────────────────────

def measure(days: int = 7) -> LevelResult:
    """전체 측정 실행."""
    hir, hir_detail = calc_hir(days)
    uet, uet_detail = calc_uet(days)
    agr, agr_detail = calc_agr(days)
    dar, dar_detail = calc_dar(days)

    metrics = Metrics(hir=hir, uet=uet, agr=agr, dar=dar)

    sample_counts = {
        "hir": hir_detail,
        "uet": uet_detail,
        "agr": agr_detail,
        "dar": dar_detail,
    }

    level, bottleneck, detail, confidence, insufficient_reasons = judge_level(
        metrics, sample_counts
    )

    return LevelResult(
        level=level,
        metrics=metrics,
        bottleneck=bottleneck,
        detail=detail,
        period_days=days,
        sample_counts=sample_counts,
        confidence=confidence,
        insufficient_reasons=insufficient_reasons,
    )


def daily_history(days: int = 30) -> List[dict]:
    """일별 HIR/UET 추이 (간이 버전)."""
    db_path = _find_msgbus_db()
    if not db_path:
        return []

    history = []
    with _connect(db_path) as conn:
        for offset in range(days):
            day_start = f"-{offset + 1} days"
            day_end = f"-{offset} days"

            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM messages
                   WHERE sender = 'telegram'
                     AND msg_type IN ('task', 'command', 'notify')
                     AND created_at > datetime('now', ?)
                     AND created_at <= datetime('now', ?)""",
                (day_start, day_end),
            ).fetchone()

            msg_count = row["cnt"] if row else 0

            # 날짜 계산
            date_row = conn.execute(
                "SELECT date('now', ?) as d", (day_end,)
            ).fetchone()
            date_str = date_row["d"] if date_row else f"day-{offset}"

            history.append({
                "date": date_str,
                "human_messages": msg_count,
                "hir_estimate": round(msg_count / 24, 3),  # 24h 기준
            })

    history.reverse()
    return history


# ── CLI ──────────────────────────────────────────────────────────────────────

_LEVEL_BARS = {1: "█░░░", 2: "██░░", 3: "███░", 4: "████"}


def _print_report(result: LevelResult) -> None:
    m = result.metrics
    bar = _LEVEL_BARS.get(result.level, "????")

    print(f"\n{'=' * 52}")
    print(f"  AUTONOMY METER  |  {result.detail}")
    print(f"{'=' * 52}")
    confidence_mark = "" if result.confidence == "sufficient" else " *"
    print(f"  Level: {bar}  L{result.level}{confidence_mark}")
    print(f"  Period: last {result.period_days} days")

    if result.confidence == "insufficient":
        print(f"{'─' * 52}")
        print(f"  * DATA INSUFFICIENT — L1 forced. Reasons:")
        for reason in result.insufficient_reasons:
            print(f"    - {reason}")

    print(f"{'─' * 52}")
    print(f"  HIR  (Human Intervention Rate) : {m.hir:>7.3f} /h")
    print(f"  UET  (Unattended Execution)    : {m.uet:>7.1%}")
    print(f"  AGR  (AI-Generated Ratio)      : {m.agr:>7.1%}")
    print(f"  DAR  (Decision Autonomy)       : {m.dar:>7.1%}")
    print(f"{'─' * 52}")
    print(f"  Bottleneck: {result.bottleneck}")
    print(f"{'─' * 52}")

    # Sample details
    for key, detail in result.sample_counts.items():
        tag = key.upper()
        if isinstance(detail, dict):
            parts = [f"{k}={v}" for k, v in detail.items() if k != "source"]
            print(f"  [{tag}] {', '.join(parts)}")

    print(f"{'=' * 52}\n")


def _print_history(history: List[dict]) -> None:
    if not history:
        print("No data available.")
        return

    print(f"\n{'=' * 44}")
    print(f"  DAILY HIR TREND (messages/day)")
    print(f"{'=' * 44}")

    max_msgs = max((d["human_messages"] for d in history), default=1) or 1
    bar_width = 20

    for day in history:
        count = day["human_messages"]
        bar_len = int((count / max_msgs) * bar_width)
        bar = "█" * bar_len + "░" * (bar_width - bar_len)
        print(f"  {day['date']}  {bar}  {count:>3}")

    print(f"{'=' * 44}\n")


def main():
    parser = argparse.ArgumentParser(description="Autonomy Level Meter (Phase 1)")
    parser.add_argument("--days", type=int, default=7, help="Measurement period in days (default: 7)")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    parser.add_argument("--history", action="store_true", help="Show daily trend")
    args = parser.parse_args()

    if args.history:
        hist = daily_history(args.days)
        if args.as_json:
            print(json.dumps(hist, ensure_ascii=False, indent=2))
        else:
            _print_history(hist)
        return

    result = measure(args.days)

    if args.as_json:
        output = {
            "level": result.level,
            "confidence": result.confidence,
            "insufficient_reasons": list(result.insufficient_reasons),
            "metrics": asdict(result.metrics),
            "bottleneck": result.bottleneck,
            "detail": result.detail,
            "period_days": result.period_days,
            "samples": result.sample_counts,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        _print_report(result)


if __name__ == "__main__":
    main()
