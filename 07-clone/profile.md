---
type: clone-data
subtype: profile
status: inactive
last_synthesized: 2026-03-07
total_decisions: 21
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

## Tooling (3 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| CLI 사용 원칙 | 1/3 | 0.33 | D-007 |
| Opus | 1/3 | 0.33 | D-009 |
| supervision=OFF, MsgBus direct approvals, manual re-send for timing bug | 1/3 | 0.33 | D-017 |

## Trade Offs (2 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| 사용자 입력 우선 + 점진적 보강 | 1/2 | 0.50 | D-011 |
| AI 고유 이점으로 전부 해소 | 1/2 | 0.50 | D-016 |

## Uncategorized (4 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| DB로 이관 + frontmatter에서 제거 | 1/4 | 0.25 | D-019 |
| review 단계 추가 (Recommended) | 1/4 | 0.25 | D-021 |
| JSONL 스캔만 (Recommended) | 1/4 | 0.25 | D-022 |
| /feature-session으로 트리거 대고 아무것도 안적으면 1,2 둘다 해당 명령어 이후에 내가 내용 적으면 그거 위주로. | 1/4 | 0.25 | D-028 |

## Workflow (2 decisions, accuracy: N/A)

| 성향 | 빈도 | 신뢰도 | 근거 |
|------|------|--------|------|
| Skill-first (skill로 검증 → 반복 패턴만 code로) | 1/2 | 0.50 | D-005 |
| Plan Mode 도입 | 1/2 | 0.50 | D-010 |
