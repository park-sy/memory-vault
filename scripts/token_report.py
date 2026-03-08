#!/usr/bin/env python3
"""Token Report — 토큰 사용량 7일 요약 리포트.

Token Optimizer 자율 탐색 시 호출하는 순수 Python 집계 스크립트 (LLM 미호출).
whos-life의 claude_token_usage DB에서 데이터를 읽어 요약 출력.

Usage:
    python3 scripts/token_report.py
    python3 scripts/token_report.py --days 14
    python3 scripts/token_report.py --json
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / "dev" / "whos-life" / "db" / "productivity.db"


def _get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row[0] > 0


def generate_report(days: int = 7, db_path: str = str(DB_PATH)) -> dict:
    """Generate token usage summary for the last N days.

    Returns a dict with all report sections.
    """
    if not Path(db_path).exists():
        return {"error": f"DB not found: {db_path}"}

    conn = _get_db(db_path)

    if not _has_table(conn, "claude_token_usage"):
        conn.close()
        return {"error": "claude_token_usage table not found"}

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # 1. Model breakdown
    model_rows = conn.execute(
        """SELECT model,
               COUNT(*) as msg_count,
               SUM(input_tokens) as input_total,
               SUM(output_tokens) as output_total,
               SUM(cache_read_tokens) as cache_read_total,
               SUM(cache_creation_tokens) as cache_create_total,
               SUM(input_tokens + output_tokens +
                   cache_read_tokens + cache_creation_tokens) as total
           FROM claude_token_usage
           WHERE message_timestamp >= ?
           GROUP BY model
           ORDER BY total DESC""",
        (cutoff,),
    ).fetchall()

    grand_total = sum(r["total"] for r in model_rows) if model_rows else 0
    by_model = []
    for r in model_rows:
        pct = (r["total"] / grand_total * 100) if grand_total > 0 else 0
        by_model.append({
            "model": r["model"],
            "messages": r["msg_count"],
            "input": r["input_total"],
            "output": r["output_total"],
            "cache_read": r["cache_read_total"],
            "cache_create": r["cache_create_total"],
            "total": r["total"],
            "pct": round(pct, 1),
        })

    # 2. Project breakdown
    project_rows = conn.execute(
        """SELECT project,
               COUNT(*) as msg_count,
               SUM(input_tokens + output_tokens +
                   cache_read_tokens + cache_creation_tokens) as total,
               SUM(cache_read_tokens) as cache_read_total
           FROM claude_token_usage
           WHERE message_timestamp >= ?
           GROUP BY project
           ORDER BY total DESC""",
        (cutoff,),
    ).fetchall()

    by_project = []
    for r in project_rows:
        pct = (r["total"] / grand_total * 100) if grand_total > 0 else 0
        cache_rate = (r["cache_read_total"] / r["total"] * 100) if r["total"] > 0 else 0
        by_project.append({
            "project": r["project"],
            "messages": r["msg_count"],
            "total": r["total"],
            "pct": round(pct, 1),
            "cache_hit_pct": round(cache_rate, 1),
        })

    # 3. Peak hours
    hour_rows = conn.execute(
        """SELECT CAST(strftime('%H', message_timestamp) AS INTEGER) as hour,
               SUM(input_tokens + output_tokens +
                   cache_read_tokens + cache_creation_tokens) as total
           FROM claude_token_usage
           WHERE message_timestamp >= ?
           GROUP BY hour
           ORDER BY total DESC
           LIMIT 5""",
        (cutoff,),
    ).fetchall()

    peak_hours = [{"hour": r["hour"], "total": r["total"]} for r in hour_rows]

    # 4. Cache hit rate (overall)
    cache_row = conn.execute(
        """SELECT
               COALESCE(SUM(cache_read_tokens), 0) as cache_read,
               COALESCE(SUM(input_tokens + output_tokens +
                   cache_read_tokens + cache_creation_tokens), 0) as total
           FROM claude_token_usage
           WHERE message_timestamp >= ?""",
        (cutoff,),
    ).fetchone()

    cache_hit_pct = (
        (cache_row["cache_read"] / cache_row["total"] * 100)
        if cache_row["total"] > 0 else 0
    )

    # 5. Daily average
    daily_rows = conn.execute(
        """SELECT date(message_timestamp) as day,
               SUM(input_tokens + output_tokens +
                   cache_read_tokens + cache_creation_tokens) as total
           FROM claude_token_usage
           WHERE message_timestamp >= ?
           GROUP BY day
           ORDER BY day""",
        (cutoff,),
    ).fetchall()

    active_days = len(daily_rows)
    daily_avg = grand_total // active_days if active_days > 0 else 0
    daily_data = [{"date": r["day"], "total": r["total"]} for r in daily_rows]

    # 6. Session count
    session_count = conn.execute(
        """SELECT COUNT(DISTINCT session_id)
           FROM claude_token_usage
           WHERE message_timestamp >= ?""",
        (cutoff,),
    ).fetchone()[0]

    conn.close()

    return {
        "period_days": days,
        "cutoff": cutoff,
        "grand_total": grand_total,
        "sessions": session_count,
        "active_days": active_days,
        "daily_avg": daily_avg,
        "cache_hit_pct": round(cache_hit_pct, 1),
        "by_model": by_model,
        "by_project": by_project,
        "peak_hours": peak_hours,
        "daily": daily_data,
    }


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def print_report(report: dict) -> None:
    """Print human-readable report to stdout."""
    if "error" in report:
        print(f"Error: {report['error']}", file=sys.stderr)
        sys.exit(1)

    days = report["period_days"]
    print(f"=== Token Usage Report ({days}일) ===")
    print(f"기간: {report['cutoff'][:10]} ~ {datetime.now().strftime('%Y-%m-%d')}")
    print(f"총 토큰: {_format_tokens(report['grand_total'])}")
    print(f"세션 수: {report['sessions']}")
    print(f"활성 일수: {report['active_days']}")
    print(f"일평균: {_format_tokens(report['daily_avg'])}")
    print(f"캐시 히트율: {report['cache_hit_pct']}%")

    print(f"\n--- 모델별 ---")
    print(f"{'모델':<40} {'메시지':>7} {'토큰':>10} {'비율':>6}")
    print("-" * 65)
    for m in report["by_model"]:
        print(f"{m['model']:<40} {m['messages']:>7} {_format_tokens(m['total']):>10} {m['pct']:>5.1f}%")

    print(f"\n--- 프로젝트별 ---")
    print(f"{'프로젝트':<35} {'메시지':>7} {'토큰':>10} {'비율':>6} {'캐시':>6}")
    print("-" * 70)
    for p in report["by_project"]:
        print(
            f"{p['project']:<35} {p['messages']:>7} "
            f"{_format_tokens(p['total']):>10} {p['pct']:>5.1f}% {p['cache_hit_pct']:>5.1f}%"
        )

    print(f"\n--- 피크 시간대 (KST) ---")
    for h in report["peak_hours"]:
        bar = "#" * min(int(h["total"] / max(report["peak_hours"][0]["total"], 1) * 20), 20)
        print(f"  {h['hour']:02d}:00  {_format_tokens(h['total']):>10}  {bar}")

    print(f"\n--- 일별 추이 ---")
    for d in report["daily"]:
        bar = "#" * min(int(d["total"] / max(report["daily_avg"], 1) * 10), 30)
        print(f"  {d['date']}  {_format_tokens(d['total']):>10}  {bar}")


def main():
    parser = argparse.ArgumentParser(description="Token usage summary report")
    parser.add_argument("--days", type=int, default=7, help="Number of days to analyze")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--db", default=str(DB_PATH), help="DB path override")
    args = parser.parse_args()

    report = generate_report(days=args.days, db_path=args.db)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
