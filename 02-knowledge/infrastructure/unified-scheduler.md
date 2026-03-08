---
type: knowledge
importance: 8
created: 2026-03-07
tags: [scheduler, cron, infrastructure, automation]
---

# Unified Scheduler — 통합 스케줄러

## 개요

산재된 스케줄링 포인트(healthcheck, optimizer, archiver 등)를 하나의 스케줄러로 통합 관리.
launchd가 5분마다 scheduler를 깨우고, scheduler가 "지금 실행할 작업이 있는가?"를 판단한다.

```
launchd (매 5분)
  → python3 scripts/scheduler.py tick
    → storage/scheduler.db에서 등록된 작업 조회
    → 각 작업의 schedule + conditions 평가
    → 충족된 작업만 실행
    → 실행 결과 + last_run 기록
```

## 아키텍처

```
┌─────────────────────────────────────────────────┐
│ launchd (com.memory-vault.scheduler)            │
│ RunAtLoad + StartInterval: 300 (5분)            │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│ scripts/scheduler.py tick                       │
│                                                 │
│  1. DB에서 enabled=true 작업 조회               │
│  2. 각 작업의 schedule (cron식) 평가            │
│  3. conditions 평가 (시간, 토큰, 시스템 상태)   │
│  4. 실행 대상 결정                              │
│  5. 실행 (subprocess / tmux / claude CLI)       │
│  6. 결과 기록 (last_run, exit_code, duration)   │
└─────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│ storage/scheduler.db                            │
│                                                 │
│ jobs: id, name, schedule, conditions, command,  │
│       last_run, last_result, enabled, timeout   │
│                                                 │
│ run_log: id, job_id, started_at, finished_at,   │
│          exit_code, output_summary              │
└─────────────────────────────────────────────────┘
```

## DB 스키마

### jobs 테이블

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | TEXT PK | job 고유 ID (예: `healthcheck`, `workflow-optimizer`) |
| name | TEXT | 표시 이름 |
| schedule | TEXT | cron 표현식 (예: `*/1 * * * *`, `0 1-6 * * *`) |
| conditions | TEXT (JSON) | 추가 실행 조건 (아래 참조) |
| command | TEXT | 실행 명령어 |
| command_type | TEXT | `script` / `claude-session` / `tmux-send` |
| last_run | TEXT | ISO 8601 마지막 실행 시각 |
| last_result | TEXT | `success` / `failed` / `skipped` / `running` |
| enabled | INTEGER | 0 또는 1 |
| timeout | INTEGER | 실행 제한 시간 (초) |

### run_log 테이블

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | 자동 증가 |
| job_id | TEXT FK | jobs.id 참조 |
| started_at | TEXT | 실행 시작 시각 |
| finished_at | TEXT | 실행 종료 시각 |
| exit_code | INTEGER | 종료 코드 |
| output_summary | TEXT | 출력 요약 (마지막 500자) |

## Conditions (실행 조건)

JSON으로 저장. 모든 조건을 AND로 평가.

```json
{
  "time_range": "01:00-06:00",
  "token_remaining_pct": 50,
  "no_active_workers": true,
  "day_of_week": [0, 6],
  "require_service": "bridge"
}
```

| 조건 | 타입 | 설명 |
|------|------|------|
| `time_range` | `"HH:MM-HH:MM"` | KST 기준 실행 허용 시간대 |
| `token_remaining_pct` | int | 일일 토큰 잔여 % 이상일 때만 |
| `no_active_workers` | bool | 워커 풀에 활성 작업 없을 때만 |
| `day_of_week` | int[] | 0=월 ~ 6=일, 해당 요일만 |
| `require_service` | string | 특정 데몬이 실행 중일 때만 |
| `min_interval_hours` | int | 마지막 실행 후 최소 N시간 경과 |

## Command Types

| 타입 | 설명 | 예시 |
|------|------|------|
| `script` | 단순 셸/파이썬 스크립트 실행 | `python3 scripts/memory-archiver.py` |
| `claude-session` | Claude Code 세션 스폰 (tmux) | `claude --role workflow-optimizer` |
| `tmux-send` | 기존 tmux 세션에 명령 전달 | pool.sh 경유 |

### claude-session 실행 방식

```bash
# 새 tmux 세션 생성 + claude 실행
tmux new-session -d -s "sched-{job_id}" \
  -c ~/dev/memory-vault \
  "claude --print '최적화 해줘. OPT-001 탐색 시작.'"
```

- 세션 이름: `sched-{job_id}`
- timeout 도달 시 세션 kill
- 실행 완료는 tmux 세션 종료로 감지

## 초기 등록 작업

| id | name | schedule | conditions | command_type | command |
|----|------|----------|------------|-------------|---------|
| `healthcheck` | 서비스 상태 확인 | `*/1 * * * *` | `{}` | script | `bash scripts/healthcheck.sh` |
| `workflow-optimizer` | 워크플로우 최적화 탐색 | `0 2 * * *` | `{"time_range":"01:00-06:00", "token_remaining_pct":50, "min_interval_hours":20}` | claude-session | 최적화 해줘 |
| `memory-archiver` | 기억 아카이브 | `0 4 * * 0` | `{"min_interval_hours":144}` | script | `python3 scripts/memory-archiver.py` |
| `distill-queue` | 증류 큐 처리 | `0 5 * * *` | `{"time_range":"04:00-07:00"}` | script | `python3 scripts/distill-queue.py` |
| `synthesize-decisions` | 의사결정 프로필 합성 | `0 3 * * 1` | `{"min_interval_hours":144}` | script | `python3 scripts/decision-clone.py synthesize` |

## CLI

```bash
# 상태 확인
python3 scripts/scheduler.py status

# 수동 tick (테스트)
python3 scripts/scheduler.py tick

# 작업 등록
python3 scripts/scheduler.py add <id> "<name>" "<schedule>" "<command>" --type script --conditions '{}'

# 작업 활성화/비활성화
python3 scripts/scheduler.py enable <id>
python3 scripts/scheduler.py disable <id>

# 수동 실행 (조건 무시)
python3 scripts/scheduler.py run <id>

# 실행 로그
python3 scripts/scheduler.py log [--job <id>] [--last N]

# launchd 등록/해제
python3 scripts/scheduler.py install
python3 scripts/scheduler.py uninstall
```

## launchd plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.memory-vault.scheduler</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/hiyeop/dev/memory-vault/scripts/scheduler.py</string>
        <string>tick</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/hiyeop/dev/memory-vault/storage/logs/scheduler.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/hiyeop/dev/memory-vault/storage/logs/scheduler.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/hiyeop/dev/memory-vault</string>
</dict>
</plist>
```

## 기존 시스템과의 관계

| 기존 | 변경 |
|------|------|
| `healthcheck.sh` + 전용 launchd plist | scheduler의 job으로 통합. 기존 plist 제거. |
| Feature Factory 자체 스케줄러 | 유지 (데몬 내부 루프). scheduler는 factory 데몬 자체의 생존만 확인. |
| 수동 실행 스크립트들 | scheduler에 등록하되 수동 실행도 여전히 가능 |

## 구현 순서

1. `scripts/scheduler.py` — DB 초기화 + tick + status + add/enable/disable/run/log
2. `storage/scheduler.db` — jobs + run_log 테이블
3. launchd plist 생성 + install/uninstall 서브커맨드
4. 초기 작업 5개 등록 (healthcheck, workflow-optimizer, archiver, distill, synthesize)
5. 기존 healthcheck launchd plist 마이그레이션
6. `daemon.sh`에 scheduler 상태 표시 추가

## 관련 문서

- [[02-knowledge/infrastructure/feature-factory-architecture]] — Feature Factory 데몬
- [[01-org/enabling/workflow-optimizer/role]] — Workflow Optimizer 역할 (자율 탐색 + 리스크 해소)
- [[02-knowledge/infrastructure/token-monitoring]] — 토큰 잔여량 확인
