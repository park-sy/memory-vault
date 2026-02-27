# Memory Vault

AI 에이전트의 장기기억 체계. 이 디렉토리에서 claude를 실행하면 이 파일이 자동 로드된다.

## 세션 시작 프로토콜

**반드시 아래 순서대로 읽고 시작할 것:**

1. `01-org/head.md` — 너의 영혼. 행동 원칙, 경계, 규율.
2. `01-org/user.md` — 상엽 정보.
3. `01-org/identity.md` — 너의 정체성.
4. `05-sessions/` — 최신 2개 파일을 읽어서 최근 컨텍스트 파악.
5. 이번 작업 관련 기억 검색 — tags + importance 기준으로 `02-knowledge/`, `06-skills/`에서 관련 파일 탐색.
6. 읽은 파일의 frontmatter 갱신 — `last_accessed` → 오늘 날짜, `access_count` += 1.

읽은 후 간단히 인사하고 바로 대화 시작. "파일을 읽었습니다" 같은 보고 불필요.

## 역할 전환

별도 tmux 세션 없이, 상엽이 말하면 역할을 전환한다:
- "플래닝 해줘" → `01-org/product/planner.md` 읽고 planner 모드
- "코딩 해줘" → `01-org/engineering/worker.md` 읽고 worker 모드
- "오케스트레이션" → `01-org/ops/orchestrator.md` 읽고 orchestrator 모드

역할 파일에 "읽어야 할 파일" 목록이 있으면 그것도 읽는다.

## 기억 기록

### 새 기억 작성 규칙
- 반드시 frontmatter 포함 (type, importance, created, tags 필수)
- importance 자가 평가 (1-10, 기준: CLAUDE.md 하단 표 참조)
- 관련 노트에 `[[wiki-link]]` 연결

### 세션 중
- 중요한 결정, 교훈, 실수 → 해당 역할의 `*-memory.md`에 바로 기록
- 프로젝트 관련 → `03-projects/{name}/`에 기록
- 읽은 기억 파일의 `last_accessed`, `access_count` 갱신

### 세션 종료 시
- `05-sessions/YYYY-MM-DD.md` 에 오늘 세션 요약 작성 (frontmatter 포함, 또는 기존 파일에 추가)
- 증류할 만한 내용이 있으면 `05-sessions/_distill-queue.md`에 등록
- 읽은 기억 파일들의 `last_accessed`, `access_count` 최종 갱신

### 승격 규칙
- 3회 이상 반복 검증된 패턴 → `02-knowledge/patterns/`로 승격
- 중요한 아키텍처 결정 → `04-decisions/`에 ADR 작성
- 새 실수 패턴 → `02-knowledge/mistakes/`에 기록

### importance 기준표

| 점수 | 기준 | 예시 |
|------|------|------|
| 9-10 | 아키텍처 결정, 반복 치명적 실수 | "DB는 반드시 마이그레이션으로" |
| 7-8 | 검증된 패턴, 프로젝트 핵심 맥락 | "immutable state", "인증 구조" |
| 5-6 | 유용하지만 범용적 | "API 캐싱 방법" |
| 3-4 | 일회성 해결, 상황 의존적 | "라이브러리 버그 우회" |
| 1-2 | 사소한 임시 메모 | "회의 시간 변경" |

## 디렉토리 구조

| 디렉토리 | 용도 |
|----------|------|
| `00-MOC/` | Maps of Content — 전체 인덱스, 조직도, 지식맵 |
| `01-org/` | 조직 — head(원칙), user(상엽), identity(얍), 부서별 역할+기억 |
| `02-knowledge/` | 공유 지식 — patterns, stack, conventions, mistakes |
| `03-projects/` | 프로젝트별 컨텍스트 (overview, tasks, backlog) |
| `04-decisions/` | ADR (Architecture Decision Records) |
| `05-sessions/` | 세션 로그 → 증류 → permanent note |
| `06-skills/` | 방법론 문서 (feature-pipeline, planner, auto-dev) |
| `templates/` | 옵시디언 노트 템플릿 |

## 워커 풀 관리

워커는 항상 켜져있는 idle tmux 세션이다. 범용 실행자로, 어떤 작업이든 수행할 수 있다.
오케스트레이터 세션에서 `scripts/pool.sh`를 호출해 관리한다.

### 기본 사용법

```bash
# 워커 3개 생성 (기본 역할: worker)
bash scripts/pool.sh init 3

# 상태 확인
bash scripts/pool.sh status

# 작업 전달
bash scripts/pool.sh send 1 "~/dev/myproject/src/auth.py 코드 리뷰해줘"

# 출력 확인
bash scripts/pool.sh capture 1

# 재시작
bash scripts/pool.sh reset 1

# 전체 종료
bash scripts/pool.sh teardown
```

### 역할 및 프로젝트 디렉토리 지정

```bash
# planner 역할로 2개 생성
bash scripts/pool.sh init 2 --role planner

# 특정 프로젝트 디렉토리에서 워커 실행
bash scripts/pool.sh init 1 --role worker --dir ~/dev/whos-life

# 워커 2를 planner로 역할 변경 재시작
bash scripts/pool.sh reset 2 --role planner
```

사용 가능 역할: `worker`(기본), `planner`, `orchestrator`, 또는 절대 경로

### 워크플로우별 사용 예시

```bash
# Feature Pipeline: designing 작업
bash scripts/pool.sh send 1 "whos-life 여행 기능 designing 해줘. spec: ~/dev/whos-life/work_logs/features/travel-planner/spec.md"

# 범용: 코드 리뷰
bash scripts/pool.sh send 2 "~/dev/myproject/src/utils.py 리뷰해줘. 성능 중점."

# 범용: 리서치
bash scripts/pool.sh send 3 "Next.js 14 Server Actions vs API Routes 비교 분석해줘."
```
