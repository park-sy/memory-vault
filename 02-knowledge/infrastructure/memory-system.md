---
type: knowledge
importance: 9
created: "2026-03-01"
tags: [memory, obsidian, vault, hooks, infrastructure, frontmatter]

---

# Memory System — 옵시디언 기반 장기기억 체계

## 개요

memory-vault는 AI 에이전트(얍)의 장기기억을 옵시디언 vault + git으로 관리하는 시스템이다.
세션마다 초기화되는 LLM의 한계를 파일 기반 기억으로 극복한다.

핵심 원칙:
- **아는 것 = 파일에 있는 것** — 암묵지가 구조적으로 불가능
- **wiki-link 기반 상호참조** — 옵시디언 그래프 뷰로 지식 연결 시각화
- **git 버전 관리** — 타임트래블, 롤백, blame 가능

## Vault 디렉토리 구조

```
memory-vault/
├── 00-MOC/           인덱스, 조직도, 지식맵 (다른 노트를 묶는 목차)
├── 01-org/           조직 정의 — 원칙, 정체성, 코어팀, 오케스트레이터
│   ├── head.md       상위 지침 (SOUL)
│   ├── identity.md   에이전트 정체성
│   ├── user.md       사용자(상엽) 프로필
│   ├── orchestrator.md  오케스트레이터 역할
│   └── core/         코어팀 역할별 (planner, coder, reviewer, qa, researcher, web-searcher)
│       └── {role}/
│           ├── role.md    역할 정의
│           └── memory.md  누적 학습
├── 02-knowledge/     프로젝트 독립적 공유 지식
│   ├── patterns/     3회+ 검증된 패턴
│   ├── conventions/  코딩 컨벤션, 에이전트 규칙
│   ├── infrastructure/  시스템 인프라 문서 (이 파일 포함)
│   └── mistakes/     실수 DB
├── 03-projects/      도메인별 컨텍스트 (프로젝트, 실험, 리서치)
│   └── {name}/
│       ├── context.md              도메인 컨텍스트 (정본)
│       ├── developer.md            도메인 developer 역할 (project 유형)
│       ├── specialist.md           도메인 specialist 역할 (experimentation 유형)
│       ├── developer-memory.md     도메인 종속 기억 (project)
│       ├── specialist-memory.md    도메인 종속 기억 (experimentation)
│       └── ideas-backlog.md        아이디어 백로그
├── 04-decisions/     ADR (아키텍처 결정 기록)
├── 05-sessions/      세션 로그 (날짜별 요약)
├── 06-skills/        재사용 방법론 ("어떻게 하는가")
├── 07-clone/         의사결정 복제 (캡처 → 합성 → 실행)
└── templates/        옵시디언 노트 템플릿
```

### 배치 규칙

| 디렉토리 | O (넣는 것) | X (넣지 않는 것) |
|----------|-------------|-----------------|
| `00-MOC/` | 다른 노트를 묶는 목차/맵 | 실제 콘텐츠 |
| `01-org/` | 원칙, 정체성, 역할 정의, memory | 프로젝트 작업물 |
| `02-knowledge/` | 3회+ 검증된 범용 패턴 | 프로젝트 종속 지식 |
| `03-projects/` | 도메인 컨텍스트 (소프트웨어 프로젝트, 실험/최적화, 리서치 등) | 범용 패턴 |
| `04-decisions/` | "왜 이렇게 결정했는가" | 구현 방법 |
| `05-sessions/` | 날짜별 세션 요약 | 영구 보존 지식 |
| `06-skills/` | "어떻게 하는가" 절차 문서 | 일회성 작업 목록 |
| `07-clone/` | decision-log, profile | 일반 기억 |

## Frontmatter 규약

모든 기억 파일은 YAML frontmatter를 포함한다:

```yaml
---
type: knowledge        # knowledge | decision | skill | project | session | team | moc
importance: 7          # 1-10 (아래 기준표 참조)
created: "2026-02-28"
tags: [memory, pattern, ...]
---
```

### importance 기준표

| 점수 | 기준 | 예시 |
|------|------|------|
| 9-10 | 아키텍처 결정, 반복 치명적 실수 | "DB는 반드시 마이그레이션으로" |
| 7-8 | 검증된 패턴, 프로젝트 핵심 맥락 | "immutable state 패턴" |
| 5-6 | 유용하지만 범용적 | "API 캐싱 방법" |
| 3-4 | 일회성 해결, 상황 의존적 | "라이브러리 버그 우회" |
| 1-2 | 사소한 임시 메모 | "회의 시간 변경" |

### 접근 추적 (역할 인식)

파일 접근 기록은 `storage/access_tracker.db` SQLite DB에서 **역할별로** 관리된다.
PostToolUse hook (`access_tracker.py`)이 Read 도구 사용 시 자동으로 기록한다.

```sql
-- file_role_access 테이블 — 파일별 역할별 접근 카운트
file_path     TEXT NOT NULL     -- vault root 기준 상대경로
role          TEXT NOT NULL     -- "coder", "planner", "unknown" 등
access_count  INTEGER NOT NULL  -- 해당 역할의 누적 접근 횟수
last_accessed TEXT NOT NULL     -- ISO date (YYYY-MM-DD)
PRIMARY KEY (file_path, role)

-- session_role 테이블 — 세션별 현재 활성 역할
session_id    TEXT PRIMARY KEY  -- os.getppid() 기반
active_role   TEXT NOT NULL     -- 현재 역할
updated_at    TEXT NOT NULL     -- 마지막 역할 전환 시각
```

#### 역할 감지 원리

`memory.md` 읽기가 역할 활성화 시그널:
- `01-org/core/coder/memory.md` Read → 세션 역할 = "coder"
- `01-org/enabling/orchestrator/memory.md` Read → 세션 역할 = "orchestrator"
- 이후 읽는 모든 파일은 해당 역할로 귀속

#### reference_rate — 정규화된 참조 비율

```
reference_rate = file의 role별 count / 해당 role의 memory.md count
```

역할의 memory.md 카운트 = 역할 활성화 횟수 (분모).
이로써 스폰 빈도에 무관한 **실제 참조율**을 얻는다.

예시:
- coder/memory.md 100회, test.md coder:10 → rate 10%
- planner/memory.md 10회, test.md planner:8 → rate 80% → hot

#### API

```python
get_access_info(rel_path)        # → (last_accessed, total_count)
get_all_access_info()            # → {path: {last_accessed, total_count, role_counts}}
get_role_baselines()             # → {role: memory.md_count}  (rate 계산의 분모)
```

frontmatter에는 `access_count`/`last_accessed`를 저장하지 않는다.

## 기억 수명주기

```
Hot (활발)  →  Warm (주기적)  →  Cold (미접근)  →  Archive
```

| 상태 | 기준 (reference_rate + 경과일) | 대시보드 |
|------|------|----------|
| Hot | max_rate >= 30% AND 14일 이내 접근 | Dataview 쿼리 자동 표시 |
| Warm | max_rate >= 10% OR 7일 이내 접근 | 주기적 참조 |
| Cold | 60일 이내 미접근 | 아카이브 후보 |
| Archive | 60일+ 미접근 | `02-knowledge/archive/` |

### Dataview 대시보드 (`00-MOC/dashboard.md`)

옵시디언 Dataview 플러그인으로 frontmatter 자동 쿼리:

```dataview
TABLE importance, tags
FROM "02-knowledge" OR "01-org/core"
SORT importance DESC
```

> **Note**: `access_count`와 `last_accessed`는 `storage/access_tracker.db`에서 관리되므로 Dataview 쿼리 대상이 아니다. vault-ui 대시보드에서 확인 가능.

## 승격 규칙

기억은 검증 횟수에 따라 상위 디렉토리로 승격된다:

```
세션 교훈 (05-sessions/)
  → 역할 memory.md (01-org/core/{role}/ 또는 03-projects/{name}/)
    → 3회+ 반복 검증 → 02-knowledge/patterns/ 승격
    → 아키텍처 결정 → 04-decisions/ ADR 작성
    → 반복 실수 → 02-knowledge/mistakes/ 기록
```

### 저장 위치 판별

```
교훈/패턴 발생
  ├─ 프로젝트 종속? → 03-projects/{name}/developer-memory.md
  └─ 프로젝트 무관? → 01-org/core/{role}/memory.md
```

## 세션 프로토콜

### 세션 시작 (5단계)

1. `01-org/head.md` — 행동 원칙 (SOUL)
2. `01-org/user.md` — 상엽 정보
3. `01-org/identity.md` — 에이전트 정체성
4. `05-sessions/` — 최신 2개 파일 (최근 컨텍스트)
5. 작업 관련 기억 검색 — tags + importance 기준

### 세션 종료

1. `05-sessions/YYYY-MM-DD.md` 세션 요약 작성
2. 증류 대상 → `05-sessions/_distill-queue.md` 등록
3. 의사결정 캡처 → `07-clone/decision-log.md` 추가

## Hook 연동

Claude Code hooks가 기억 체계와 연동된다:

### whos-life 프로젝트 hooks (`.claude/settings.json`)

| 이벤트 | Hook | 동작 |
|--------|------|------|
| SessionStart | `session_status.py` | 세션 상태 추적 시작 |
| UserPromptSubmit | `session_status.py` | 활동 상태 업데이트 |
| Notification (idle_prompt) | `session_status.py` | idle 상태 기록 |
| PostToolUse (Write\|Edit) | `post_service_edit.sh` | service.py 변경 시 context.md 갱신 제안 |
| Stop | `session_status.py` + `telegram_notify.py` | 세션 종료 기록 + Telegram 알림 |

### Hook이 기억 체계에 미치는 영향

- `post_service_edit.sh`: service.py 변경 → context.md 갱신 제안 → **도메인 컨텍스트 자동 최신화**
- `telegram_notify.py`: 세션 종료 → Telegram 알림 → **상엽에게 결과 즉시 전달**
- `session_status.py`: 세션 상태 전이 → **오케스트레이터가 워커 상태 파악**

## Related

- [[04-decisions/001-vault-structure]] — Vault 구조 채택 결정
- [[04-decisions/002-platform-team-structure]] — 코어팀 구조
- [[02-knowledge/infrastructure/platform-team-operations]] — 팀 운영 가이드
- [[02-knowledge/infrastructure/communication-system]] — 통신 체계
