---
type: skill
importance: 8
status: planned
audience: [orchestrator, core-team, domain-team]
created: "2026-02-28"
tags: [core-team, automation, hook, script, infrastructure]
related: ["[[002-platform-team-structure]]"]

---

# 코어팀 구조 자동화 — Hook / Script / Skill 목록

## 개요

[[002-platform-team-structure|ADR-002]] 코어팀 구조의 단점을 해소하기 위한 자동화 도구 목록.
원칙: LLM 불필요 → 코드, 팀 간 공유 → 옵시디언, 나머지 → AI 고유 이점.

## 구현 목록

### Hook

| ID | 이름 | 트리거 | 동작 | 해소하는 단점 |
|----|------|--------|------|--------------|
| H-1 | context-auto-sync | 프로젝트 파일 변경 시 (PostToolUse) | 프로젝트 구조 스캔 → domain context.md 자동 갱신 | context.md 관리 부담 | ✅ `scripts/context-auto-sync.sh` |
| H-2 | task-router | 작업 수신 시 | 작업 크기/복잡도 판단 → trivial이면 코드 직접 처리, 아니면 코어팀 호출 | 사소한 작업 오버킬 |
| H-3 | handoff-trigger | 완료 키워드 감지 시 | 현재 팀 산출물 + 도메인 컨텍스트를 다음 코어팀에 자동 전달 | 멀티팀 핸드오프 유실 |

### Script

| ID | 이름 | 실행 방식 | 동작 | 해소하는 단점 |
|----|------|----------|------|--------------|
| S-1 | conflict-detector | 주기적 또는 수동 | 코어팀 memory 파일들에서 동일 [[wiki-link]] 참조에 대한 상반된 평가 탐지 → 리포트 | 코어팀 간 패턴 충돌 |
| S-2 | memory-archiver | 주기적 또는 수동 | importance/access_count/last_accessed 기준으로 cold memory 식별 → 아카이브 제안 | memory 비대화 | ✅ `scripts/memory-archiver.py` |
| S-3 | core-seed | 코어팀 초기 생성 시 | 02-knowledge/ 의 기존 패턴을 코어팀 memory에 시드 | 콜드 스타트 |

### Skill (LLM 필요)

| ID | 이름 | 호출 주체 | 동작 | 해소하는 단점 |
|----|------|----------|------|--------------|
| K-1 | responsibility-assign | orchestrator | 피처 시작 시 건별 최종 책임자(코어팀 or 도메인팀) 지정 | 책임 소재 분산 |
| K-2 | cross-review | 코어팀 | 다른 코어팀의 memory 요약 읽고 자기 memory와 교차 검증 | 코어팀 간 패턴 충돌 |
| K-3 | domain-context-brief | 도메인팀 | 코어팀 호출 전 도메인 컨텍스트를 최소 토큰으로 요약 생성 | 도메인 컨텍스트 반복 로딩 | ✅ `scripts/domain-context-brief.py` |

## 구현 우선순위

```
Phase 1 (구조 재편 직후):
  S-3 core-seed             ← 코어팀 생성과 동시에 필요
  K-3 domain-context-brief  ← 코어팀이 도메인 작업하려면 필요

Phase 2 (운영 시작):
  H-2 task-router           ← 작업 라우팅 자동화
  H-3 handoff-trigger       ← 팀 간 핸드오프 자동화
  K-1 responsibility-assign

Phase 3 (안정화):
  H-1 context-auto-sync
  S-1 conflict-detector
  S-2 memory-archiver
  K-2 cross-review
```

## When to Use

- 코어팀 구조 구현 시 이 목록을 참조
- 각 Phase 진입 시 해당 도구부터 구현
- 새로운 단점 발견 시 이 문서에 추가
