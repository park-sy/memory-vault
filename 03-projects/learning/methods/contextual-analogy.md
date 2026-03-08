---
type: learning-method
tier: 3
category: comprehension
evidence_level: emerging
sangup_fit: pending
experiment_count: 0
created: "2026-03-06"
tags: [learning, method, comprehension, contextual-analogy, ai-native, core-hypothesis]

---

# 개인 경험 기반 비유 (Contextual Analogy) ★

## 개요

학습자의 **개인 경험**을 기반으로 AI가 맞춤 비유를 생성하여 새 개념을 설명하는 방법.
상엽이 제안한 고유 방법. memory-vault 인프라에 의존하는 AI-native 학습법.

## 원리

```
경험 축적 (memory-vault)
  → AI가 축적된 경험 기반 비유 생성
    → 이해도 상승
      → 새 경험 축적
        → 비유 정확도 상승
          → ... (선순환)
```

- **개인화된 스키마 연결**: 일반 비유보다 자기 경험 비유가 스키마 활성화를 강하게 유발
- **정서적 연결**: 자기 경험은 감정과 연결 → 감정이 기억을 강화 (정서적 부호화)
- **AI 고유 이점**: 사람 튜터는 학습자의 전 경험을 알 수 없지만, AI는 memory-vault에 축적된 경험을 전부 참조 가능
- **선순환 구조**: 경험 축적 → 비유 풍부화 → 학습 가속 → 경험 추가 축적

## 절차

1. 학습할 새 개념 선택
2. AI가 memory-vault에서 관련 경험 탐색
   - 세션 로그, 프로젝트 히스토리, 의사결정 기록 등
3. 새 개념과 상엽의 경험 사이 구조적 유사성(structural mapping) 식별
4. 비유 생성: "이건 네가 {경험}할 때 {구체적 상황}과 같아"
5. 비유의 한계(disanalogy) 명시: "다만 {차이점}은 다르다"
6. 이해도 확인 → 비유 정제 또는 다른 경험으로 재시도

## 변형

- **다중 비유**: 같은 개념에 여러 경험 기반 비유 → 다각적 이해
- **역방향**: 상엽이 비유를 시도 → AI가 정확성 검증 + 보완
- **[[feynman-technique]] 결합**: 파인만 기법으로 설명하되, 비유는 contextual analogy로

## When to Use

- 새롭고 추상적인 개념을 처음 접할 때
- 기존 지식 체계와 연결이 안 되는 고립된 개념
- memory-vault에 관련 도메인 경험이 있을 때 (비유 재료 필요)

## When NOT to Use

- 경험이 없는 완전히 새로운 분야 (비유 재료 부족)
- 단순 사실 암기 (비유가 오히려 혼란)
- 경험과의 유사성이 표면적일 때 (잘못된 비유 위험)

## memory-vault 의존성

이 방법은 다른 시드 방법과 달리 **memory-vault 인프라가 필수**:

| 의존 요소 | 용도 |
|-----------|------|
| `05-sessions/` | 세션 경험 탐색 |
| `03-projects/` | 프로젝트 경험 탐색 |
| `07-clone/decision-log.md` | 의사결정 경험 탐색 |
| `01-org/user.md` | 상엽 프로필 |
| `03-projects/learning/context.md` | 학습 프로필 |

## 상엽 적응 노트

(실험 후 기록 — 핵심 가설 방법이므로 초기 실험 우선순위 높음)

## 실험 히스토리

| 실험 ID | 날짜 | effectiveness | confidence | 비고 |
|---------|------|---------------|------------|------|
| — | — | — | — | 아직 실험 없음 |

## 출처

- Gentner, D. (1983). "Structure-mapping: A theoretical framework for analogy"
- Richland et al. (2007). "Cognitive supports for analogies in the mathematics classroom"
- 상엽 제안 (2026-03-06) — memory-vault 기반 선순환 가설
