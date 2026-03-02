"""web_auto_adapters.py — 어댑터 로드/저장 + Playwright 스텝 실행 엔진.

핵심 루프: Extension 탐색 → 패턴 추출 → Playwright 자동화 → 실패 시 재탐색
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from web_auto_db import WebAutoDB
from web_auto_models import (
    ActionStep,
    AdapterFlow,
    AutoResponse,
    SiteAdapter,
    now_iso,
)
from web_auto_safety import (
    demote_trust,
    evaluate_trust_promotion,
    pick_user_agent,
    pick_viewport,
    random_delay,
    run_safety_checks,
)

logger = logging.getLogger(__name__)

ADAPTERS_DIR = Path(__file__).resolve().parent.parent / "storage" / "site-adapters"
_STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"

# ── Domain Validation ──────────────────────────────────────────

_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]$")


def _validate_domain(domain: str) -> None:
    """도메인 이름 검증 (path traversal 방지)."""
    if not domain or ".." in domain or "/" in domain or not _DOMAIN_RE.match(domain):
        raise ValueError(f"Invalid domain: {domain!r}")


def _safe_url(url: str) -> str:
    """http/https 스킴만 허용 (javascript:, file:// 방지)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsafe URL scheme: {parsed.scheme!r}")
    return url


# ── Adapter I/O ─────────────────────────────────────────────────

def load_adapter(domain: str) -> SiteAdapter | None:
    """JSON 파일에서 어댑터 로드."""
    _validate_domain(domain)
    path = ADAPTERS_DIR / f"{domain}.json"
    if not path.exists():
        logger.warning("Adapter not found: %s", path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SiteAdapter.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Failed to load adapter %s: %s", domain, e)
        return None


def save_adapter(adapter: SiteAdapter) -> Path:
    """어댑터를 JSON 파일로 저장."""
    _validate_domain(adapter.domain)
    ADAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = ADAPTERS_DIR / f"{adapter.domain}.json"
    updated = replace(adapter, updated_at=now_iso())
    path.write_text(
        json.dumps(updated.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Adapter saved: %s", path)
    return path


def list_adapters(domain: str | None = None) -> list[SiteAdapter]:
    """모든 어댑터 목록 (또는 특정 도메인 필터)."""
    if not ADAPTERS_DIR.exists():
        return []
    adapters: list[SiteAdapter] = []
    for p in sorted(ADAPTERS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            a = SiteAdapter.from_dict(data)
            if domain and a.domain != domain:
                continue
            adapters.append(a)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Skipping invalid adapter %s: %s", p.name, e)
    return adapters


def register_flow(
    domain: str,
    flow_name: str,
    flow_type: str,
    steps_json: str,
    requires_auth: bool = False,
) -> SiteAdapter:
    """어댑터에 플로우 등록/갱신."""
    steps = tuple(ActionStep.from_dict(s) for s in json.loads(steps_json))
    new_flow = AdapterFlow(
        name=flow_name,
        flow_type=flow_type,
        steps=steps,
        requires_auth=requires_auth,
    )

    existing = load_adapter(domain)
    if existing:
        flows_list = [f for f in existing.flows if f.name != flow_name]
        flows_list.append(new_flow)
        adapter = replace(
            existing,
            flows=tuple(flows_list),
            version=existing.version + 1,
            updated_at=now_iso(),
        )
    else:
        adapter = SiteAdapter(
            domain=domain,
            version=1,
            created_at=now_iso(),
            updated_at=now_iso(),
            flows=(new_flow,),
        )

    save_adapter(adapter)
    return adapter


# ── Template Engine ─────────────────────────────────────────────

def _render_template(template: str, variables: dict[str, Any]) -> str:
    """{{변수}} 템플릿 치환."""
    def replacer(m: re.Match) -> str:
        key = m.group(1).strip()
        return str(variables.get(key, m.group(0)))
    return re.sub(r"\{\{(.+?)\}\}", replacer, template)


# ── Step Execution Result ──────────────────────────────────────

class StepResult:
    """스텝 실행 결과 (불변)."""
    __slots__ = ("ok", "error", "data", "extract_key")

    def __init__(
        self,
        ok: bool = True,
        error: str = "",
        data: Any = None,
        extract_key: str = "",
    ):
        self.ok = ok
        self.error = error
        self.data = data
        self.extract_key = extract_key


# ── Playwright Step Executor ────────────────────────────────────

def _locate_element(page: Any, selector: Any) -> Any:
    """SelectorSpec으로 요소 찾기. css → xpath → text_contains 순."""
    if selector.css:
        return page.locator(selector.css)
    if selector.xpath:
        return page.locator(f"xpath={selector.xpath}")
    if selector.text_contains:
        return page.get_by_text(selector.text_contains)
    return None


def _execute_step(
    page: Any,
    step: ActionStep,
    input_data: dict,
    extracted: dict,
) -> StepResult:
    """단일 Playwright 스텝 실행. extracted를 mutation하지 않고 StepResult로 반환."""
    try:
        variables = {**input_data, **extracted}

        if step.action == "navigate":
            url = _safe_url(_render_template(step.value, variables))
            page.goto(url, timeout=30000)
            return StepResult()

        if step.action == "wait":
            page.wait_for_timeout(step.wait_ms or 1000)
            return StepResult()

        if step.action == "click":
            el = _locate_element(page, step.selector)
            if el is None:
                return StepResult(ok=False, error=f"step {step.step_id}: no selector for click")
            el.first.click(timeout=10000)
            return StepResult()

        if step.action == "type":
            el = _locate_element(page, step.selector)
            if el is None:
                return StepResult(ok=False, error=f"step {step.step_id}: no selector for type")
            value = _render_template(step.value, variables)
            el.first.fill(value, timeout=10000)
            return StepResult()

        if step.action == "extract":
            el = _locate_element(page, step.selector)
            if el is None:
                return StepResult(ok=False, error=f"step {step.step_id}: no selector for extract")
            texts = el.all_text_contents()
            key = step.extract_key or f"extract_{step.step_id}"
            return StepResult(data=texts, extract_key=key)

        if step.action == "screenshot":
            ss_dir = _STORAGE_DIR / "screenshots"
            ss_dir.mkdir(parents=True, exist_ok=True)
            path = str(ss_dir / f"{now_iso().replace(':', '-')}_{step.step_id}.png")
            page.screenshot(path=path, full_page=True)
            key = step.extract_key or f"screenshot_{step.step_id}"
            return StepResult(data=path, extract_key=key)

        if step.action == "submit":
            el = _locate_element(page, step.selector)
            if el is None:
                page.keyboard.press("Enter")
            else:
                el.first.click(timeout=10000)
            return StepResult()

        return StepResult(ok=False, error=f"step {step.step_id}: unknown action {step.action!r}")

    except Exception as e:
        return StepResult(ok=False, error=f"step {step.step_id} ({step.action}): {e}")


# ── Session Management ──────────────────────────────────────────

def _restore_session(context: Any, domain: str) -> None:
    """저장된 쿠키를 브라우저 컨텍스트에 복원."""
    session = WebAutoDB.load_session(domain)
    cookies = session.get("cookies", [])
    if isinstance(cookies, list) and cookies:
        try:
            context.add_cookies(cookies)
        except Exception as e:
            logger.warning("Failed to restore cookies for %s: %s", domain, e)


def _save_session(context: Any, domain: str) -> None:
    """브라우저 컨텍스트의 쿠키를 저장."""
    try:
        cookies = context.cookies()
        WebAutoDB.save_session(domain, json.dumps(cookies, ensure_ascii=False))
    except Exception as e:
        logger.warning("Failed to save session for %s: %s", domain, e)


# ── Main Execution ──────────────────────────────────────────────

def execute_playwright(
    adapter: SiteAdapter,
    flow: AdapterFlow,
    input_data: dict,
    *,
    headless: bool = True,
    dry_run: bool = False,
) -> AutoResponse:
    """Playwright로 플로우 실행 (Tier 2)."""
    if dry_run:
        return AutoResponse(
            command="run",
            domain=adapter.domain,
            timestamp=now_iso(),
            success=True,
            data={"dry_run": True, "steps": [s.to_dict() for s in flow.steps]},
            metadata={"flow": flow.name, "tier": 2},
        )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return AutoResponse(
            command="run",
            domain=adapter.domain,
            timestamp=now_iso(),
            success=False,
            error="PLAYWRIGHT_NOT_INSTALLED: pip install playwright && playwright install chromium",
        )

    extracted: dict = {}
    error_response: AutoResponse | None = None

    try:
        with sync_playwright() as p:
            ua = pick_user_agent()
            vp = pick_viewport()

            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=ua, viewport=vp)
            try:
                _restore_session(context, adapter.domain)
                page = context.new_page()

                for step in flow.steps:
                    if step.step_id > 1:
                        delay_s = random_delay(adapter.rate_limit_seconds * 0.2)
                        time.sleep(max(0.3, delay_s))

                    result = _execute_step(page, step, input_data, extracted)

                    # Immutable merge: extract/screenshot 결과를 새 dict로 합침
                    if result.extract_key and result.data is not None:
                        extracted = {**extracted, result.extract_key: result.data}

                    if not result.ok and not step.optional:
                        error_response = AutoResponse(
                            command="run",
                            domain=adapter.domain,
                            timestamp=now_iso(),
                            success=False,
                            error=result.error,
                            metadata={"flow": flow.name, "tier": 2, "failed_step": step.step_id},
                        )
                        break

                _save_session(context, adapter.domain)
            finally:
                context.close()
                browser.close()

    except Exception as e:
        return AutoResponse(
            command="run",
            domain=adapter.domain,
            timestamp=now_iso(),
            success=False,
            error=f"PLAYWRIGHT_ERROR: {e}",
            metadata={"flow": flow.name, "tier": 2},
        )

    if error_response is not None:
        return error_response

    return AutoResponse(
        command="run",
        domain=adapter.domain,
        timestamp=now_iso(),
        success=True,
        data=extracted,
        metadata={"flow": flow.name, "tier": 2},
    )


# ── 3-Tier Orchestration ───────────────────────────────────────

def run_flow(
    domain: str,
    flow_name: str,
    input_data_str: str = "{}",
    *,
    tier: int = 2,
    dry_run: bool = False,
    headless: bool = True,
) -> AutoResponse:
    """3-Tier 폴백 로직으로 플로우 실행."""

    # 어댑터 로드
    adapter = load_adapter(domain)
    if adapter is None:
        return AutoResponse(
            command="run",
            domain=domain,
            timestamp=now_iso(),
            success=False,
            error=f"ADAPTER_NOT_FOUND: no adapter for {domain}",
        )

    # 플로우 찾기
    flow = adapter.find_flow(flow_name)
    if flow is None:
        available = [f.name for f in adapter.flows]
        return AutoResponse(
            command="run",
            domain=domain,
            timestamp=now_iso(),
            success=False,
            error=f"FLOW_NOT_FOUND: {flow_name!r}. Available: {available}",
        )

    # 안전 검사
    safety_result = run_safety_checks(adapter, flow, input_data_str)
    if safety_result is not None:
        return safety_result

    # rate limit 기록
    WebAutoDB.record_request(domain)

    # 실행 기록 생성
    exec_id = WebAutoDB.record_execution(
        domain=domain,
        flow_name=flow_name,
        flow_type=flow.flow_type,
        input_data=input_data_str,
        tier_used=tier,
    )

    try:
        input_data = json.loads(input_data_str) if input_data_str else {}
    except json.JSONDecodeError:
        input_data = {}

    # Tier 2: Playwright
    result = execute_playwright(adapter, flow, input_data, headless=headless, dry_run=dry_run)

    if result.success:
        WebAutoDB.update_execution(
            exec_id,
            status="success",
            output_data=json.dumps(result.data, ensure_ascii=False),
        )
        # trust level 승격 평가
        new_trust = evaluate_trust_promotion(adapter, flow_name)
        if new_trust:
            updated = replace(adapter, trust_level=new_trust, updated_at=now_iso())
            save_adapter(updated)
    else:
        WebAutoDB.update_execution(
            exec_id, status="failed", error=result.error,
        )
        # trust level 강등
        if flow.flow_type == "write":
            new_trust = demote_trust(adapter)
            if new_trust != adapter.trust_level:
                updated = replace(adapter, trust_level=new_trust, updated_at=now_iso())
                save_adapter(updated)

        # Tier 3 폴백 시그널
        if not dry_run:
            return AutoResponse(
                command="run",
                domain=domain,
                timestamp=now_iso(),
                success=False,
                error=result.error,
                metadata={
                    **result.metadata,
                    "fallback": "tier3",
                    "message": (
                        f"Tier 2 failed. Use Chrome Extension MCP to inspect {domain} "
                        f"and update adapter with: web-auto.py record {domain} {flow_name}"
                    ),
                },
            )

    return result


# ── Health Check ────────────────────────────────────────────────

def check_adapter_health(domain: str) -> dict:
    """어댑터 상태 확인."""
    adapter = load_adapter(domain)
    if adapter is None:
        return {"domain": domain, "status": "not_found"}

    executions = WebAutoDB.list_executions(domain=domain, limit=10)
    recent_statuses = [e.status for e in executions]
    success_rate = (
        recent_statuses.count("success") / len(recent_statuses)
        if recent_statuses
        else 0.0
    )

    return {
        "domain": domain,
        "status": "ok",
        "version": adapter.version,
        "trust_level": adapter.trust_level,
        "flows": [f.name for f in adapter.flows],
        "rate_limit_seconds": adapter.rate_limit_seconds,
        "daily_cap": adapter.daily_cap,
        "recent_success_rate": round(success_rate, 2),
        "recent_executions": len(recent_statuses),
    }
