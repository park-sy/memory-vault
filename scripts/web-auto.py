#!/usr/bin/env python3
"""web-auto.py — Tier 2/3 Web Automation CLI.

사이트 어댑터 패턴 기반 브라우저 자동화.
ADR-004 준수: argparse + --json, exit code 1 + JSON stderr.

Usage:
  web-auto.py run       <domain> <flow> [--input '{}'] [--tier 2|3] [--dry-run]
  web-auto.py record    <domain> <flow> [--steps-json '[...]'] [--flow-type read|write]
  web-auto.py adapters  [--domain X]
  web-auto.py approve   <id> [--reject] [--reason ".."]
  web-auto.py approvals [--domain X] [--status pending]
  web-auto.py history   [--domain X] [--limit 20]
  web-auto.py session   <domain> [--export|--import file]
  web-auto.py check     <domain>
  web-auto.py backends
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# scripts/ 디렉토리를 모듈 검색 경로에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 세션 export/import 허용 경로
_SESSION_BASE = Path(__file__).resolve().parent.parent / "storage"

from web_auto_adapters import (
    check_adapter_health,
    list_adapters,
    load_adapter,
    register_flow,
    run_flow,
    save_adapter,
)
from web_auto_db import WebAutoDB
from web_auto_models import AutoResponse, now_iso


# ── Output Helpers ──────────────────────────────────────────────

def _output_json(data: dict, file=sys.stdout) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2), file=file)


def _output_error(error: str, domain: str = "", command: str = "") -> None:
    resp = AutoResponse(
        command=command,
        domain=domain,
        timestamp=now_iso(),
        success=False,
        error=error,
    )
    _output_json(json.loads(resp.to_json()), file=sys.stderr)
    sys.exit(1)


def _output_success(data: dict, domain: str = "", command: str = "") -> None:
    resp = AutoResponse(
        command=command,
        domain=domain,
        timestamp=now_iso(),
        success=True,
        data=data,
    )
    _output_json(json.loads(resp.to_json()))


# ── Commands ────────────────────────────────────────────────────

def _safe_session_path(user_path: str) -> Path:
    """세션 파일 경로를 storage/ 내로 제한."""
    resolved = (_SESSION_BASE / user_path).resolve()
    if not str(resolved).startswith(str(_SESSION_BASE.resolve())):
        raise ValueError(f"Path traversal attempt: {user_path!r}")
    return resolved


def cmd_run(args: argparse.Namespace) -> None:
    """플로우 실행."""
    # 입력 JSON 검증 (fail fast)
    try:
        json.loads(args.input)
    except json.JSONDecodeError as e:
        _output_error(f"INVALID_INPUT_JSON: {e}", domain=args.domain, command="run")

    result = run_flow(
        domain=args.domain,
        flow_name=args.flow,
        input_data_str=args.input,
        tier=args.tier,
        dry_run=args.dry_run,
        headless=not args.headed,
    )

    output = json.loads(result.to_json())
    if args.format == "markdown":
        _print_markdown_result(output)
    else:
        _output_json(output)

    if not result.success:
        sys.exit(1)


def cmd_record(args: argparse.Namespace) -> None:
    """어댑터에 플로우 등록/갱신."""
    try:
        adapter = register_flow(
            domain=args.domain,
            flow_name=args.flow,
            flow_type=args.flow_type,
            steps_json=args.steps_json,
            requires_auth=args.requires_auth,
        )
        _output_success(
            data={
                "domain": adapter.domain,
                "version": adapter.version,
                "flow_registered": args.flow,
                "flow_type": args.flow_type,
                "total_flows": len(adapter.flows),
            },
            domain=args.domain,
            command="record",
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        _output_error(f"INVALID_STEPS: {e}", domain=args.domain, command="record")


def cmd_adapters(args: argparse.Namespace) -> None:
    """어댑터 목록."""
    adapters = list_adapters(domain=args.domain)
    data = [
        {
            "domain": a.domain,
            "version": a.version,
            "flows": [{"name": f.name, "type": f.flow_type} for f in a.flows],
            "trust_level": a.trust_level,
            "rate_limit_seconds": a.rate_limit_seconds,
            "daily_cap": a.daily_cap,
        }
        for a in adapters
    ]
    _output_success(
        data={"adapters": data, "total": len(data)},
        command="adapters",
    )


def cmd_approve(args: argparse.Namespace) -> None:
    """승인/거부."""
    approval = WebAutoDB.get_approval(args.id)
    if approval is None:
        _output_error(f"Approval #{args.id} not found", command="approve")

    if approval.status != "pending":
        _output_error(
            f"Approval #{args.id} already {approval.status}",
            domain=approval.domain,
            command="approve",
        )

    approved = not args.reject
    WebAutoDB.decide_approval(args.id, approved=approved, reason=args.reason)

    _output_success(
        data={
            "approval_id": args.id,
            "decision": "approved" if approved else "rejected",
            "reason": args.reason,
            "domain": approval.domain,
            "flow": approval.flow_name,
        },
        domain=approval.domain,
        command="approve",
    )


def cmd_approvals(args: argparse.Namespace) -> None:
    """대기 중 승인 목록."""
    pending = WebAutoDB.get_pending_approvals(domain=args.domain)
    data = [a.to_dict() for a in pending]
    _output_success(
        data={"approvals": data, "total": len(data)},
        command="approvals",
    )


def cmd_history(args: argparse.Namespace) -> None:
    """실행 이력."""
    executions = WebAutoDB.list_executions(domain=args.domain, limit=args.limit)
    data = [e.to_dict() for e in executions]
    _output_success(
        data={"executions": data, "total": len(data)},
        command="history",
    )


def cmd_session(args: argparse.Namespace) -> None:
    """세션 관리."""
    if args.export_file:
        safe_path = _safe_session_path(args.export_file)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        session = WebAutoDB.load_session(args.domain)
        safe_path.write_text(
            json.dumps(session, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _output_success(
            data={"exported_to": str(safe_path), "domain": args.domain},
            domain=args.domain,
            command="session",
        )
    elif args.import_file:
        safe_path = _safe_session_path(args.import_file)
        if not safe_path.exists():
            _output_error(f"File not found: {args.import_file}", domain=args.domain, command="session")
        data = json.loads(safe_path.read_text(encoding="utf-8"))
        cookies = json.dumps(data.get("cookies", {}), ensure_ascii=False)
        ls = json.dumps(data.get("local_storage", {}), ensure_ascii=False)
        WebAutoDB.save_session(args.domain, cookies, ls)
        _output_success(
            data={"imported_from": str(safe_path), "domain": args.domain},
            domain=args.domain,
            command="session",
        )
    else:
        session = WebAutoDB.load_session(args.domain)
        has_cookies = bool(session.get("cookies"))
        has_ls = bool(session.get("local_storage"))
        _output_success(
            data={
                "domain": args.domain,
                "has_cookies": has_cookies,
                "has_local_storage": has_ls,
            },
            domain=args.domain,
            command="session",
        )


def cmd_check(args: argparse.Namespace) -> None:
    """어댑터 헬스체크."""
    health = check_adapter_health(args.domain)
    if health["status"] == "not_found":
        _output_error(f"Adapter not found: {args.domain}", domain=args.domain, command="check")
    _output_success(data=health, domain=args.domain, command="check")


def cmd_backends(_args: argparse.Namespace) -> None:
    """Playwright 설치 상태."""
    backends_info: dict = {"playwright_installed": False, "browsers": []}

    try:
        import playwright
        backends_info["playwright_installed"] = True
        backends_info["playwright_version"] = playwright.__version__
    except ImportError:
        _output_success(data=backends_info, command="backends")
        return

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            for browser_type in [p.chromium, p.firefox, p.webkit]:
                try:
                    b = browser_type.launch(headless=True)
                    b.close()
                    backends_info["browsers"].append(
                        {"name": browser_type.name, "status": "installed"}
                    )
                except Exception:
                    backends_info["browsers"].append(
                        {"name": browser_type.name, "status": "not_installed"}
                    )
    except Exception as e:
        backends_info["check_error"] = str(e)

    _output_success(data=backends_info, command="backends")


# ── Markdown Output ─────────────────────────────────────────────

def _print_markdown_result(output: dict) -> None:
    """결과를 마크다운으로 출력."""
    success = output.get("success", False)
    icon = "OK" if success else "FAIL"
    print(f"## [{icon}] {output.get('command', '')} — {output.get('domain', '')}")
    print(f"**Time:** {output.get('timestamp', '')}")
    print()

    if success:
        data = output.get("data", {})
        if data:
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"### {k}")
                    for item in v[:20]:
                        print(f"- {item}")
                else:
                    print(f"- **{k}:** {v}")
    else:
        print(f"**Error:** {output.get('error', 'unknown')}")
        meta = output.get("metadata", {})
        if meta.get("fallback"):
            print(f"\n> {meta.get('message', 'Tier 3 fallback needed')}")
    print()


# ── Arg Parser ──────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web-auto.py",
        description="Tier 2/3 Web Automation CLI (Playwright + Site Adapters)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Execute a flow")
    p_run.add_argument("domain", help="Site domain (e.g. ppomppu.co.kr)")
    p_run.add_argument("flow", help="Flow name (e.g. scrape_hot_deals)")
    p_run.add_argument("--input", default="{}", help="Input data as JSON string")
    p_run.add_argument("--tier", type=int, default=2, choices=[2, 3], help="Tier to use")
    p_run.add_argument("--dry-run", action="store_true", help="Simulate without browser")
    p_run.add_argument("--headed", action="store_true", help="Show browser window")
    p_run.add_argument("--format", default="json", choices=["json", "markdown"])
    p_run.set_defaults(func=cmd_run)

    # record
    p_rec = sub.add_parser("record", help="Register/update a flow adapter")
    p_rec.add_argument("domain", help="Site domain")
    p_rec.add_argument("flow", help="Flow name")
    p_rec.add_argument("--steps-json", required=True, help="Steps as JSON array")
    p_rec.add_argument("--flow-type", default="read", choices=["read", "write"])
    p_rec.add_argument("--requires-auth", action="store_true")
    p_rec.set_defaults(func=cmd_record)

    # adapters
    p_adp = sub.add_parser("adapters", help="List adapters")
    p_adp.add_argument("--domain", default=None, help="Filter by domain")
    p_adp.set_defaults(func=cmd_adapters)

    # approve
    p_apr = sub.add_parser("approve", help="Approve/reject a write request")
    p_apr.add_argument("id", type=int, help="Approval ID")
    p_apr.add_argument("--reject", action="store_true", help="Reject instead of approve")
    p_apr.add_argument("--reason", default="", help="Reason for decision")
    p_apr.set_defaults(func=cmd_approve)

    # approvals
    p_als = sub.add_parser("approvals", help="List pending approvals")
    p_als.add_argument("--domain", default=None)
    p_als.add_argument("--status", default="pending", choices=["pending", "approved", "rejected"])
    p_als.set_defaults(func=cmd_approvals)

    # history
    p_his = sub.add_parser("history", help="Execution history")
    p_his.add_argument("--domain", default=None)
    p_his.add_argument("--limit", type=int, default=20)
    p_his.set_defaults(func=cmd_history)

    # session
    p_ses = sub.add_parser("session", help="Session management")
    p_ses.add_argument("domain", help="Site domain")
    p_ses.add_argument("--export", dest="export_file", default=None, help="Export to file")
    p_ses.add_argument("--import", dest="import_file", default=None, help="Import from file")
    p_ses.set_defaults(func=cmd_session)

    # check
    p_chk = sub.add_parser("check", help="Adapter health check")
    p_chk.add_argument("domain", help="Site domain")
    p_chk.set_defaults(func=cmd_check)

    # backends
    p_bck = sub.add_parser("backends", help="Check Playwright installation")
    p_bck.set_defaults(func=cmd_backends)

    return parser


# ── Main ────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        _output_error(
            f"UNEXPECTED: {e}",
            domain=getattr(args, "domain", ""),
            command=args.command,
        )


if __name__ == "__main__":
    main()
