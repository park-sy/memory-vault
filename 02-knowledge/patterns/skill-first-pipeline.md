---
type: knowledge
importance: 8
created: "2026-02-23"
tags: [skill-first, pipeline, feature, pattern, distilled]
verified_count: 3
source: "distill from 05-sessions/2026-02-23"

---

# Skill-First 파이프라인

## 패턴

새 기능을 만들 때 **skill(프롬프트)로 먼저 검증**하고, 반복 패턴이 확인되면 **code로 전환**한다.

```
skill = 프로토타입 / 설계서 (LLM 해석)
code = 최적화된 실행 (토큰 0)
```

## 깔때기 구조

```
  designing  ← 많이 (탐색, 실험)
  testing    ← 중간 (검증)
  coding     ← 적게 (확정된 것만 코드화)
```

기능이 성숙할수록:
- code 비중 ↑ → 토큰 소모 ↓
- skill은 edge case/새 시나리오에만 사용

## 파이프라인 스테이지

```
idea → interview → spec → [승인] → queued → designing → testing ⇄ designing → [승인] → stable → coding → done
```

| 구간 | 주체 | 핵심 활동 |
|------|------|----------|
| idea → spec | Planner (코어팀) | 인터뷰, 요구사항 정리 |
| designing | Coder + Skill | SKILL.md 작성, 프롬프트 설계 |
| testing | QA (코어팀) | skill 실행 결과 검증 |
| stable → coding | Coder (도메인팀) | 검증된 패턴을 Python 코드로 전환 |
| done | - | code + 잔여 skill 공존 |

## 적용 판단 기준

| 상황 | 접근 |
|------|------|
| 새 기능, 요구사항 불확실 | Skill-First (프롬프트로 탐색) |
| 규칙 기반, 결정적 동작 | 바로 Code (Level 0) |
| 3회+ 반복된 skill 패턴 | Code로 전환 (Level 0/1) |
| 맥락 의존적 판단 | Skill 유지 (Level 2) |

## 검증

- 2026-02-23: Feature Pipeline v2 설계에서 확립 — `designing → testing ⇄ designing` 루프
- 2026-02-23: Auto-Dev Pipeline에서 적용 — skill 기반 스케줄러 → 코드 기반 체크포인트
- 2026-02-28: whos-life 여러 feature에서 skill/code 공존 확인

## Related

- [[06-skills/feature-pipeline]] — 전체 파이프라인 규격
- [[02-knowledge/patterns/three-tier-execution]] — 3단계 실행 모델 (Level 0/1/2)
