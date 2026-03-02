---
type: knowledge
importance: 9
created: "2026-03-01"
last_accessed: "2026-03-01"
access_count: 1
tags: [core-team, operations, domain-team, enabling-team, infrastructure]
---

# 팀 운영 가이드

> **Team Topologies 용어 매핑** (이 문서 내 유일한 TT 참조):
> Platform Team → 코어팀 | Enabling Team → 운영팀 | Stream-aligned Team → 도메인팀

## 개요

3개 팀 유형 구조.
결정 근거는 [[04-decisions/002-platform-team-structure|ADR-002]] 참조.

```
┌──── 운영팀 (운영/최적화) ────┐
│  Orchestrator | (확장 가능)   │
└─────────────────┬────────────┘
                  │ 조율/최적화
┌─────────── 코어팀 (전문팀) ───────────┐
│  Planner | Researcher | Reviewer | QA | Coder | WebSearcher │
└──────┬──────────┬──────────┬──────────┬───────────┘
       │          │          │          │
  ┌────┴───┐ ┌───┴────┐ ┌──┴───┐ ┌───┴────┐
  │whos-life│ │mem-vault│ │ ...  │ │  ...   │
  │developer│ │developer│ │      │ │        │
  │+context │ │+context │ │      │ │        │
  └────────┘ └────────┘ └──────┘ └────────┘
       도메인팀
```

## 용어 정의

| 용어 | 정의 | 레벨 |
|------|------|------|
| **세션(session)** | tmux 안의 Claude Code 인스턴스. 실행 단위. | 인프라 |
| **워커(worker)** | 역할(role)이 부여된 세션. 작업을 수행할 수 있는 상태. | 운영 |
| **풀(pool)** | 워커들의 관리 단위. `pool.sh`로 생성/관리. | 운영 |
| **역할(role)** | 팀 내 전문 기능 정의 (planner, coder 등). `role.md`로 정의. | 조직 |
| **모드(mode)** | 단독 세션에서 역할을 전환한 상태. 상엽이 직접 대화하며 조종. | 운영 |
| **Feature Factory** | 자동화 오케스트레이션 데몬 (`cc-factory`). 파이프라인을 코드로 구동. | 인프라 |

**세션 vs 워커:** "세션 3개 생성 → 각각 coder 워커로 초기화". 세션은 빈 그릇, 워커는 역할이 담긴 그릇.
**워커 vs 모드:** pool 세션에서 역할 부여 = 워커. 단독 세션에서 역할 전환 = 모드. 같은 role.md 사용.
**모드 vs 워커 (Feature Factory 기준):**

| 구분 | 모드(mode) | 워커(worker) |
|------|-----------|-------------|
| 주체 | 상엽 ↔ 얍 직접 대화 | Feature Factory 데몬이 관리 |
| 맥락 | 단독 세션, 역할 전환 자유 | tmux 세션, 역할 고정 |
| 완료 감지 | 상엽이 직접 판단 | MsgBus 완료 알림 (자동) |
| 승인 | 대화 중 즉시 | Telegram 버튼 |

## 코어팀

프로젝트에 독립적인 전문 역량 팀. 여러 도메인을 넘나들며 교차 수분한다.

### 구성원

| 역할 | 파일 | 완료 키워드 | 전문 영역 |
|------|------|-------------|-----------|
| Planner | `01-org/core/planner/role.md` | `SPEC_READY` | 요구사항 → spec 변환 |
| Researcher | `01-org/core/researcher/role.md` | `RESEARCH_DONE` | 리서치, 분석, 비교 |
| Reviewer | `01-org/core/reviewer/role.md` | `REVIEW_DONE` | 코드/설계 리뷰 |
| QA | `01-org/core/qa/role.md` | `QA_DONE` | 테스트, 검증, 품질 보증 |
| Coder | `01-org/core/coder/role.md` | `CODE_DONE` | 구현, 코딩 패턴, 최적화 |
| Web Searcher | `01-org/core/web-searcher/role.md` | `SEARCH_DONE` | 실시간 웹 검색 |

### 역할 진입/전환

상엽이 키워드를 말하면 역할을 전환한다 (별도 tmux 세션 불필요):

| 상엽 명령 | 로드 파일 | 모드 |
|-----------|----------|------|
| "플래닝 해줘" | `core/planner/role.md` | Planner |
| "리서치 해줘" | `core/researcher/role.md` | Researcher |
| "리뷰 해줘" | `core/reviewer/role.md` | Reviewer |
| "QA 해줘" / "테스트 해줘" | `core/qa/role.md` | QA |
| "코딩 해줘" | `core/coder/role.md` | Coder |
| "오케스트레이션" | `01-org/enabling/orchestrator/role.md` | Orchestrator |

역할 파일에 "읽어야 할 파일" 목록이 있으면 그것도 함께 로드한다.

### 역할 수행 흐름

```
역할 진입
  → role.md 로드 + "읽어야 할 파일" 로드
  → memory.md 로드 (누적 학습)
  → 작업 수행
  → 교훈 발생 시 memory.md에 즉시 기록
  → 완료 시 완료 키워드 출력 (SPEC_READY, CODE_DONE 등)
```

### memory 기록 규칙

- 범용 패턴 → `01-org/core/{role}/memory.md`
- 도메인 특수 지식 → `03-projects/{name}/developer-memory.md` + wiki-link
- 3회+ 검증 패턴 → `02-knowledge/patterns/`로 승격

## 도메인팀

프로젝트별 컨텍스트 + 도메인 전문 개발 담당.

### 구성

각 프로젝트 디렉토리에:

| 파일 | 역할 |
|------|------|
| `context.md` | 도메인 컨텍스트 (정본). 스택, 구조, 컨벤션, 기능 목록 |
| `developer.md` | 도메인 developer 역할 정의 |
| `developer-memory.md` | 도메인 종속 기억 |

### Context Injection 모델

도메인팀 세션은 **3개 파일이 주입되어야** 작업 가능:

1. `{project}/context.md` — 도메인 컨텍스트 (스택, 기존 기능 목록)
2. `01-org/core/{role}/role.md` — 필요한 코어팀 역할
3. `06-skills/feature-pipeline.md` — 케이스 2 진입 시

developer.md가 이 3개를 "읽어야 할 파일"로 참조한다.

## 운영팀 (운영/최적화)

다른 팀의 역량을 강화하거나 시스템 자체를 최적화하는 팀.
직접 기능을 만들지 않고, 만드는 과정을 개선한다.

### 구성원

| 역할 | 파일 | 책임 |
|------|------|------|
| Orchestrator | `01-org/enabling/orchestrator/role.md` | 작업 라우팅, 워커 풀 관리, 결과 추적 |

> 향후 확장 후보: Token Optimizer (비용 분석/최적화), Architect (팀 구조 취약점 분석)

### 오케스트레이터 케이스 판별

```
사용자 요청
  ├─ 기존 기능으로 해결 → 케이스 1 (실행) → developer 위임
  ├─ 기존 기능 수정/확장 → 케이스 1.5 (확장) → developer 판단
  │    ├─ 분기 A: 인라인 수정 → developer 직접
  │    ├─ 분기 B: 구조 내 확장 → developer + 코어팀
  │    └─ 분기 C: 에스컬레이션 → 케이스 2 전환
  └─ 완전히 새 기능 → 케이스 2 (구축) → Feature Pipeline
```

상세 라우팅 규칙: [[06-skills/workflow-routing]]

## 워커 풀

tmux 세션 기반 워커 풀. 오케스트레이터가 `scripts/pool.sh`로 관리.

### 워커 풀 ≠ 팀

워커 풀은 팀 토폴로지의 팀이 아니라 **실행 인프라**다.
어떤 팀의 어떤 역할이든 워커로 실행할 수 있다.

```
팀 토폴로지 (누가, 무엇을)        실행 인프라 (어떻게)
─────────────────────         ────────────────────
코어팀                         단독 세션 → 모드 전환
  planner, coder, ...            (상엽이 직접 대화)

도메인팀                       워커 풀 → 역할 고정
  whos-life developer              (pool.sh로 자동화)
  memory-vault developer

운영팀
  orchestrator
```

예시:
```bash
pool.sh init 1 --role planner                     # 코어팀 역할을 워커로
pool.sh init 1 --role coder --dir ~/dev/whos-life  # 도메인팀 역할을 워커로
```

### 기본 명령

```bash
bash scripts/pool.sh init 3                           # 워커 3개 생성
bash scripts/pool.sh init 2 --role planner             # planner 역할로
bash scripts/pool.sh init 1 --role coder --dir ~/dev/whos-life  # 특정 프로젝트
bash scripts/pool.sh status                            # 상태 확인
bash scripts/pool.sh send 1 "작업 메시지"                # 작업 전달
bash scripts/pool.sh capture 1                         # 출력 확인
bash scripts/pool.sh reset 2 --role planner            # 역할 변경 재시작
bash scripts/pool.sh teardown                          # 전체 종료
```

사용 가능 역할: `planner`, `researcher`, `reviewer`, `qa`, `coder`, `orchestrator`, 또는 절대 경로

## 자동화 도구

코어팀 구조의 단점을 해소하는 9개 자동화 도구.
상세: [[03-projects/memory-vault/platform-team-automation]]

### 요약

| 구분 | ID | 이름 | 해소하는 단점 |
|------|-----|------|-------------|
| Hook | H-1 | context-auto-sync | context.md 관리 부담 |
| Hook | H-2 | task-router | 사소한 작업 오버킬 |
| Hook | H-3 | handoff-trigger | 핸드오프 유실 |
| Script | S-1 | conflict-detector | 패턴 충돌 |
| Script | S-2 | memory-archiver | memory 비대화 |
| Script | S-3 | core-seed | 콜드 스타트 |
| Skill | K-1 | responsibility-assign | 책임 소재 분산 |
| Skill | K-2 | cross-review | 패턴 충돌 |
| Skill | K-3 | domain-context-brief | 컨텍스트 반복 로딩 |

## AI 에이전트이기 때문에 가능한 이유

사람 조직에서 비효율적인 이 구조가 AI에서 작동하는 이유:

- **세션 스케일링**: 역할 "전환"이 아니라 "복제" — 같은 역할 세션 추가 가능
- **컨텍스트 스위칭 ≈ 파일 로드**: 사람은 ~23분, AI는 즉시
- **메모리 공유**: 동일 파일 → 동일 지식 (해석 편차 0)
- **암묵지 불가능**: 아는 것 = 파일에 있는 것
- **버스 팩터 ∞**: 세션이 죽어도 지식 손실 0
- **롤백**: memory.md 수정 또는 git revert로 오염 즉시 복구

## Related

- [[04-decisions/002-platform-team-structure]] — 결정 근거
- [[01-org/core/_team]] — 코어팀 구성원 목록
- [[03-projects/memory-vault/platform-team-automation]] — 자동화 상세
- [[06-skills/workflow-routing]] — 케이스 판별 및 라우팅
