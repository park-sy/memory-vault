---
type: clone-data
subtype: profile
status: inactive
last_synthesized: 2026-02-28
total_decisions: 16
overall_accuracy: 0.00
tags: [decision-clone, profile]
---

# Decision Profile — 상엽

## Architecture (7 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| NiceGUI 유지 | 1/7 | 0.14 | D-001 |
| sub-agent 방식 | 1/7 | 0.14 | D-002 |
| LLM은 판단만, 실행은 코드 | 1/7 | 0.14 | D-003 |
| 모델/권한이 다를 때만 분리 | 1/7 | 0.14 | D-004 |
| 제거 (sub-agent로 대체) | 1/7 | 0.14 | D-008 |
| 3-Tier (planner 1개 + worker N개) | 1/7 | 0.14 | D-012 |
| Platform Team 구조 채택 | 1/7 | 0.14 | D-013 |

## Communication (2 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| 자유 소통 (Collaboration Mode) | 1/2 | 0.50 | D-014 |
| Platform Team (Team Topologies) | 1/2 | 0.50 | D-015 |

## Risk Tolerance (1 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| 반드시 상엽 확인 후 push | 1/1 | 1.00 | D-006 |

## Tooling (2 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| CLI 사용 원칙 | 1/2 | 0.50 | D-007 |
| Opus | 1/2 | 0.50 | D-009 |

## Trade Offs (2 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| 사용자 입력 우선 + 점진적 보강 | 1/2 | 0.50 | D-011 |
| AI 고유 이점으로 전부 해소 | 1/2 | 0.50 | D-016 |

## Workflow (2 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| Skill-first (skill로 검증 → 반복 패턴만 code로) | 1/2 | 0.50 | D-005 |
| Plan Mode 도입 | 1/2 | 0.50 | D-010 |
