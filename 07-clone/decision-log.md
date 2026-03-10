---
type: clone-data
subtype: decision-log
created: 2026-02-22
last_updated: 2026-03-11
total_entries: 40
tags: [decision-clone, decisions]
---

# Decision Log

### D-001 | architecture | 2026-02-22
- **context**: 프레임워크 비교 후 whos-life UI 프레임워크 선택
- **options**: NiceGUI, FastAPI+React, Reflex, FastHTML, Streamlit, Gradio
- **chosen**: NiceGUI 유지
- **rationale**: 에이전트 편의성 9/10, 같은 프로세스 MCP+UI
- **confidence**: high
- **outcome**: pending
- **tags**: framework, nicegui, whos-life

### D-002 | architecture | 2026-02-22
- **context**: 멀티 에이전트에서 코봉을 별도 에이전트로 분리할지
- **options**: 별도 에이전트, sub-agent, 단일 에이전트
- **chosen**: sub-agent 방식
- **rationale**: 같은 모델/머신이면 분리 불필요. 모델/권한 다를 때만 분리.
- **confidence**: high
- **outcome**: pending
- **tags**: multi-agent, agent-architecture

### D-003 | architecture | 2026-02-22
- **context**: LLM 실행 범위 결정
- **options**: 모든 작업 LLM, 판단만 LLM + 실행은 코드, 코드 전부
- **chosen**: LLM은 판단만, 실행은 코드
- **rationale**: 토큰 절약 + 안정성. Level 0(코드)/1(정형 LLM)/2(비정형 LLM)
- **confidence**: high
- **outcome**: pending
- **tags**: llm-boundary, 3-tier

### D-004 | architecture | 2026-02-22
- **context**: 에이전트 분리 기준 정의
- **options**: 기능별 분리, 모델/권한별 분리, 단일 에이전트
- **chosen**: 모델/권한이 다를 때만 분리
- **rationale**: 같은 모델/머신이면 sub-agent로 충분
- **confidence**: high
- **outcome**: pending
- **tags**: multi-agent, agent-architecture

### D-005 | workflow | 2026-02-22
- **context**: Skill과 Code의 관계 정의
- **options**: skill만 사용, code만 사용, skill-first
- **chosen**: Skill-first (skill로 검증 → 반복 패턴만 code로)
- **rationale**: skill = 프로토타입/설계서, code = 최적화된 실행. 성숙할수록 code 비중 증가.
- **confidence**: high
- **outcome**: pending
- **tags**: skill-first, pipeline

### D-006 | risk-tolerance | 2026-02-22
- **context**: git push 자동화 수준
- **options**: 자동 push, 반자동, 수동만
- **chosen**: 반드시 상엽 확인 후 push
- **rationale**: 코드 변경은 리뷰 필수. 자동화 범위에 push 제외.
- **confidence**: high
- **outcome**: pending
- **tags**: git, safety

### D-007 | tooling | 2026-02-22
- **context**: OpenClaw config 수정 방법
- **options**: 직접 수정, CLI 사용
- **chosen**: CLI 사용 원칙
- **rationale**: 직접 수정 시 토큰 공백/중복 발생. CLI가 안전.
- **confidence**: medium
- **outcome**: pending
- **tags**: openclaw, config

### D-008 | architecture | 2026-02-23
- **context**: 코봉(coder agent) 유지 여부
- **options**: 유지, 제거
- **chosen**: 제거 (sub-agent로 대체)
- **rationale**: 같은 모델/머신이면 별도 에이전트 불필요
- **confidence**: high
- **outcome**: pending
- **tags**: multi-agent, agent-architecture

### D-009 | tooling | 2026-02-23
- **context**: cron 스케줄러 모델 선택
- **options**: Flash, Opus
- **chosen**: Opus
- **rationale**: Flash rate limit 문제 발생. Opus가 안정적.
- **confidence**: medium
- **outcome**: pending
- **tags**: cron, model-selection

### D-010 | workflow | 2026-02-25
- **context**: Feature pipeline에 계획 승인 게이트 도입 여부
- **options**: 승인 없이 자동, Plan Mode(승인 게이트)
- **chosen**: Plan Mode 도입
- **rationale**: designing/coding 진입 시 plan 생성 → 사용자 승인 → 실행. 4개 승인 게이트.
- **confidence**: high
- **outcome**: pending
- **tags**: plan-mode, pipeline

### D-011 | trade-offs | 2026-02-25
- **context**: 설계 원칙 우선순위
- **options**: 기능 완성도 우선, 사용자 입력 우선, 기술 우수성 우선
- **chosen**: 사용자 입력 우선 + 점진적 보강
- **rationale**: 초안 먼저 내고 보강하는 방식. reject 히스토리 자동 누적.
- **confidence**: high
- **outcome**: pending
- **tags**: design-principles, trade-offs

### D-012 | architecture | 2026-02-25
- **context**: Feature pipeline 세션 구조
- **options**: 단일 세션, planner+worker 분리, per-feature 세션
- **chosen**: 3-Tier (planner 1개 + worker N개)
- **rationale**: planner가 spec 전담, worker가 구현. scheduler가 배정.
- **confidence**: high
- **outcome**: pending
- **tags**: 3-tier, pipeline, multi-session

### D-013 | architecture | 2026-02-28
- **context**: AI 에이전트 조직 구조 선택
- **options**: Hub-and-Spoke, Platform Team (Team Topologies)
- **chosen**: Platform Team 구조 채택
- **rationale**: 코어 전문팀 + 가벼운 도메인팀 + 자유 소통. AI 고유 이점으로 단점 전부 해소.
- **confidence**: high
- **outcome**: pending
- **tags**: team-topologies, organization, platform-team

### D-014 | communication | 2026-02-28
- **context**: 팀 간 커뮤니케이션 구조
- **options**: Hub-and-Spoke(오케스트레이터 경유), 자유 소통(direct)
- **chosen**: 자유 소통 (Collaboration Mode)
- **rationale**: 옵시디언 wiki-link로 지식 공유, 직접 참조 가능. 병목 제거.
- **confidence**: high
- **outcome**: pending
- **tags**: communication, team-topologies

### D-015 | communication | 2026-02-28
- **context**: 조직 구조 명칭 선택
- **options**: 헥사고날 아키텍처, Platform Team (Team Topologies)
- **chosen**: Platform Team (Team Topologies)
- **rationale**: 헥사고날은 소프트웨어 Ports & Adapters 패턴 → 부적합. Team Topologies가 정확.
- **confidence**: high
- **outcome**: pending
- **tags**: naming, team-topologies

### D-016 | trade-offs | 2026-02-28
- **context**: Platform Team 단점 해소 전략
- **options**: 단점 수용, 구조 변경, AI 이점 활용
- **chosen**: AI 고유 이점으로 전부 해소
- **rationale**: 세션 복제, 컨텍스트 스위칭 0, 메모리 공유, 에고 없음, 롤백 가능.
- **confidence**: high
- **outcome**: pending
- **tags**: ai-advantage, team-topologies

### D-017 | tooling | 2026-03-02
- **context**: Feature Factory e2e dogfooding
- **options**: -
- **chosen**: supervision=OFF, MsgBus direct approvals, manual re-send for timing bug
- **rationale**: 첫 실행: supervision=OFF 자율 실행, Telegram 없이 MsgBus CLI로 승인. 워커 startup 3초→15초 수정 필요 발견
- **confidence**: medium
- **outcome**: pending
- **tags**: tooling

### D-018 | uncategorized | 2026-03-03
- **context**: 내가 이해한 방향이 맞아? 아니면 다른 의미야?
- **options**: 맞아, 그 방향, 좀 다른 뜻이야
- **chosen**: 좀 다른 의미이긴한데, 그냥 코드를 만들었을 때 사용자가 더 많은 정보를 획득할 수 있고 그 기능에 대한 세밀한 조절이 가능한 코드들이 만들어져야한다는거야. 다시 말해봐.
- **rationale**: 좀 다른 의미이긴한데, 그냥 코드를 만들었을 때 사용자가 더 많은 정보를 획득할 수 있고 그 기능에 대한 세밀한 조절이 가능한 코드들이 만들어져야한다는거야. 다시 말해봐.
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured, exploratory

### D-019 | uncategorized | 2026-03-03
- **context**: 기존 frontmatter에 있는 access_count/last_accessed 필드를 어떻게 처리할까요?
- **options**: DB로 이관 + frontmatter에서 제거, DB로 이관 + frontmatter 유지 (Recommended), 기존 데이터 버리고 새로 시작
- **chosen**: DB로 이관 + frontmatter에서 제거
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-020 | uncategorized | 2026-03-03
- **context**: 파이프라인 각 단계에 팀을 매핑하려면, designing 단계의 담당을 먼저 결정해야 해. SKILL.md(7섹션 기술 명세) 작성은 누가 해야 해?
- **options**: Planner, Coder, 새 역할 (Designer)
- **chosen**: 뭐가 더 맞을 거 같아?
- **rationale**: 뭐가 더 맞을 거 같아?
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured, exploratory

### D-021 | uncategorized | 2026-03-03
- **context**: coding 이후에 코드 검증 단계를 추가할까? 추가하면 파이프라인이 `coding → review → done`이 되고, 각 코어팀이 정확히 한 단계씩 담당하게 돼.
- **options**: review 단계 추가 (Recommended), QA가 코드도 검증, 현행 유지
- **chosen**: review 단계 추가 (Recommended)
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-022 | uncategorized | 2026-03-03
- **context**: 어떤 방식으로 갈까?
- **options**: JSONL 스캔만 (Recommended), 이중 모드 (원래 계획), JSONL + 비용 후계산
- **chosen**: JSONL 스캔만 (Recommended)
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-023 | uncategorized | 2026-03-03
- **context**: unique_sessions를 제거하고 핵심 지표를 어떻게 구성할까?
- **options**: reference_count만 (Recommended), reference_count + access_log, 다른 지표 제안
- **chosen**: 아니 팀별 hot/cold 판단으로 바꿔야하는건 아닐까? 뭐가 중요한거 같아? 너 생각엔
- **rationale**: 아니 팀별 hot/cold 판단으로 바꿔야하는건 아닐까? 뭐가 중요한거 같아? 너 생각엔
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured, exploratory

### D-024 | uncategorized | 2026-03-06
- **context**: 시드 학습 방법 4개(spaced-repetition, active-recall, feynman-technique, interleaving)로 시작하는데, 추가로 넣고 싶은 방법이 있어?
- **options**: 이 4개면 충분, 몇 개 더 추가
- **chosen**: 이 네개가 뭐야? 설명해줘.
- **rationale**: 이 네개가 뭐야? 설명해줘.
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured, exploratory

### D-025 | uncategorized | 2026-03-06
- **context**: 이 4개로 시작할까, 추가할 방법이 있어?
- **options**: 이 4개로 시작 (Recommended), 더 추가하고 싶어
- **chosen**: 오호 예를들어 '주식'이라는 주제에 대해 학습한다면 저 네개는 어떤식으로 하는거야?
- **rationale**: 오호 예를들어 '주식'이라는 주제에 대해 학습한다면 저 네개는 어떤식으로 하는거야?
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured, exploratory

### D-026 | uncategorized | 2026-03-06
- **context**: 학습 도메인팀 플랜 진행할까?
- **options**: 진행 (Recommended), 시드 방법 추가, 수정 요청
- **chosen**: 음 이런 개념적인거 말고, 예를 들어 주식 시장의 움직임이나, 현재 거시적인 정치적 경제적 상황을 잘읽게 만들어야 한다면?
- **rationale**: 음 이런 개념적인거 말고, 예를 들어 주식 시장의 움직임이나, 현재 거시적인 정치적 경제적 상황을 잘읽게 만들어야 한다면?
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured, exploratory

### D-027 | uncategorized | 2026-03-06
- **context**: 시드 방법을 이렇게 확장해서 진행할까?
- **options**: 3계층 8개로 시작 (Recommended), 판단력 중심으로, 다른 생각 있음
- **chosen**: 오호 이런 방법론도 저장해봐. 그리고 지금의 내가 생각하는 효율적인 방법은 '비유'야. 그리고 또 그 비유는 그 사람의 경험에서 비유하는게 제일 효과적이라고 생각해. 그래서 기존에는 사람마다 무슨 경험을 가지고, 어떤 일을하고 하는것과 상관없이 일반적인 경우로 비유를 했잖아. 그런데 이제는 ai가 나의 경험을 알고 잇다면 그거에 맞춰서 비유를 해줘서 이해도가 올라가고, 그로부터 더 경험을 많이 가지고 있고 ai도 그 컨텍스트를 충분히 이해하고 있기 때문에 계속해서 선순환 구조를 가지고 간다고 생각해. 내 생각이 어때?
- **rationale**: 오호 이런 방법론도 저장해봐. 그리고 지금의 내가 생각하는 효율적인 방법은 '비유'야. 그리고 또 그 비유는 그 사람의 경험에서 비유하는게 제일 효과적이라고 생각해. 그래서 기존에는 사람마다 무슨 경험을 가지고, 어떤 일을하고 하는것과 상관없이 일반적인 경우로 비유를 했잖아. 그런데 이제는 ai가 나의 경험을 알고 잇다면 그거에 맞춰서 비유를 해줘서 이해도가 올라가고, 그로부터 더 경험을 많이 가지고 있고 ai도 그 컨텍스트를 충분히 이해하고 있기 때문에 계속해서 선순환 구조를 가지고 간다고 생각해. 내 생각이 어때?
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured, exploratory

### D-028 | uncategorized | 2026-03-06
- **context**: 세션 컨텍스트 기반 feature 생성을 어떤 방식으로 하고 싶어? 예: 대화 중 논의한 내용을 자동 요약해서 title+description을 만들어주는 건지, 아니면 세션 로그 파일(05-sessions/)을 읽어서 추출하는 건지?
- **options**: 대화 컨텍스트 자동 요약, 세션 로그 파일 분석, 둘 다
- **chosen**: /feature-session으로 트리거 대고 아무것도 안적으면 1,2 둘다 해당 명령어 이후에 내가 내용 적으면 그거 위주로.
- **rationale**: /feature-session으로 트리거 대고 아무것도 안적으면 1,2 둘다 해당 명령어 이후에 내가 내용 적으면 그거 위주로.
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-029 | uncategorized | 2026-03-07
- **context**: daemon.sh에 infra-dashboard도 등록해서 bridge/factory처럼 자동 관리할까?
- **options**: 등록 (Recommended), 수동 실행만
- **chosen**: 등록 (Recommended)
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-030 | uncategorized | 2026-03-07
- **context**: Phase 1 MVP 범위 — 어디까지 먼저 만들까?
- **options**: Overview + Scheduler (Recommended), Overview + Memory + Org, 전부 한번에
- **chosen**: 전부 한번에
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-031 | uncategorized | 2026-03-07
- **context**: token-monitor와 token-dashboard는 rate limit 조회(같은 API), OAuth 토큰 읽기, 모델명 포맷팅, 리셋 시간 포맷팅이 중복이다. token-monitor가 이미 멀티 프로바이더 rate limit + 작업 큐를 가지고 있고, token-dashboard는 JSONL 스캔 → 일별 차트 + 프로젝트별 분석이 핵심. 어떻게 할까?
- **options**: token-monitor에 통합 (Recommended), 중복 함수만 _shared.py로, token-dashboard에 통합
- **chosen**: token-monitor에 통합 (Recommended)
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-032 | uncategorized | 2026-03-08
- **context**: 상사 페르소나 3명(진수/미영/정훈)의 성격과 관점이 원하는 방향과 맞아?
- **options**: 이대로 좋아, 인원/성격 수정, 완전히 다시
- **chosen**: 다른 레퍼런스를 좀 더 찾아봐.
- **rationale**: 다른 레퍼런스를 좀 더 찾아봐.
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-033 | uncategorized | 2026-03-08
- **context**: 체크인 시간대와 빈도는 어떻게 할까? 설계안: 평일 아침 09:00 + 저녁 18:00 + 주간 금요일 17:00
- **options**: 설계안 그대로, 아침만, 직접 설정할게
- **chosen**: 이거 설정할 수 있는 화면도 만들어줘.
- **rationale**: 이거 설정할 수 있는 화면도 만들어줘.
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-034 | uncategorized | 2026-03-08
- **context**: Telegram 전용 그룹은 토픽 없이 단순 그룹 채팅으로 시작하는 게 좋을까? (토픽으로 나누면 단톡방 느낌이 사라짐)
- **options**: 단순 그룹 채팅 (추천), 토픽 분리, 포럼 그룹 재활용
- **chosen**: 단순 그룹 채팅 (추천)
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-035 | uncategorized | 2026-03-08
- **context**: 상사의 LLM 호출에 어떤 모델을 쓸까?
- **options**: Haiku 4.5 (추천), Sonnet 4.6, 상황별 혼합
- **chosen**: Haiku 4.5 (추천)
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-036 | uncategorized | 2026-03-08
- **context**: 상사 페르소나 구성을 어떻게 할까?
- **options**: 수정안 (추천), 원래 설계, 직접 구성할게
- **chosen**: 수정안 (추천)
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-037 | uncategorized | 2026-03-08
- **context**: 모바일에서 Claude app 링크로 뭘 하고 싶은 거야? 워커 세션에 직접 붙어서 수정 지시를 내리는 건 tmux (데스크탑)에서만 가능한데, 모바일에서의 워크플로우가 뭐야?
- **options**: Telegram에서 텍스트로 피드백, Claude 앱에서 새 대화, 둘 다
- **chosen**: 지금 remote-control 되잖아. 그걸로 tmux 세션에 모바일로 붙는거.
- **rationale**: 지금 remote-control 되잖아. 그걸로 tmux 세션에 모바일로 붙는거.
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-038 | uncategorized | 2026-03-08
- **context**: 모바일에서 워커 세션에 접속하는 방법을 어떻게 제공할까요?
- **options**: tmux-attach:// + SSH 커맨드, tmux 커맨드만, remote-control URL 자동 생성
- **chosen**: 있을텐데, 몇가지 보내봐 테스트하게.
- **rationale**: 있을텐데, 몇가지 보내봐 테스트하게.
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-039 | uncategorized | 2026-03-11
- **context**: 오늘 체크인이 힘들었던 건 어디서 한 거야? (경로에 따라 수정 위치가 달라짐)
- **options**: 텔레그램 자동 체크인, 상사 모드 (이 세션), 둘 다
- **chosen**: 텔레그램 자동 체크인
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured

### D-040 | uncategorized | 2026-03-11
- **context**: 질문 자체를 없애는 게 아니라, 어떤 톤을 원해?
- **options**: 질문 1개 이하, 질문 허용, 핵심만, 체크인은 일방향
- **chosen**: 질문 허용, 핵심만
- **rationale**: auto-captured
- **confidence**: medium
- **outcome**: pending
- **tags**: auto-captured
