---
type: domain-context
project: whos-life
importance: 8
created: 2026-02-28
tags: [whos-life, context, domain]

---

# whos-life — 도메인 컨텍스트

코어팀에 전달할 최소 컨텍스트. 이 파일을 읽으면 프로젝트 작업이 가능하다.

## 프로젝트 요약

개인 생산성 플랫폼 + AI 에이전트 시스템.

## 스택

- **UI**: NiceGUI (Python)
- **DB**: SQLite WAL (`db/productivity.db`)
- **통신**: 통합 CLI (`whos-life feature {name} {method}`) — service.py 인트로스펙션으로 argparse 자동 생성
- **A2A 통신**: memory-vault MsgBus (SQLite + Telegram)
- **네트워크**: Tailscale (로컬 우선)

## 아키텍처

- Feature = `service.py`(순수 함수 → CLI 자동 노출) + `render.py`(NiceGUI)
- 통합 CLI: `whos-life feature {name} {method} [args]` — 개별 cli.py 불필요
- 3단계 실행 모델: Level 0(코드), Level 1(정형 LLM), Level 2(비정형 LLM)
- 디렉토리: `features/{category}/{name}/`

### LLM 호출 2-tier 구조

| 계층 | 세션 타입 | 용도 | 추적 |
|------|----------|------|------|
| Core | `lifecycle="core"` | 장기 보존 대화, 메인 에이전트 | AISession 테이블 |
| Ephemeral | `lifecycle="ephemeral"` | 1회성 LLM 호출 (분석, 요약 등) | `llm_call_log` 테이블 |

- `ClaudeRunner.run_ephemeral()`: `--output-format json --no-session-persistence`로 usage/cost 실측
- `LLMTracker`: run_ephemeral() 래퍼, 자동 DB 기록 + 통계 조회
- `SessionManager.cleanup_ephemeral()`: 만료된 ephemeral 세션 정리

## Key Paths

- 프로젝트 루트: `/Users/hiyeop/dev/whos-life/`
- DB: `db/productivity.db`
- Features: `features/{category}/{name}/`

## 기존 기능 목록

케이스 판별용. 여기 있는 기능은 케이스 1(실행) 또는 1.5(확장) 대상.

| 기능 | 디렉토리 | 상태 | 비고 |
|------|----------|------|------|
| 에이전트 매니저 | `ai-ops/agent-manager` | active | v0.2.0 |
| 개발 큐 | `ai-ops/dev-queue` | active | v0.1.0 |
| 모델 매니저 | `ai-ops/model-manager` | active | v0.1.0 |
| 토큰 대시보드 | `ai-ops/token-dashboard` | active | v0.1.0 |
| 토큰 모니터 | `ai-ops/token-monitor` | active | v0.1.0 |
| 포트폴리오 트래커 | `invest/portfolio-tracker` | active | v1.0.0 |
| Hello World | `builtin/hello-world` | active | v1.0.0 |

> 새 feature가 done 상태가 되면 여기에 추가한다.

## 주요 컨벤션

- 새 기능 = Feature Pipeline 워크플로우 (`06-skills/feature-pipeline.md`)
- spec → designing → coding → testing 순서
- 작업 라우팅 = [[workflow-routing]] (케이스 1 / 1.5 / 2 판별)

## Related

- [[03-projects/whos-life/ideas-backlog]]
- [[06-skills/feature-pipeline]]
- [[06-skills/workflow-routing]]
