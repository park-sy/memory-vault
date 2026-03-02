---
type: clone-data
subtype: decision-log
created: 2026-02-22
last_updated: 2026-03-02
total_entries: 17
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
