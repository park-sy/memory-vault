# Ideas Backlog

## 3. 외부 LLM 요청 수신 (Guest Agent)
- 타 LLM(GPT, Gemini 등)이 CLI로 whos-life에 변경 요청을 보내는 구조
- `whos-life feature {name} request-change` 통합 CLI command로 진입점 노출
- 케이스 1(실행), 1.5(확장)만 허용 — 케이스 2(구축)는 차단
- 판단/실행은 내부 developer, 외부는 요청만
- 구체화 필요: tool 파라미터 스펙, 인증/권한, 요청 큐, 거절 응답 포맷
- 참조: [[06-skills/workflow-routing]] "외부 LLM 요청 수신" 섹션
- 등록일: 2026-02-28

## 1. 프로젝트 구조 Anthropic 제안
- 우리 프로젝트 구조를 정기적으로 Anthropic에 제안
- 영어 번역 후 제출
- 등록일: 2026-02-26

## 2. 파이프라인 시각화 + 양방향 편집
- 현재 파이프라인 모니터링 및 강화 에이전트 화면
- 파이프라인을 시각화하고, 시각 도구(UI)에서 변경하면 파이프라인 코드 및 스킬이 자동 변경되도록 구성
- 비주얼 → 코드 양방향 동기화
- 등록일: 2026-02-26
