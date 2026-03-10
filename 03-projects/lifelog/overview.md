---
type: project
importance: 8
created: 2026-03-10
tags: [lifelog, infrastructure, automation, telegram]
status: active
---

# Lifelog

상엽의 모든 활동(업무, 식사, 소비, 약속, 생각 등)을 기록하는 라이프로그 시스템.
자동 수집이 불가능한 것은 Telegram에 한 줄 쓰면 자동 분류 + 저장.
각 도메인(AI Boss, 학습 등)이 필요한 것만 query해서 가져간다.

## 아키텍처

```
상엽 (Telegram lifelog 그룹)
  → telegram_bridge.py (inbound)
  → subprocess: scripts/lifelog/ingest.py "텍스트"  (fire-and-forget)
      → claude -p --model haiku  (분류)
      → lifelog.db INSERT  (raw + 분류 결과)
```

## 주요 파일

| 파일 | 용도 |
|------|------|
| `scripts/lifelog/db.py` | DB 관리 (Entry dataclass, CRUD) |
| `scripts/lifelog/classify.py` | Haiku 분류 (claude CLI) |
| `scripts/lifelog/ingest.py` | CLI 진입점 |
| `storage/lifelog.db` | SQLite (WAL mode) |

## DB 스키마

`entries` 테이블: id, content, source, categories(JSON), tags(JSON), sentiment, metadata(JSON), classified, created_at

- `source`: manual, git, session, factory
- `categories`: Haiku가 자유 태깅 (가이드: work, learning, side-project, food, expense, social, health, thought, life, travel, entertainment, exercise)
- `classified`: 0=미분류, 1=분류완료

## Phase 로드맵

| Phase | 내용 | 상태 |
|-------|------|------|
| 1 | 수동 텍스트 입력 — Telegram → Haiku 분류 → DB | ✅ 완료 |
| 2 | 이미지 분류 — Telegram 사진 → 저장 → Haiku Vision 분류 | 보류 (API key 필요) |
| 3 | 자동 수집 — git commit, 세션 로그, factory 이벤트를 source별로 자동 기록 | 미착수 |
| 4 | 도메인 query — AI Boss, 학습 specialist 등이 lifelog를 조회해서 컨텍스트로 활용 | 미착수 |
| 5 | 대시보드 — whos-life에서 lifelog 시각화 (카테고리별 통계, 타임라인) | 미착수 |

## 환경변수

- `TELEGRAM_LIFELOG_CHAT_ID` — lifelog 전용 Telegram 그룹 chat_id (`.env`)
