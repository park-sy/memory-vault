---
type: knowledge
importance: 8
created: "2026-03-06"
tags: [feature-factory, infrastructure, database, pipeline, architecture]

---

# Feature Factory 아키텍처

> **주의**: 현재 듀얼 DB 구조는 [[04-decisions/005-unify-pipeline-db|ADR-005]]에 의해 통합 예정. 이 문서는 통합 전 현재 상태를 기록한다.

## 개요

Feature Factory는 Feature Pipeline을 자동으로 구동하는 데몬(`cc-factory` tmux 세션).
태스크 생성 → 워커 배정 → 승인 게이트 → 단계 전진을 코드로 처리한다.

## 듀얼 DB 구조 (현재)

```
whos-life/db/productivity.db              memory-vault/storage/feature-factory.db
┌─────────────────────────────┐           ┌─────────────────────────────┐
│ work_queue        (태스크)   │           │ factory_config    (설정)     │
│ feature_dev_log   (개발로그) │           │ worker_assignments(워커배정) │
│ feature_timeline  (타임라인) │           │ pending_approvals (승인대기) │
│ token_snapshots   (토큰)    │           │ factory_events    (이벤트)   │
│ ...기타 whos-life 테이블     │           │ stage_token_log   (토큰추적) │
└─────────────────────────────┘           └─────────────────────────────┘
         ▲                                          ▲
         │ subprocess (whos-life CLI)                │ 직접 접근
         │                                          │
┌────────┴──────────────────────────────────────────┴────┐
│                  Feature Factory 데몬                    │
│  scripts/feature_factory/                               │
│    config.py         — 경로, 상수, get_runtime_int()    │
│    db.py             — feature-factory.db CRUD          │
│    pipeline_manager.py — whos-life CLI subprocess 래퍼  │
│    dispatcher.py     — 메인 디스패치 로직               │
│    notifier.py       — Telegram 알림                    │
│    report.py         — 완료 리포트                      │
└───────────────────────────────────────────────────────────┘
         ▲
         │ 직접 접근 (productivity.db)
┌────────┴────────────────────┐
│  feature_cli.py              │
│  (~/.openclaw/workspace/     │
│   skills/auto-dev/)          │
│  /feature 스킬이 호출        │
└─────────────────────────────┘
```

## 접근 경로 정리

| 누가 | 어떤 DB | 어떻게 |
|------|---------|--------|
| Feature Factory 데몬 → 태스크 조작 | productivity.db | `pipeline_manager.py` → whos-life CLI subprocess |
| Feature Factory 데몬 → 설정/워커/승인 | feature-factory.db | `db.py` 직접 접근 |
| feature_cli.py (`/feature` 스킬) | productivity.db | SQLite 직접 접근 |
| whos-life 대시보드 UI | feature-factory.db | `scripts/feature_factory/db.py` import |

## 설정 시스템

### factory_config (feature-factory.db)

| 키 | 기본값 | 설명 |
|----|--------|------|
| `supervision` | `on` | 워커 plan-mode 강제 |
| `paused` | `false` | 파이프라인 일시정지 |
| `base_pool_size` | `1` | 최소 워커 수 |
| `max_pool_size` | `3` | 최대 워커 수 |
| `idle_timeout` | `600` | 유휴 워커 회수 (초) |
| `stall_timeout` | `900` | 워커 정체 감지 (초) |
| `approval_timeout` | `1800` | 승인 미응답 리마인드 (초) |
| `max_concurrent_features` | `3` | 동시 진행 피처 수 |

### 조회 방법

```python
# Python (Feature Factory 내부)
from scripts.feature_factory.db import get_config, get_all_config
supervision = get_config("supervision")  # "on" or "off"
all_config = get_all_config()            # dict

# Python (런타임 int with fallback)
from scripts.feature_factory.config import get_runtime_int
pool_size = get_runtime_int("base_pool_size", 1)
```

```bash
# CLI (직접 쿼리)
sqlite3 storage/feature-factory.db "SELECT key, value FROM factory_config;"
```

## 데몬 상태 확인

```bash
# 데몬 프로세스 확인
pgrep -af "scheduler.py\|feature_factory"

# tmux 세션 확인
tmux list-sessions | grep factory

# 데몬 시작
tmux new-session -d -s cc-factory -c ~/dev/memory-vault \
  "python3 scripts/feature_factory/scheduler.py"
```

## 파이프라인 흐름 (간략)

```
idea → spec → [승인] → queued → designing → [계획승인] → designing(실행)
  → testing → [승인] → stable → coding → [계획승인] → coding(실행)
  → review → done
```

상세: [[06-skills/feature-pipeline]]

## Related

- [[06-skills/feature-pipeline]] — 파이프라인 단계/흐름 상세
- [[02-knowledge/infrastructure/platform-team-operations]] — 팀 구조, 워커 풀
- [[04-decisions/005-unify-pipeline-db]] — DB 통합 결정
- [[02-knowledge/infrastructure/communication-system]] — Telegram + MsgBus
