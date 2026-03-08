---
type: decision
id: "004"
status: accepted
date: "2026-02-28"
participants: ["상엽", "얍"]
importance: 8
tags: [architecture, cli, mcp, feature, token-efficiency]

---

# ADR-004: Feature Tool 인터페이스를 MCP에서 CLI로 전환

## Context

### 문제

whos-life의 feature tool은 MCP `@tool` 데코레이터로 노출되어 있었다.
MCP는 tool 스키마(함수명, 파라미터, 설명)를 **매 턴 시스템 프롬프트에 주입**한다.

- tool 10개 기준 ~2,000 토큰/턴 낭비
- 100턴 세션이면 ~200,000 토큰이 스키마 반복에 소모
- tool이 늘어날수록 비용이 선형 증가

### 추가 동기

- **체이닝**: MCP는 tool 간 연결에 LLM 턴이 필요. CLI는 `|`, `&&`로 턴 없이 연결
- **범용성**: CLI면 어떤 LLM이든 Bash 실행만으로 사용 가능 (Guest Agent 시나리오)

## Decision

**Feature tool은 CLI, A2A 통신도 Hook (Stop) 기반.** *(amended 2026-03-01: MCP → Hook)*

### 아키텍처 변경

```
Before:
에이전트 → MCP protocol → service.py (@tool) → DB
사용자   → UI           → render.py           → service.py

After:
에이전트 → Bash → whos-life feature {name} {method} → service.py → DB
사용자   → UI   → render.py                         → service.py → DB
```

- `service.py`: 핵심 로직 (순수 함수, 인터페이스 무관) → **통합 CLI가 자동으로 CLI 노출**
- `cli.py` (루트): 통합 CLI 진입점 — service.py 런타임 인트로스펙션으로 argparse 자동 생성
- `render.py`: UI (기존과 동일)

### 범위

| 대상 | 인터페이스 | 이유 |
|------|-----------|------|
| Feature tool | CLI | 토큰 효율, 체이닝, 범용성 |
| A2A 통신 (ADR-003 채널 6) | ~~MCP 유지~~ → **Hook (Stop)** | 세션 간 메시지 전달 (amended 2026-03-01) |

## Rationale

| 기준 | MCP | CLI | 판정 |
|------|-----|-----|------|
| 토큰 효율 | 스키마 매 턴 주입 (~200 tok/tool) | 0 (Bash 호출만) | CLI 우위 |
| 체이닝 | tool 간 LLM 턴 필요 | 파이프/&& 가능 | CLI 우위 |
| 외부 LLM 범용성 | MCP 클라이언트 필요 | Bash만 있으면 됨 | CLI 우위 |
| 발견 가능성 | 자동 노출 | --help 필요 | MCP 우위 (보완 가능) |
| 타입 안전성 | Pydantic 자동 검증 | Typer 타입 힌트 | 동등 |
| 구조화된 출력 | JSON dict 기본 | --json 플래그 필요 | MCP 우위 (보완 가능) |

## Consequences

### 긍정적

- **토큰 절약**: tool 스키마 주입 제거 → 턴당 ~2,000 토큰 절감
- **체이닝**: `cli.py get-trips --json | cli.py filter --status active` — LLM 턴 0
- **Guest Agent 범용성**: GPT, Gemini 등 어떤 LLM이든 Bash 실행으로 연동
- **테스트 용이**: CLI는 셸에서 직접 테스트 가능

### 부정적 + 보완

| # | 잃는 것 | 보완 방법 |
|---|---------|----------|
| 1 | **발견 가능성** — tool 목록 자동 노출 | `context.md`에 CLI 명령어 목록 포함 + `cli.py --help` |
| 2 | **타입 안전성** — Pydantic 스키마 자동 검증 | Typer 타입 힌트 자동 검증 + service.py 내부 Pydantic 유지 |
| 3 | **구조화된 출력** — 항상 JSON 반환 | `--json` 플래그 표준화. 에이전트는 항상 `--json` 사용 |
| 4 | **에러 처리** — 구조화된 에러 객체 | exit code 1 + stderr JSON `{"error": "msg", "code": "CODE"}` |
| 5 | **초기화 오버헤드** — 서버 상시 구동 | SQLite WAL → 연결 비용 ~1ms. 문제 없음 |
| 6 | **복잡한 파라미터** — nested JSON 전달 | `--input '{"key":"val"}'` 또는 stdin 파이프 |

### CLI 표준 규칙

```bash
# 통합 CLI 실행 (alias whos-life="python3 /Users/hiyeop/dev/whos-life/cli.py")

# 기본: 사람 읽기용
whos-life feature travel get-events --from 2026-02-23 --to 2026-02-28

# 에이전트용: --json
whos-life feature travel get-events --from 2026-02-23 --to 2026-02-28 --json

# 에러: exit code 1 + JSON stderr
whos-life feature travel get-events --from invalid
# stderr: {"error": "Invalid date format", "code": "INVALID_INPUT"}

# feature 목록
whos-life feature --help

# method 목록
whos-life feature dev-queue --help

# 인자 도움말
whos-life feature dev-queue register-idea --help

# 체이닝
whos-life feature travel get-trips --json | jq '.items[]'
```

## Amendment (2026-03-01): A2A 통신도 Hook으로 전환

### 변경

| Before | After |
|--------|-------|
| Feature tool → CLI, A2A → MCP 유지 | Feature tool → CLI, **A2A → Hook (Stop)** |

### 근거

MCP의 이론적 장점 "워커가 원할 때 확인"이 실제로는 발생하지 않는다:

1. **LLM은 자발적으로 행동하지 않는다** — 프롬프트에 반응할 뿐. busy 워커가 스스로 `read_mail` 호출할 일이 없다.
2. **실제 확인 시점 = idle** — MCP든 Hook이든 메시지를 확인하는 시점은 작업 완료 후. Stop hook이 이 타이밍을 정확히 포착.
3. **토큰 낭비** — MCP tool schema ~200 토큰/턴이 한 번도 호출되지 않을 도구 광고에 소모. 이 ADR이 feature tool에서 제거한 그 똑같은 문제.

### 새 아키텍처

```
오케스트레이터: pool.sh send → msgbus.db 기록 + tmux 직접 전달 + ack
Telegram:       bridge.py → msgbus.db 기록 (pending)
Stop hook:      inbox-deliver.py → msgbus.db 확인 → pending 있으면 tmux 전달
```

### 영향

- `mcp-mailbox.py` MCP 서버 불필요 → 미등록 유지
- `mailbox.py` 폐기 → `msgbus.py` 단일 DB로 통합
- `mailbox-notify.sh` → `inbox-deliver.py`로 교체

## Related

- [[003-independent-a2a-communication]] — A2A 통신 (MCP 부분은 이 Amendment로 대체)
- [[06-skills/feature-pipeline]] — CLI 표준 패턴 반영
- [[06-skills/workflow-routing]] — 외부 LLM 요청 CLI 전환
- [[03-projects/whos-life/ideas-backlog]] — Guest Agent CLI 전환
