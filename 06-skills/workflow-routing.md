---
type: skill
importance: 9
created: 2026-02-28
last_accessed: 2026-02-28
access_count: 1
tags: [workflow, routing, orchestration, platform-team]
---

# Workflow Routing — 작업 흐름 라우팅

오케스트레이터가 사용자 요청을 받았을 때, 어떤 흐름으로 처리할지 판별하고 실행하는 전체 규칙.

## Context Injection 모델 (도메인팀 종속)

도메인팀(developer) 세션은 **3개 파일이 주입되어야** 작업 가능하다:

| 순서 | 파일 | 역할 |
|------|------|------|
| 1 | `{project}/context.md` | 도메인 컨텍스트 (스택, 아키텍처, 기존 기능 목록) |
| 2 | `01-org/core/{role}/role.md` | 코어팀 역할 (필요시 호출) |
| 3 | `06-skills/feature-pipeline.md` | 케이스 2 진입 시 파이프라인 규칙 |

developer 역할 파일(`{project}/developer.md`)이 이 3개를 "읽어야 할 파일"로 참조한다.
오케스트레이터는 developer에게 작업을 위임할 때 이 구조가 로드되는지만 확인하면 된다.

## 케이스 판별 기준

오케스트레이터가 사용자 요청을 받으면 아래 순서로 판별한다:

```
사용자 요청 수신
  │
  ├─ 기존 기능/코드에 대한 작업인가?
  │    ├─ Yes → context.md의 "기존 기능 목록" 확인
  │    │    ├─ 해당 기능 존재 → 케이스 1 (실행)
  │    │    └─ 해당 기능 없음 → 케이스 2 (구축)
  │    │
  │    └─ 부분적 (기존 기능 + 변경/확장) → 케이스 1.5 (확장)
  │
  └─ 새 기능 요청인가?
       └─ Yes → 케이스 2 (구축)
```

### 판별 핵심 질문

| 질문 | Yes | No |
|------|-----|-----|
| 기존 코드를 **그대로** 사용하면 되는가? | 케이스 1 | 다음 질문 |
| 기존 코드를 **수정/확장**하면 되는가? | 케이스 1.5 | 케이스 2 |
| 완전히 새로운 기능인가? | 케이스 2 | — |

## 케이스 1: 실행

> "이미 있는 걸 쓴다"

기존 코드/SKILL이 있고, 수정 없이 실행만 하면 되는 작업.

### 흐름

```
오케스트레이터
  → developer 워커에 작업 위임
  → developer가 기존 코드/tool 실행
  → 결과 보고
```

### 예시
- "일정 조회해줘" → 기존 calendar tool 호출
- "데이터 백업해줘" → 기존 backup 스크립트 실행
- 버그 수정 (기존 로직 내 오류)

### 오케스트레이터 행동
- 워커 1개 할당 (developer 역할)
- `pool.sh send {N} "작업 메시지"`
- 결과 확인 후 보고

## 케이스 1.5: 확장

> "있는 걸 고친다"

기존 기능이 있지만 수정/확장이 필요한 작업.
**developer가 변경 범위를 판단**하여 3가지 분기로 나뉜다.

### 판단 기준 (developer가 수행)

```
변경 요청 분석
  │
  ├─ 기존 함수/파일 내 수정으로 끝나는가?
  │    └─ Yes → 분기 A (인라인 수정)
  │
  ├─ 새 함수/파일 추가가 필요하지만 기존 구조 내인가?
  │    └─ Yes → 분기 B (구조 내 확장)
  │
  └─ DB 스키마 변경, 새 feature 디렉토리, 대규모 리팩토링?
       └─ Yes → 분기 C (케이스 2 에스컬레이션)
```

### 분기 A: 인라인 수정

기존 파일 내 코드 수정. 새 파일 없음.

- developer가 직접 수행
- 코어팀 호출 불필요 (단, 리뷰 필요시 reviewer 호출 가능)
- 예시: 기존 tool의 파라미터 추가, 에러 메시지 개선, UI 레이아웃 조정

### 분기 B: 구조 내 확장

기존 feature 디렉토리 안에서 함수/파일 추가.

- developer가 직접 수행
- 필요시 코어팀(planner, reviewer) 협업
- 예시: 기존 feature에 새 tool 추가, 테이블에 컬럼 추가, 새 UI 탭 추가

### 분기 C: 케이스 2 에스컬레이션

변경 범위가 커서 Feature Pipeline이 필요.

- developer → 오케스트레이터에 보고: "이건 케이스 2로 가야 합니다"
- 오케스트레이터 → 케이스 2 흐름 진입
- 예시: 새 DB 테이블 필요, 새 feature 디렉토리 필요, 3개 이상 파일 대규모 수정

### 오케스트레이터 행동
- developer 워커에 작업 위임
- developer의 분기 판단 결과를 수신
- 분기 A/B: 결과 보고 대기
- 분기 C: 케이스 2 전환

## 케이스 2: 구축

> "새로 만든다"

완전히 새로운 기능이거나, 케이스 1.5에서 에스컬레이션된 작업.
[[feature-pipeline|Feature Pipeline]] 4단계를 따른다.

### 흐름

```
오케스트레이터
  → spec (planner): 상엽과 대화하며 spec 작성 → spec 승인
  → designing (worker): SKILL.md + config.json 작성 → 설계 승인
  → testing (worker): Tool-Level Verification → stable 승인
  → coding (worker): service.py + render.py 구현 → done
```

### 오케스트레이터 행동
- `06-skills/feature-pipeline.md` 참조하여 파이프라인 관리
- 각 단계별 워커 할당 및 승인 게이트 관리
- 단계 전환 시 알림 발송

### 상세
Feature Pipeline의 전체 규칙은 [[feature-pipeline]] 참조.

## 기억 저장 규칙

작업 중 발생한 교훈은 **성격에 따라 다른 위치**에 저장한다.

### 저장 위치 판별

```
교훈/패턴 발생
  │
  ├─ 프로젝트 종속인가? (특정 프로젝트에서만 유효)
  │    └─ Yes → 도메인 기억
  │         → 03-projects/{name}/developer-memory.md
  │
  └─ 프로젝트 무관한가? (다른 프로젝트에서도 적용 가능)
       └─ Yes → 범용 기억
            → 해당 코어팀의 memory.md
            → 01-org/core/{role}/memory.md
```

### 승격 규칙

| 조건 | 행동 |
|------|------|
| 3회 이상 반복 확인된 패턴 | `02-knowledge/patterns/`로 승격 |
| 아키텍처 수준 결정 | `04-decisions/`에 ADR 작성 |
| 반복되는 실수 | `02-knowledge/mistakes/`에 기록 |

### 저장 타이밍
- 작업 **중**: 즉시 해당 memory.md에 기록
- 세션 **종료 시**: `05-sessions/YYYY-MM-DD.md`에 세션 요약 + 증류 대상 확인

## 외부 LLM 요청 수신 (향후 확장)

케이스 1, 1.5는 외부 LLM(GPT, Gemini 등)이 **클라이언트**로서 우리 시스템에 요청을 보낼 수 있다.
코드 변경 권한은 내부 developer에게만 있고, 외부 LLM은 요청만 한다.

### 원칙

- 외부 LLM은 **파일 접근 없음** — CLI 실행만 가능
- 판단(케이스 판별, 분기 A/B/C)은 **내부 오케스트레이터/developer**가 수행
- 케이스 2는 허용하지 않음 — 새 기능 구축은 상엽 승인 필수

### 흐름

```
외부 LLM (클라이언트)
  → request-change CLI command 실행
  → 오케스트레이터 수신
  → 케이스 판별 (1 또는 1.5만 허용)
  → developer 할당 → 실행
  → 결과를 외부 LLM에 반환
```

### 허용 범위

| 케이스 | 외부 LLM 허용 | 이유 |
|--------|--------------|------|
| 1 (실행) | O | 기존 tool 호출 요청 — 위험 없음 |
| 1.5 (확장) | O | 판단/실행은 내부 — 외부는 요청만 |
| 2 (구축) | X | Feature Pipeline은 상엽 승인 필요 |

구체적인 tool 스펙, 인증, 큐 구조는 구현 시 확정. → [[03-projects/whos-life/ideas-backlog|ideas-backlog]] 참조.

## 케이스별 요약

| 케이스 | 핵심 | 주체 | 참조 문서 |
|--------|------|------|-----------|
| 1 (실행) | 기존 코드 실행 | developer | context.md |
| 1.5 (확장) | 기존 코드 수정/확장 | developer (판단) → 분기 A/B/C | context.md, developer.md |
| 2 (구축) | 새 기능 구축 | orchestrator → pipeline | [[feature-pipeline]] |
