---
type: knowledge
importance: 7
created: "2026-02-22"
last_accessed: "2026-03-01"
access_count: 1
tags: [auto-dev, scheduler, automation, checkpoint, pattern, distilled]
verified_count: 3
source: "distill from 05-sessions/2026-02-22, 2026-02-23"
---

# Auto-Dev 스케줄러 아키텍처

## 패턴

자동 개발 파이프라인의 스케줄러 설계. 토큰 사용률 기반으로 작업을 자율 실행한다.

## 핵심 결정

| 항목 | 결정 | 근거 |
|------|------|------|
| 스폰 방식 | CLI 기본 (`claude -p`) | ADR-004, 토큰 효율 |
| 체크포인트 | 태스크 단위 저장/재개 | 세션 중단 시 복구 |
| 동시 실행 | default 1, UI 조정 가능 | 토큰 충돌 방지 |
| 토큰 제어 | ≤70% 시작, ≥90% 전부 중단 | Rate Limit 보호 |
| 스케줄러 주기 | 10분 간격 | 응답성 vs 비용 균형 |
| 알림 | Telegram (기능명 + 설명) | 비동기 상엽 확인 |
| 피드백 | Telegram 답장 → 파싱 → 수정 태스크 | 인터랙티브 루프 |
| 큐 등록 | 상엽 승인 필수 | 안전장치 |

## 체크포인트 구조

```python
# checkpoint.py
save(feature_name, stage, context)   # 체크포인트 저장
load(feature_name) -> dict           # 마지막 상태 로드
delete(feature_name)                 # 완료 시 삭제
resume_context(feature_name) -> str  # 재개용 프롬프트 생성
```

## 스케줄러 흐름

```
10분 간격 트리거
  → 토큰 사용률 확인 (token-monitor API)
  ├─ ≥90% → 전부 중단, Telegram 알림
  ├─ ≥70% → 신규 작업 시작 안 함
  └─ <70% → work_queue에서 다음 작업 선택
       → CLI 스폰 (claude -p "..." --system "...")
       → 체크포인트 저장
       → 완료/실패 시 Telegram 알림 + DB 업데이트
```

## 교훈

- "Python 직접 실행 cron" 아님 — cron = 에이전트에게 메시지 보내는 것
- "별도 로직 필요" 판단 전 SKILL.md 확인 — skill이 곧 로직, 에이전트가 읽고 실행
- Flash 모델로 스케줄러 실행 시 Rate Limit 발생 → Opus로 변경 (모델 선택 중요)

## Related

- [[04-decisions/004-cli-over-mcp-for-features]] — CLI 스폰 근거
- [[02-knowledge/patterns/three-tier-execution]] — 3단계 실행 모델
- [[02-knowledge/infrastructure/token-monitoring]] — 토큰 추적 인프라
