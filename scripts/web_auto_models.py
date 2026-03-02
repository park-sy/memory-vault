"""web_auto_models.py — Tier 2/3 Web Automation 데이터 모델.

모든 모델은 frozen dataclass로 불변성 보장.
web-search.py 패턴을 따름.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ── Selector ────────────────────────────────────────────────────

@dataclass(frozen=True)
class SelectorSpec:
    """CSS/XPath/텍스트 기반 요소 셀렉터."""
    css: str = ""
    xpath: str = ""
    text_contains: str = ""

    def to_dict(self) -> dict:
        return {"css": self.css, "xpath": self.xpath, "text_contains": self.text_contains}

    @staticmethod
    def from_dict(d: dict) -> SelectorSpec:
        return SelectorSpec(
            css=d.get("css", ""),
            xpath=d.get("xpath", ""),
            text_contains=d.get("text_contains", ""),
        )


# ── Action Step ─────────────────────────────────────────────────

VALID_ACTIONS = frozenset(
    {"navigate", "click", "type", "wait", "extract", "screenshot", "submit"}
)


@dataclass(frozen=True)
class ActionStep:
    """단일 자동화 스텝."""
    step_id: int
    action: str  # navigate|click|type|wait|extract|screenshot|submit
    selector: SelectorSpec = field(default_factory=SelectorSpec)
    value: str = ""          # URL 또는 입력값. {{변수}} 템플릿 지원
    wait_ms: int = 0
    optional: bool = False
    extract_key: str = ""    # extract 결과를 저장할 키

    def __post_init__(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"Invalid action: {self.action!r}. Must be one of {VALID_ACTIONS}")

    def to_dict(self) -> dict:
        d: dict = {"step_id": self.step_id, "action": self.action}
        if self.selector.css or self.selector.xpath or self.selector.text_contains:
            d["selector"] = self.selector.to_dict()
        if self.value:
            d["value"] = self.value
        if self.wait_ms:
            d["wait_ms"] = self.wait_ms
        if self.optional:
            d["optional"] = True
        if self.extract_key:
            d["extract_key"] = self.extract_key
        return d

    @staticmethod
    def from_dict(d: dict) -> ActionStep:
        sel = SelectorSpec.from_dict(d["selector"]) if "selector" in d else SelectorSpec()
        return ActionStep(
            step_id=d["step_id"],
            action=d["action"],
            selector=sel,
            value=d.get("value", ""),
            wait_ms=d.get("wait_ms", 0),
            optional=d.get("optional", False),
            extract_key=d.get("extract_key", ""),
        )


# ── Adapter Flow ────────────────────────────────────────────────

VALID_FLOW_TYPES = frozenset({"read", "write"})


@dataclass(frozen=True)
class AdapterFlow:
    """하나의 자동화 플로우 (읽기 또는 쓰기)."""
    name: str
    flow_type: str  # read|write
    steps: tuple[ActionStep, ...] = ()
    requires_auth: bool = False

    def __post_init__(self) -> None:
        if self.flow_type not in VALID_FLOW_TYPES:
            raise ValueError(f"Invalid flow_type: {self.flow_type!r}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "flow_type": self.flow_type,
            "requires_auth": self.requires_auth,
            "steps": [s.to_dict() for s in self.steps],
        }

    @staticmethod
    def from_dict(d: dict) -> AdapterFlow:
        steps = tuple(ActionStep.from_dict(s) for s in d.get("steps", []))
        return AdapterFlow(
            name=d["name"],
            flow_type=d["flow_type"],
            steps=steps,
            requires_auth=d.get("requires_auth", False),
        )


# ── Site Adapter ────────────────────────────────────────────────

VALID_TRUST_LEVELS = frozenset({"manual", "review", "auto"})


@dataclass(frozen=True)
class SiteAdapter:
    """사이트별 어댑터 설정."""
    domain: str
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    flows: tuple[AdapterFlow, ...] = ()
    rate_limit_seconds: float = 5.0
    daily_cap: int = 100
    trust_level: str = "manual"  # manual|review|auto

    def __post_init__(self) -> None:
        if self.trust_level not in VALID_TRUST_LEVELS:
            raise ValueError(f"Invalid trust_level: {self.trust_level!r}")

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "flows": [f.to_dict() for f in self.flows],
            "rate_limit_seconds": self.rate_limit_seconds,
            "daily_cap": self.daily_cap,
            "trust_level": self.trust_level,
        }

    @staticmethod
    def from_dict(d: dict) -> SiteAdapter:
        flows = tuple(AdapterFlow.from_dict(f) for f in d.get("flows", []))
        return SiteAdapter(
            domain=d["domain"],
            version=d.get("version", 1),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            flows=flows,
            rate_limit_seconds=d.get("rate_limit_seconds", 5.0),
            daily_cap=d.get("daily_cap", 100),
            trust_level=d.get("trust_level", "manual"),
        )

    def find_flow(self, name: str) -> AdapterFlow | None:
        for f in self.flows:
            if f.name == name:
                return f
        return None


# ── Execution Record ────────────────────────────────────────────

VALID_EXEC_STATUSES = frozenset(
    {"pending", "approved", "running", "success", "failed", "rejected"}
)


@dataclass(frozen=True)
class ExecutionRecord:
    """자동화 실행 기록."""
    id: int = 0
    domain: str = ""
    flow_name: str = ""
    flow_type: str = ""       # read|write
    status: str = "pending"
    started_at: str = ""
    finished_at: str = ""
    input_data: str = ""      # JSON string
    output_data: str = ""     # JSON string
    error: str = ""
    tier_used: int = 2

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "domain": self.domain,
            "flow_name": self.flow_name,
            "flow_type": self.flow_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error": self.error,
            "tier_used": self.tier_used,
        }


# ── Approval Request ────────────────────────────────────────────

VALID_APPROVAL_STATUSES = frozenset({"pending", "approved", "rejected", "expired"})


@dataclass(frozen=True)
class ApprovalRequest:
    """쓰기 작업 승인 요청."""
    id: int = 0
    domain: str = ""
    flow_name: str = ""
    action_summary: str = ""
    input_data: str = ""      # JSON string
    status: str = "pending"
    requested_at: str = ""
    decided_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "domain": self.domain,
            "flow_name": self.flow_name,
            "action_summary": self.action_summary,
            "input_data": self.input_data,
            "status": self.status,
            "requested_at": self.requested_at,
            "decided_at": self.decided_at,
        }


# ── Auto Response ───────────────────────────────────────────────

@dataclass(frozen=True)
class AutoResponse:
    """CLI 응답 포맷."""
    command: str
    domain: str
    timestamp: str
    success: bool
    data: dict = field(default_factory=dict)
    error: str = ""
    metadata: dict = field(default_factory=dict)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            {
                "command": self.command,
                "domain": self.domain,
                "timestamp": self.timestamp,
                "success": self.success,
                "data": self.data,
                "error": self.error,
                "metadata": self.metadata,
            },
            ensure_ascii=False,
            indent=indent,
        )


# ── Helpers ─────────────────────────────────────────────────────

def now_iso() -> str:
    """현재 시각 ISO 8601 문자열."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
