---
type: decision
id: "005"
status: proposed
date: "2026-03-06"
participants: ["상엽", "얍"]
importance: 8
tags: [architecture, database, feature-factory, pipeline, infrastructure]

---

# ADR-005: 파이프라인 DB 단일화 — productivity.db → feature-factory.db 통합

## Context

Feature Pipeline의 데이터가 2개 DB에 분산되어 있다:

| DB | 위치 | 저장 데이터 |
|----|------|------------|
| `productivity.db` | `whos-life/db/` | work_queue(태스크), feature_dev_log, feature_timeline, token_snapshots |
| `feature-factory.db` | `memory-vault/storage/` | factory_config(설정), worker_assignments, pending_approvals, factory_events, stage_token_log |

### 발생 경위

의도된 설계가 아니라 성장 과정의 부산물:

1. 태스크 관리가 whos-life의 `dev-queue` 기능으로 시작 → `productivity.db`에 work_queue 생성
2. Feature Factory 데몬을 memory-vault에 만들면서 운영 상태를 별도 DB로 분리
3. Feature Factory의 `pipeline_manager.py`는 whos-life CLI를 subprocess로 호출하여 태스크 조작

### 문제

1. **책임 혼재**: work_queue는 파이프라인 인프라 데이터인데 whos-life 도메인 DB에 있음. whos-life가 아닌 피처(예: 퍼블리싱 파이프라인)도 이 DB에 들어감
2. **접근 경로 불일치**: feature_cli.py는 productivity.db 직접 접근, Feature Factory는 whos-life CLI subprocess 호출. 같은 데이터를 다른 방식으로 접근
3. **설정/태스크 분리**: supervision(설정)은 feature-factory.db, work_queue(태스크)는 productivity.db. 통합 조회 불가
4. **새 세션 혼란**: 어떤 DB를 봐야 하는지 문서가 없어서, 잘못된 DB를 조회하고 "설정이 없다"고 오판하는 사고 발생 (2026-03-06 세션)

## Decision

**feature-factory.db로 통합한다.**

- work_queue 및 파이프라인 관련 테이블을 `memory-vault/storage/feature-factory.db`로 이전
- feature_cli.py가 feature-factory.db를 직접 사용하도록 변경
- whos-life CLI subprocess 의존 제거 (pipeline_manager.py → 직접 DB 접근 또는 내부 모듈 호출)
- whos-life의 productivity.db에는 whos-life 도메인 데이터만 남김

### 근거

- 파이프라인은 whos-life에 종속되지 않는 범용 인프라
- 단일 DB → 단일 접근 경로 → 새 세션이 헷갈릴 여지 제거
- 설정과 태스크가 같은 DB에 있으면 트랜잭션 일관성 확보

## Consequences

### 긍정적
- DB 경로 혼란 제거
- feature_cli.py와 Feature Factory가 동일 DB 사용
- whos-life 독립성 강화 (파이프라인 인프라 분리)

### 부정적/리스크
- 마이그레이션 작업 필요 (work_queue 데이터 이전, 스키마 통합)
- whos-life CLI의 dev-queue 명령 수정 또는 제거 필요
- 기존 feature-pipeline.md 문서 업데이트 필요

## Migration Plan

1. feature-factory.db에 work_queue 스키마 생성 + 기존 데이터 마이그레이션
2. feature_cli.py → feature-factory.db 직접 접근으로 전환
3. feature_cli.py에 누락 명령 흡수 (`add`, `advance-stage` 등 whos-life dev-queue에만 있던 것)
4. Feature Factory pipeline_manager.py → subprocess 래퍼 제거, 직접 DB 접근 또는 내부 모듈 호출
5. whos-life CLI `dev-queue` 명령 fade-out (feature_cli.py가 단일 진입점)
6. 문서 업데이트 (feature-pipeline.md, CLAUDE.md, `/feature` 스킬 정의)

## Related

- [[04-decisions/004-cli-over-mcp-for-features]] — CLI 인터페이스 결정 (이 ADR로 일부 재검토)
- [[06-skills/feature-pipeline]] — 파이프라인 문서 (업데이트 필요)
- [[02-knowledge/infrastructure/feature-factory-architecture]] — 현재 구조 문서 (신설)
