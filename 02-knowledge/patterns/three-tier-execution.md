---
type: knowledge
importance: 8
created: "2026-02-22"
last_accessed: "2026-03-01"
access_count: 2
tags: [execution-model, llm, token-efficiency, pattern, distilled]
verified_count: 3
source: "distill from 05-sessions/2026-02-22"
---

# 3단계 실행 모델 (Three-Tier Execution)

## 패턴

모든 feature의 실행 로직을 토큰 소모량 기준으로 3단계로 분류한다.

```
Level 0: 코드 (0 토큰)
Level 1: 정형 LLM (프롬프트 .md + Flash)
Level 2: 비정형 LLM (에이전트 개입, Opus)
```

## 적용 규칙

| Level | 실행 주체 | 토큰 | 사용 조건 |
|-------|----------|------|----------|
| 0 | Python 코드 (함수, SQL, 정규식) | 0 | 규칙 기반, 결정적 동작 |
| 1 | 정형 프롬프트 + 경량 모델 (Flash/Haiku) | 소 | 템플릿 기반 분석, 분류, 요약 |
| 2 | 에이전트 대화 (Opus/Sonnet) | 대 | 맥락 의존적 판단, 설계, 리뷰 |

## 설계 원칙

- **코드로 할 수 있으면 코드로** — LLM은 판단만, 실행은 코드
- **Level 0 → 1 → 2 순서로 검토** — 토큰 비용이 낮은 쪽 우선
- **모든 feature spec에 LLM Boundary 테이블 필수** — 어떤 메서드가 어떤 Level인지 명시

## 예시: LLM Boundary 테이블

```markdown
| Method | Level | Model | 근거 |
|--------|-------|-------|------|
| get_events() | 0 | - | DB 쿼리, 코드로 충분 |
| classify_priority() | 1 | Flash | 템플릿 분류, 정형 |
| design_architecture() | 2 | Opus | 맥락 의존 판단 |
```

## 검증

- 2026-02-22: whos-life feature-pipeline 설계에서 확립
- 2026-02-23: Auto-Dev Pipeline에서 적용 (스케줄러 토큰 임계값 기반 실행)
- 2026-02-28: token-monitor feature에서 `run()` vs `run_ephemeral()` 분리로 재확인

## Related

- [[06-skills/feature-pipeline]] — 파이프라인에서 Level별 세션 관리
- [[02-knowledge/infrastructure/token-monitoring]] — 토큰 추적 인프라
