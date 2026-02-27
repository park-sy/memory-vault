# Design Principles — 상엽의 설계 방향

plan 생성 시 이 원칙을 반드시 따른다. reject 피드백이 누적되며 점점 정교해진다.

## 핵심 원칙

### 1. 사용자 입력 우선
- 있는 정보로 먼저 결과물 만든다
- 아무것도 없으면 인터뷰로 최소 정보 파악
- 시스템이 처음부터 다 만들어주는 구조 X

### 2. 점진적 보강
- 전체 파이프라인 순차 실행 X
- 부족한 부분만 필요한 tool을 선택적으로 호출
- 사용자가 보강할 구간을 지정

### 3. 초안 먼저
- 완벽하지 않아도 빠르게 보여준다
- 보여준 후 반복 수정/보강

## Reject 히스토리

| 날짜 | feature | reject 사유 | 반영된 원칙 |
|------|---------|------------|------------|
| 2026-02-24 | 여행계획 세우기 | 처음부터 전체 파이프라인 순차 실행하는 구조 | 사용자 입력 우선 + 점진적 보강 |

## Architecture Patterns

| Category | Pattern | Rationale | Source | Confidence |
|----------|---------|-----------|--------|------------|

## LLM Boundary Decisions

| Tool Pattern | Classification | Rationale | Source |
|-------------|---------------|-----------|--------|

## Implementation Patterns

| Pattern | When to Use | Source | Confidence |
|---------|------------|--------|------------|
