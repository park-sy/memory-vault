# Feature Pipeline v2 — Skill-First 개발 파이프라인

## 개요
아이디어를 Skill로 먼저 검증한 뒤, 반복 패턴만 코드로 전환하는 파이프라인.
LLM은 판단만, 실행은 코드로. 토큰 효율 극대화.

## 3-Tier 세션 구조

| Tier | 세션 | 역할 | 수량 |
|------|------|------|------|
| 오케스트레이션 | `cc-orchestration` tmux | 태스크 관리/배정. 직접 작업 안 함 | 1 |
| 계획 전문가 | `cc-planner` tmux | `idea → spec` 전담. 사용자와 대화하며 spec 구체화 | 1 |
| Worker | `cc-pool-{1..N}` | `designing → coding → done` 실행 | N |

### 핵심 흐름
```
상엽: "/feature 여행 기능" → Yap → OpenClaw → cc-orchestration
  → idea 생성 + planner에 tmux send-keys
  → 코봉 알림 즉시 발송 (planner 딥링크)
  → 상엽이 딥링크 탭 → planner 세션에서 직접 대화하며 spec 작성
  → SPEC_READY → 코봉 알림 "spec 완료"
  → 상엽: "승인해" → spec → queued → worker 배정 (기존 흐름)
```

## 트리거

`/feature` 로 시작하는 메시지를 받으면 이 스킬을 실행한다.

| 명령 | 동작 |
|---|---|
| `/feature` | "어떤 기능 만들까?" 물어보고 → 답변으로 파이프라인 시작 |
| `/feature {제목}` | 바로 파이프라인 시작 (idea → planner 할당) |
| `/feature status` | 전체 파이프라인 현황 (get_pipeline_status) |
| `/feature list` | 활성 태스크 목록 (get_queue_status, done 제외) |
| `/feature approve {id}` | 승인 (stage에 따라 spec/plan/stable 승인) |
| `/feature approve planner` | planner spec 승인 → queued |
| `/feature detail {id}` | 태스크 상세 정보 |

텔레그램, webchat 등 모든 채널에서 동작.

### 사용자 메시지 → 명령 매핑

| 사용자 메시지 예시 | 오케스트레이션 동작 |
|---|---|
| "여행 기능 만들어줘" | `assign_feature("여행 기능")` |
| "planner 승인" / "spec 승인해" | `approve("planner")` |
| "pool-1 승인" / "승인해" | `approve("pool-1")` |

## 파이프라인 단계

```
idea → spec(planner) → [spec 승인] → queued → designing(계획 생성) → [계획 승인] → designing(실행) → testing ⇄ designing → [승인] → stable → coding(계획 생성) → [계획 승인] → coding(실행) → done
```

### 단계별 역할

| 단계 | 세션 | 하는 일 | 산출물 |
|---|---|---|---|
| idea | planner | 아이디어 등록 + planner 할당 | 제목 + 설명 |
| spec | planner | 상엽과 대화하며 spec 구체화 (3가지 관점 필수) | spec.md |
| queued | - | spec 승인 후 대기 | - |
| designing | SKILL.md + config.json 작성 | skills/{name}/SKILL.md |
| testing | Tool-Level Verification: 각 MCP tool 개별 검증 + codification 분석 | Tool Test Results + codification 리포트 |
| stable | 충분히 검증됨, coding 슬롯 대기 | - |
| coding | codification 분석 기반 service.py + render.py 구현 | whos-life feature 완성 |
| done | skill + code 혼합 운영 | 최종 구조 |

### SKILL.md 형식 규격 (designing 산출물)

designing이 생성하는 각 feature SKILL.md는 아래 7개 섹션을 필수로 포함한다.

| # | 섹션 | 내용 |
|---|------|------|
| 1 | **MCP Tool Specifications** | 함수명, Input Model(Pydantic frozen), Output, Logic, LLM Boundary, Error Cases |
| 2 | **DB Schema** | 실행 가능한 SQLite CREATE TABLE + INDEX |
| 3 | **Data Models** | Pydantic BaseModel 정의 (frozen=True) |
| 4 | **UI Screen Flow** | 화면별 데이터 소스(tool), 사용자 액션 |
| 5 | **Agent Orchestration** | tool 체이닝 순서, 판단 포인트, 에러 복구 |
| 6 | **Test Scenarios** | tool별 테스트 케이스 (입력 → 기대 출력) |
| 7 | **LLM Boundary Summary** | spec.md Level 0/1/2를 tool 단위로 매핑 |

#### @tool 표준 패턴

```python
@tool(description="설명")
def tool_name(db: Any, params: SomeInput) -> dict:
    """Logic 설명."""
    # Level 0: 코드로 100% 구현
    # Level 1: tool 내부에서 llm_call(task_type="structured") 호출
    # Level 2: 데이터 읽기/쓰기만. 판단은 Agent Orchestration에 기술
    ...
```

#### LLM Boundary별 service.py 처리 패턴

| LLM Boundary | SKILL.md에 표기 | service.py 구현 |
|---|---|---|
| Level 0 | `LLM: 없음` | 코드로 100% 구현 |
| Level 1 | `LLM: 정형 (tool 내부)` | tool 내부에서 `llm_call(task_type="structured")` 호출. 모델은 config 기반 |
| Level 2 | `LLM: 에이전트 판단` | 데이터 tool만 제공, Agent Orchestration에 판단 로직 기술 |

> 모델명(Flash, Opus 등)은 SKILL.md에 쓰지 않음. 작업 유형(정형/비정형)만 명시하고 실제 모델 선택은 런타임 config.

**원칙**: SKILL.md는 "에이전트가 대화로 실행하는 흐름"이 아니라 **"빌드할 MCP tool과 UI의 명세서"**.

#### 공통 모듈 참조 (designing 시 활용 가능)

| 모듈 | 위치 | 용도 |
|------|------|------|
| 웹 검색 | `core/web_search.py` | Brave Search API 래퍼 |
| LLM 유틸 | `core/llm_utils.py` | 정형/비정형 LLM 동기 호출 (Level 1 tool 내부용) |
| 날씨 API | `core/weather.py` | Open-Meteo 래퍼 |
| 환율 | `core/exchange_rate.py` | 월 평균 환율 조회 |

### spec 단계 필수 관점 (3가지)

#### 1. 사용자 관점 (UI/UX)
- 화면 플로우: 사용자가 어떤 순서로 어떤 화면을 보는지
- 와이어프레임: 각 화면의 레이아웃 (ASCII도 OK)
- 인터랙션: 버튼/입력/선택 등 사용자 액션 정의
- **단계 분리**: 한 번에 모든 결과를 뱉지 않고, 사용자가 단계별로 진행

#### 2. AI 에이전트 관점 (SKILL 실행)
- 에이전트가 이 기능을 어떤 흐름으로 실행하는지
- MCP tool 호출 순서 + 판단 포인트
- 외부 데이터 소스 (검색, API 등) 정의
- LLM Boundary 분해 (Level 0/1/2)

#### 3. 데이터 관점 (DB 설계)
- 테이블 구조 + 관계도
- 주요 필드, 타입, 제약조건
- CRUD 시나리오 (어떤 화면에서 어떤 데이터가 생성/조회/수정/삭제되는지)
- migration SQL 초안

### 승인 게이트 (4개)
1. **spec → queued**: "이거 만들 만한가?" — `approve_to_queue` MCP tool
2. **designing 계획**: "이 설계 방향 맞나?" — `approve_plan` MCP tool (신규)
3. **testing → stable**: "충분히 검증됐나?" — `approve_stable` MCP tool
4. **coding 계획**: "이 구현 방향 맞나?" — `approve_plan` MCP tool (신규)

## 실행 규칙

### 동시 실행 제한 (깔때기 구조)
```
≤50% 토큰 → designing 5개, coding 1개
≤70% 토큰 → designing 3개, coding 1개
≤90% 토큰 → designing 1개, coding 0개
>90% 토큰 → 전부 중단
```

### designing 단계 수행 절차

#### Phase 1: 계획 생성 (자동)
1. 스케줄러가 queued → designing 전환
2. 계획 생성 CLI 실행 → 아키텍처 plan JSON 생성
3. `plan_status = pending_review` 로 저장
4. 사용자에게 알림: "설계 계획 승인 필요"

#### Phase 2: 사용자 승인
5. 사용자가 `approve_plan(id)` 또는 `reject_plan(id, reason)` 호출
6. rejected → 다음 tick에서 계획 재생성
7. approved → Phase 3 진행

#### Phase 3: 실행 (계획 승인 후)
8. spec.md의 LLM Boundary (Level 0/1/2) 참조
9. SKILL.md 작성 — **7개 섹션 규격 필수 준수** (위 "SKILL.md 형식 규격" 참조):
   - MCP Tool Specifications (가장 중요)
   - DB Schema (실행 가능한 CREATE TABLE SQL)
   - Data Models (Pydantic frozen)
   - UI Screen Flow
   - Agent Orchestration
   - Test Scenarios (testing에서 검증할 대상)
   - LLM Boundary Summary
10. config.json 작성 (설정값 분리)
11. designing 복귀인 경우: `decisions/{N}-{title}.md` 작성 (왜 바꿨는지)
12. SKILL.md가 길어지면 `skills/` 하위 스킬로 분리
13. `advance_stage(id, "testing")` 호출 + plan 초기화

### testing 단계 수행 절차 (Tool-Level Verification)

> ⚠️ **금지**: 기능 전체를 사용자처럼 실행하지 않는다. 각 MCP tool을 개별적으로 검증한다.

1. **DB Schema 검증** — SKILL.md의 CREATE TABLE SQL 실행, 테이블 생성 확인
2. **Tool 단위 테스트** (핵심) — 각 MCP tool 개별 검증:
   - SKILL.md Test Scenarios의 입력값으로 tool 로직 실행 (DB 조작 직접 수행)
   - 반환값 vs 기대 출력 비교
   - Error case 처리 확인
3. **Tool 체이닝 통합 테스트** — Agent Orchestration 순서대로 데이터 흐름 검증
4. **UI 데이터 흐름 검증** — 화면별 데이터 소스 tool 반환값이 UI에 충분한지 확인
5. **Codification 분석** — 각 tool을 `codifiable` / `llm_required` / `hybrid`로 분류
6. **판정** — tool 전체 통과 시 stable 승인 요청, 실패 시 designing 복귀 (decisions/ 기록)
7. `logs/test-{N}.md` 에 Tool Test Results + Codification 분석 기록
8. `record_test_run(id, success, log)` 로 결과 기록

### coding 단계 수행 절차

#### Phase 1: 계획 생성 (자동)
1. 스케줄러가 stable → coding 전환
2. 계획 생성 CLI 실행 → 구현 plan JSON 생성
3. `plan_status = pending_review` 로 저장
4. 사용자에게 알림: "구현 계획 승인 필요"

#### Phase 2: 사용자 승인
5. 사용자가 `approve_plan(id)` 또는 `reject_plan(id, reason)` 호출
6. rejected → 다음 tick에서 계획 재생성
7. approved → Phase 3 진행

#### Phase 3: 실행 (계획 승인 후)
8. `logs/test-{N}.md`의 codification 분석 읽기
9. `codifiable` → service.py @tool 함수 구현
10. `hybrid` → service.py 기본 로직 + SKILL.md 예외 처리 유지
11. `llm_required` → SKILL.md에 그대로 유지 (코드화 안 함)
12. render.py UI 구현
13. `advance_stage(id, "done")` 호출 + plan 초기화

## 알림
모든 단계 전환 시 알림 발송 (설정에 따라 ON/OFF).
- `get_notify_settings()` 로 현재 설정 확인
- 승인 게이트는 OFF 시에도 승인 요청 알림은 별도 전송

## MCP Tools (whos-life dev-queue feature)
- `register_idea(title, description, category)` — idea 등록
- `append_interview_log(id, log)` — 인터뷰 내용 기록
- `approve_to_queue(id)` — spec → queued 승인
- `approve_stable(id)` — testing → stable 승인
- `submit_plan(id, plan_json)` — designing/coding 계획 제출 (pending_review 상태로)
- `get_plan(id)` — 태스크의 현재 계획 조회
- `approve_plan(id)` — 계획 승인 → 다음 tick에서 실행
- `reject_plan(id, reason)` — 계획 거절 → 다음 tick에서 재생성
- `advance_stage(id, stage)` — 단계 전환
- `record_test_run(id, success, log)` — 테스트 결과 기록
- `get_pipeline_status()` — 전체 현황
- `get_queue_status()` — 큐 상세 (plan, plan_status 포함)
- `get_notify_settings()` / `set_notify_setting(stage, enabled)` — 알림 설정

## LLM Boundary 분해 (spec 작성 시 적용)
- **Level 0 (코드)**: 토큰 0. CRUD, 계산, 파싱, cron.
- **Level 1 (정형 LLM)**: Flash. 템플릿 기반 생성/요약/분류.
- **Level 2 (비정형 LLM)**: Opus. 설계 판단, 디버깅, 복잡한 분석.

## Skill 디렉토리 구조

```
skills/{name}/
  SKILL.md              ← 메인 진입점 (전체 흐름 + 하위 스킬 목차)
  config.json           ← 설정값
  skills/               ← 하위 스킬 (SKILL.md가 커지면 분리)
    {sub-skill}.md
  logs/                 ← testing 결과 누적 (자동 생성)
    test-{N}.md
  decisions/            ← designing 복귀 시 판단 근거
    {N}-{title}.md
```

### 디렉토리 성장 흐름
```
1~2회차: SKILL.md + config.json만 존재
3회차~: 복잡한 로직 분리 → skills/ 하위 스킬 생성
         테스트 누적 → logs/
         설계 변경 → decisions/
```

### 규칙
- **SKILL.md**: 항상 최신 상태 유지. 이전 버전은 git 히스토리에.
- **skills/**: SKILL.md가 길어지면 분리. 처음부터 나누지 않음.
- **logs/test-{N}.md**: testing 결과 자동 기록. stable 판단 근거.
- **decisions/{N}-{title}.md**: designing 복귀 시 "왜 바꿨는지" 기록. 코드 리뷰/디버깅 참고.

## Testing 로그 형식

`logs/test-{N}.md`에 반드시 포함:

### Tool Test Results (Codification Analysis 앞에 위치)

```markdown
## Tool Test Results
| Tool | Test Case | Input | Expected | Actual | Status |
|------|-----------|-------|----------|--------|--------|
| create_trip | 정상 생성 | {"destination": "제주"} | {"trip_id": 1} | {"trip_id": 1} | PASS |
| create_trip | 필수값 누락 | {"destination": ""} | Error | Error: empty destination | PASS |
```

### Codification Analysis (기존)

```markdown
## Codification Analysis
| Step | 설명 | 분류 | 근거 | 대상 파일 |
|------|------|------|------|-----------|
| 1 | 사용자 입력 수집 | codifiable | 정형 입력, 규칙 고정 | service.py |
| 2 | 웹 검색 + 필터링 | hybrid | 검색=코드, 품질판단=LLM | service.py + SKILL.md |

### 요약
- codifiable: N개 (XX%)
- llm_required: N개 (XX%)
- hybrid: N개 (XX%)
```

분류 기준:
- **codifiable**: 정형 입력, 규칙 고정, 코드로 100% 처리 가능 → service.py
- **llm_required**: 판단/생성/분석 등 LLM 필수 → SKILL.md 유지
- **hybrid**: 기본 로직은 코드, 예외/판단은 LLM → service.py + SKILL.md

### JSON 결과 요약 형식

testing 완료 시 마지막에 출력하는 JSON에 `tool_results` 배열 포함:

```json
{
  "success": true,
  "summary": "한 줄 요약",
  "tool_results": [
    {"tool": "create_trip", "tests_passed": 2, "tests_failed": 0},
    {"tool": "search_places", "tests_passed": 1, "tests_failed": 1}
  ],
  "codification": {"codifiable": 3, "llm_required": 1, "hybrid": 2, "codifiable_pct": 50},
  "issues": ["이슈1"],
  "db_tables_created": ["trips", "places"]
}
```

> 기존 `_parse_testing_result`는 `dict.get()` 사용하므로 `tool_results` 추가에 하위 호환 유지.

## Testing 데이터 정책

- testing에서 생성된 DB 데이터는 prototyping 결과로 보존
- coding 완료 후 정리 여부는 상엽 판단
- testing 재실행 시 이전 데이터는 보존 (버전 비교 가능)

## 최종 구조 (skill + code)
```
skills/{name}/
  SKILL.md              ← 에이전트 진입점 (판단/흐름)
  config.json           ← 설정
  skills/               ← 하위 스킬
  logs/                 ← 테스트 기록
  decisions/            ← 설계 판단 기록

whos-life/features/{category}/{name}/
  service.py            ← 모든 로직 (single source of truth, @tool MCP)
  render.py             ← UI

에이전트 → SKILL.md → MCP tool → service.py
사용자   → UI       → render.py → service.py
```
