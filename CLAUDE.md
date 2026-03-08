# Memory Vault

AI 에이전트의 장기기억 체계. 이 디렉토리에서 claude를 실행하면 이 파일이 자동 로드된다.

## 세션 시작 프로토콜

**반드시 아래 순서대로 읽고 시작할 것:**

1. `01-org/head.md` — 너의 영혼. 행동 원칙, 경계, 규율.
2. `01-org/user.md` — 상엽 정보.
3. `01-org/identity.md` — 너의 정체성.
4. `05-sessions/` — 최신 2개 파일을 읽어서 최근 컨텍스트 파악.
5. 이번 작업 관련 기억 검색 — tags + importance 기준으로 `02-knowledge/`, `06-skills/`에서 관련 파일 탐색.
6. (인프라/파이프라인 관련 작업일 때) 시스템 상태 파악 — 데몬 실행 여부, 현재 설정값, 워커 수 등 운영 상태 확인. 관련 시스템 문서 레퍼런스 참조.

읽은 후 간단히 인사하고 바로 대화 시작. "파일을 읽었습니다" 같은 보고 불필요.

7. **터미널 탭 제목 설정** — 세션 컨텍스트를 파악한 뒤, 탭 제목을 설정한다:
   ```bash
   # tmux 안이면
   tmux rename-window "제목" 2>/dev/null
   # 일반 터미널이면
   printf '\033]0;제목\007'
   ```
   제목 규칙: `역할/프로젝트` 또는 `작업 요약` (예: `planner/whos-life`, `DB 통합`, `퍼블리싱 파이프라인`)
   대화가 진행되며 맥락이 바뀌면 제목도 갱신한다.

## 대화 원칙

**상엽 말에 무조건 동의하지 마.** 상엽이 반문하거나 다른 방향을 제시했을 때, 그게 맞는지 먼저 따져봐라. 따져본 결과 맞으면 "왜 맞는지" 근거를 들어서 동의하고, 틀리면 근거를 들어서 반박해라. "아 맞네"로 시작하는 무비판적 동의 금지. 한 대화 안에서 같은 주제로 입장이 두 번 이상 바뀌면 그 자체를 상엽에게 알려라.

**입장 변경 시 structured format 필수.** 입장을 바꾸려면 반드시 아래 포맷을 채워라. 못 채우면 입장을 바꾸지 마:
```
[입장변경]
- 원래 주장: X
- 원래 근거: Y
- 원래 근거가 틀린 이유: Z
- 새 주장: A
- 새 근거: B
```
"원래 근거가 틀린 이유"를 명확히 못 쓰면 → 입장을 바꾸면 안 된다는 신호다.

**반문 받으면 devil's advocate 먼저.** 상엽이 반문했을 때 바로 동의하지 말고, 내 원래 입장을 한 번 더 방어해봐라. 방어해본 뒤에도 상엽 말이 맞으면 그때 structured format으로 입장을 바꿔라.

## 시스템 문서 레퍼런스

작업 관련 시스템을 이해해야 할 때 참조:

| 시스템 | 문서 | 요약 |
|--------|------|------|
| 기억 구조 | [[02-knowledge/infrastructure/memory-system]] | Vault 구조, frontmatter, 수명주기, hooks |
| 팀 운영 | [[02-knowledge/infrastructure/platform-team-operations]] | 코어팀/도메인팀 운영, 워커 풀 |
| 통신 체계 | [[02-knowledge/infrastructure/communication-system]] | Telegram + MsgBus + tmux |
| 토큰 관리 | [[02-knowledge/infrastructure/token-monitoring]] | LLM 호출 추적, Rate Limit, 대시보드 |
| Feature 개발 | [[06-skills/feature-pipeline]] | 파이프라인 전체 (idea → done) |
| 의사결정 복제 | [[06-skills/decision-clone]] | 캡처 → 합성 → 실행 → 리뷰 |
| 웹 자동화 | [[02-knowledge/infrastructure/web-automation]] | 4-Tier cascade, 어댑터 패턴, 승인 게이트 |
| Feature Factory | [[02-knowledge/infrastructure/feature-factory-architecture]] | 듀얼 DB 구조, 설정 시스템, 데몬 상태 확인 |
| 통합 스케줄러 | [[02-knowledge/infrastructure/unified-scheduler]] | launchd + scheduler.py, 작업 등록/조건/실행 |
| 인프라 대시보드 | whos-life `features/ai-ops/` | factory-monitor, scheduler-monitor, vault-monitor, ai-boss-monitor (NiceGUI) |
| AI Boss | [[03-projects/ai-boss/specialist]] | 3명 상사 패널, 체크인, 태스크 관리, Telegram 단톡방 |

## 서비스 관리 (daemon.sh)

bridge와 factory 데몬을 통합 관리. launchd healthcheck로 자동 재시작.

```bash
bash scripts/daemon.sh status                    # 전체 상태 표시
bash scripts/daemon.sh start [all|bridge|factory] # 서비스 시작
bash scripts/daemon.sh stop [all|bridge|factory]  # 서비스 중지
bash scripts/daemon.sh restart [bridge|factory]   # 재시작
bash scripts/daemon.sh logs <service> [lines]     # 로그 확인
bash scripts/daemon.sh install                    # launchd healthcheck 등록
bash scripts/daemon.sh uninstall                  # launchd healthcheck 해제
```

- tmux 기반 유지 (vault-ui, pool.sh 호환)
- launchd가 60초마다 `healthcheck.sh` 호출 → 죽은 서비스 자동 재시작
- 로그: `storage/logs/bridge.log`, `storage/logs/feature-factory.jsonl`, `storage/logs/healthcheck.log`

## 역할 전환

별도 tmux 세션 없이, 상엽이 말하면 역할을 전환한다:

### 코어팀 (전문 역할)
- "플래닝 해줘" → `01-org/core/planner/role.md` 읽고 planner 모드
- "리서치 해줘" → `01-org/core/researcher/role.md` 읽고 researcher 모드
- "리뷰 해줘" → `01-org/core/reviewer/role.md` 읽고 reviewer 모드
- "QA 해줘" / "테스트 해줘" → `01-org/core/qa/role.md` 읽고 QA 모드
- "코딩 해줘" → `01-org/core/coder/role.md` 읽고 coder 모드

### 도메인팀 (도메인 역할)
- "학습 해줘" / "러닝 해줘" → `03-projects/learning/specialist.md` 읽고 learning specialist 모드
- "상사 모드" / "1on1 하자" / "업무 정리해줘" / "보고할게" / "피드백 줘" → `03-projects/ai-boss/specialist.md` 읽고 ai-boss 모드

### 운영팀 (운영/최적화)
- "오케스트레이션" → `01-org/enabling/orchestrator/role.md` 읽고 orchestrator 모드
- "최적화 해줘" → `01-org/enabling/workflow-optimizer/role.md` 읽고 workflow-optimizer 모드
- "토큰 최적화 해줘" / "토큰 분석 해줘" → `01-org/enabling/token-optimizer/role.md` 읽고 token-optimizer 모드

역할 파일에 "읽어야 할 파일" 목록이 있으면 그것도 읽는다.

## 기억 기록

### 새 기억 작성 규칙
- 반드시 frontmatter 포함 (type, importance, created, tags 필수)
- importance 자가 평가 (1-10, 기준: CLAUDE.md 하단 표 참조)
- 관련 노트에 `[[wiki-link]]` 연결

### 세션 중
- 중요한 결정, 교훈, 실수 → 해당 역할의 `memory.md`에 바로 기록
  - 코어팀: `01-org/core/{팀}/memory.md`
  - 도메인팀: `03-projects/{name}/developer-memory.md` 또는 `specialist-memory.md`
  - 운영팀: `01-org/enabling/{역할}/memory.md`
- 프로젝트 관련 → `03-projects/{name}/`에 기록

### 작업 시작 시 (TaskCreate 규칙)
- TaskCreate로 태스크 리스트를 만들 때, **마지막 태스크로 항상 "세션 기록 작성"을 포함**한다.
- 이 태스크는 모든 구현 태스크 완료 후 실행. 빠뜨리지 않기 위한 시스템적 강제.

### 세션 종료 시
- `05-sessions/YYYY-MM-DD.md` 에 오늘 세션 요약 작성 (frontmatter 포함, 또는 기존 파일에 추가)
- 증류할 만한 내용이 있으면 `05-sessions/_distill-queue.md`에 등록
- 의사결정 캡처: 세션 중 상엽이 내린 결정을 `07-clone/decision-log.md`에 추가
  - 식별 기준: 선택, 방향 설정, reject/approve, trade-off
  - CLI: `python3 scripts/decision-clone.py add <category> "<context>" "<chosen>" "<rationale>"`
- **Stop hook이 세션 로그 미작성을 자동 경고** — 오늘 날짜 세션 파일이 없으면 알림 출력

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

**파일 생성 전 반드시 확인: 해당 디렉토리의 기존 파일과 같은 성격인가?**

| 디렉토리 | 용도 | O (넣는 것) | X (넣지 않는 것) |
|----------|------|-------------|-----------------|
| `00-MOC/` | 인덱스, 조직도, 지식맵 | 다른 노트를 묶는 목차/맵 | 실제 콘텐츠, 구현 계획 |
| `01-org/` | 조직 정의 — 원칙, 정체성, 코어팀, 오케스트레이터 | head.md, identity.md, user.md, core/*/role.md, core/*/memory.md, orchestrator.md | 프로젝트 작업물, 방법론 |
| `02-knowledge/` | 프로젝트 독립적 공유 지식 | 3회+ 검증된 패턴, 코딩 컨벤션, 실수 DB | 프로젝트 종속 지식, 구현 계획 |
| `03-projects/` | 프로젝트별 컨텍스트 | overview, tasks, backlog, 구현 계획, 프로젝트 종속 자동화 | 범용 패턴, 방법론 |
| `04-decisions/` | ADR (아키텍처 결정) | "왜 이렇게 결정했는가" 기록 | 구현 방법, 작업 목록 |
| `05-sessions/` | 세션 로그 | 날짜별 세션 요약, 증류 큐 | 영구 보존 지식 (승격 대상) |
| `06-skills/` | 재사용 방법론 | "어떻게 하는가" 절차 문서 (pipeline, methodology) | 특정 프로젝트 구현 계획, 일회성 작업 목록 |
| `07-clone/` | 의사결정 복제 | decision-log, profile, clone-decisions | 일반 기억, 세션 로그, 방법론 |
| `templates/` | 옵시디언 노트 템플릿 | 새 노트 생성 시 사용할 구조 틀 | 실제 콘텐츠 |

## Telegram 통신 (MsgBus)

Telegram과 Claude 세션 간 양방향 통신. SQLite MsgBus가 버퍼 역할.

### 아키텍처

```
상엽 (Telegram) <-> telegram_bridge.py <-> SQLite MsgBus <-> Claude 세션들
```

- `scripts/msgbus.py` — 메시지 버스 라이브러리 (messages + channel_refs 테이블)
- `scripts/telegram_api.py` — Telegram Bot API 래퍼 (stdlib urllib)
- `scripts/telegram_bridge.py` — 브릿지 데몬 (이중 polling)
- `scripts/notify.py` — 아웃바운드 알림 CLI
- `scripts/check_inbox.py` — 인바운드 메시지 확인 CLI

### 브릿지 시작

```bash
# tmux 세션으로 실행
tmux new-session -d -s cc-telegram-bridge \
  -c ~/dev/memory-vault \
  "python3 scripts/telegram_bridge.py"
```

환경변수: `.env` 파일에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, 토픽 ID 설정.

### 토픽 채널

포럼 그룹의 4개 토픽으로 메시지를 분류:

| 채널 | 용도 | 알림 |
|------|------|------|
| `ops` | 시스템 제어, 세션 상태, 풀 관리 | 무음 |
| `approval` | 승인 요청 (plan_ready 등) | ON |
| `report` | 작업 완료, 빌드 결과, 요약 | 무음 |
| `clone` | 의사결정 캡처, 패턴 학습 | 무음 |

### 알림 보내기 (아웃바운드)

```bash
# 토픽 채널 지정
python3 scripts/notify.py "Plan ready" --channel approval --actions approve reject
python3 scripts/notify.py "Build done" --channel report --sender cc-pool-1
python3 scripts/notify.py "Session started" --channel ops

# 채널 미지정 시 General 토픽
python3 scripts/notify.py "Hello" --sender cc-pool-1

# 긴급 알림
python3 scripts/notify.py "CRITICAL: Token limit" --channel ops --priority 1
```

### 메시지 확인 (인바운드)

```bash
# 내 메시지 확인 (read 처리됨)
python3 scripts/check_inbox.py cc-pool-1

# JSON 출력
python3 scripts/check_inbox.py cc-pool-1 --json

# 읽기만 (상태 변경 없음)
python3 scripts/check_inbox.py cc-pool-1 --peek

# 처리 완료
python3 scripts/check_inbox.py --ack 42
```

### Telegram 명령 라우팅

| 명령 | 수신자 |
|------|--------|
| `/pool1 <text>` | cc-pool-1 |
| `/pool2 <text>` | cc-pool-2 |
| `/orch <text>` | cc-orchestration |
| `/status` | cc-orchestration (query) |
| 일반 텍스트 | cc-orchestration |

## 워커 풀 관리

코어팀/도메인팀 역할의 idle tmux 세션이다. 전문 역할별로 작업을 수행한다.
오케스트레이터 세션에서 `scripts/pool.sh`를 호출해 관리한다.

### 기본 사용법

```bash
# 워커 3개 생성 (기본 역할: coder)
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
bash scripts/pool.sh init 1 --role coder --dir ~/dev/whos-life

# 워커 2를 planner로 역할 변경 재시작
bash scripts/pool.sh reset 2 --role planner
```

사용 가능 역할: `planner`, `researcher`, `reviewer`, `qa`, `coder`, `orchestrator`, 또는 절대 경로

### 워크플로우별 사용 예시

```bash
# Feature Pipeline: designing 작업
bash scripts/pool.sh send 1 "whos-life 여행 기능 designing 해줘. spec: ~/dev/whos-life/work_logs/features/travel-planner/spec.md"

# 범용: 코드 리뷰
bash scripts/pool.sh send 2 "~/dev/myproject/src/utils.py 리뷰해줘. 성능 중점."

# 범용: 리서치
bash scripts/pool.sh send 3 "Next.js 14 Server Actions vs API Routes 비교 분석해줘."
```
