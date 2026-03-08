---
type: role-memory
importance: 8
created: 2026-02-28
tags: [whos-life, developer, domain, lessons]

---

# whos-life Developer Memory
마지막 업데이트: 2026-03-01

## 교훈
- `claude -p --output-format json` 결과에 `result`(텍스트) + `usage`(토큰) + `total_cost_usd`(비용) 전부 포함됨
- `--no-session-persistence` 플래그로 JSONL 세션 파일 생성 방지 가능
- usage 필드의 캐시 키: `cache_read_input_tokens`, `cache_creation_input_tokens` (input 포함 주의)
- `modelUsage` dict의 첫 번째 키가 실제 사용된 모델명
- cost_usd는 DB에 String으로 저장 (float 정밀도 손실 방지)

## 패턴
- `LLMTracker` 패턴: Runner를 직접 호출하지 않고 Tracker를 통해 호출하면 자동으로 DB 기록
- DB 마이그레이션: `create_all()` 후 `ALTER TABLE ... ADD COLUMN` (try/except로 멱등성 보장)
- 세션 lifecycle: core(장기) vs ephemeral(1회성) 구분으로 정리 자동화 가능

## 실수/회피
- `LLMRequestManager`는 생성만 되고 실제 사용처 없음 (orphaned) — 향후 정리 대상
