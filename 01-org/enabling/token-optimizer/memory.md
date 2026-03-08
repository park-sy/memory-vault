---
type: memory
importance: 7
created: "2026-03-08"
tags: [token-optimizer, memory, monitoring, cost]
---

# Token Optimizer — 누적 학습

## 알려진 모니터링 갭

| # | 갭 | 상태 | 비고 |
|---|---|------|------|
| 1 | ai_boss checkin.py `_call_claude()` | 해소 | `--output-format json` + usage 파싱 적용 |
| 2 | ai_boss responder.py `_call_claude()` | 해소 | 동일 패턴 적용 |
| 3 | intent_parser Level 1 LLM 호출 | 해소 | usage 로깅 추가 |
| 4 | scheduler `token_remaining_pct` 조건 | 해소 | whos-life token-monitor 연동 구현 |
| 5 | pool worker 세션 목적 분류 | 미해소 | JSONL scanner가 세션은 추적하나 역할/목적 태깅 없음 |

## 활성 과제

- **TOK-001**: pool worker 세션 목적 분류 — 워커가 어떤 역할(coder/planner/qa)로 무슨 작업을 했는지 추적 체계 필요

## 교훈

- Claude CLI `--output-format json` 응답 구조: `{"result": "텍스트", "usage": {...}, "total_cost_usd": 0.00xx}`
- `intent_parser.py`에 이미 검증된 JSON 파싱 패턴 있음 (178-183행) — 새 구현 시 참조
- `token_gate.py`의 fallback 패턴: 모니터 불가 시 조건 통과 (보수적 실패 방지)
