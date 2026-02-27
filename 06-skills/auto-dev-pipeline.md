# Auto-Dev Pipeline Skill

Feature 개발 파이프라인 제어. 3-Tier 세션 구조 오케스트레이션.

## 3-Tier 세션 구조

| Tier | 세션 | 역할 |
|------|------|------|
| 오케스트레이션 | OpenClaw | 태스크 관리/배정, Yap 메시지 라우팅 |
| 계획 전문가 | cc-planner (1개) | idea → spec 전담 |
| Worker | cc-pool-{1..N} | designing → coding → done |

- planner는 spec만 작성. 구현하지 않음.
- spec 승인 후 queued → worker가 designing부터 시작.

## When to Use

USE this skill when:
- 사용자가 feature 개발/추가를 요청할 때
- 세션 풀 상태 확인, 승인, 일시정지 등 파이프라인 제어
- "pool", "세션", "파이프라인", "승인", "태스크", "planner", "spec" 관련 요청

## Commands

모든 명령은 `exec` 도구로 실행:

```bash
# 풀 상태 확인
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py status

# ── feature → planner ──
# 새 feature 등록 (idea 생성 + planner 할당 + 코봉 알림)
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py feature "여행 기능" "일본 5일 여행 계획"

# planner spec 승인 (spec_ready → queued, worker 배정 대기)
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py approve cc-planner

# planner spec 수정 요청
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py reject cc-planner "범위 좁혀줘"

# ── worker 제어 ──
# worker 세션 승인 (plan_ready → 구현 시작)
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py approve pool-3

# worker 세션 승인 + 커스텀 메시지
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py approve pool-3 "승인. 캐시 TTL은 5분으로."

# 수정 요청 (plan_ready → 피드백과 함께 재설계)
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py reject pool-3 "캐싱 대신 CDN 사용해"

# 태스크 추가 (직접 queued에 넣기, planner 안 거침)
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py add "여행 기능 추가" "일본 5일 여행 계획 세우기"

# 파이프라인 일시정지/재개
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py pause
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/orchestration_commands.py resume
```

## 스케줄러 (cron 30분)

```bash
python3 /Users/hiyeop/.openclaw/workspace/skills/auto-dev/scheduler.py
```

## 세션 풀 관리

```bash
# 초기화 (세션 N개 생성)
bash /Users/hiyeop/.openclaw/workspace/skills/auto-dev/session_init.sh init-pool 5

# 상태 확인
bash /Users/hiyeop/.openclaw/workspace/skills/auto-dev/session_init.sh status

# 전체 종료
bash /Users/hiyeop/.openclaw/workspace/skills/auto-dev/session_init.sh teardown

# 단일 세션 재시작
bash /Users/hiyeop/.openclaw/workspace/skills/auto-dev/session_init.sh reset 3
```

## 사용자 메시지 → 명령 매핑

| 사용자 메시지 | 실행할 명령 |
|---|---|
| "상태 어때?" / "풀 상태" | `status` |
| "여행 기능 만들어줘" / "XXX 기능 추가해" | `feature "여행 기능"` |
| "planner 승인" / "spec 승인해" | `approve cc-planner` |
| "planner 수정해 — XXX" / "spec 다시 써줘" | `reject cc-planner "XXX"` |
| "pool-3 승인해" | `approve pool-3` |
| "pool-3 수정해 — XXX" | `reject pool-3 "XXX"` |
| "여행 기능 추가해" (구체적 태스크) | `add "여행 기능"` |
| "일시정지" / "멈춰" | `pause` |
| "재개" / "다시 시작" | `resume` |

### feature vs add 구분

- **feature**: idea → planner spec → 승인 → queued (신규 기능, 스펙 필요)
- **add**: 바로 queued (이미 명확한 태스크, 스펙 불필요)

## 알림 (코봉 봇)

코봉 봇(8273...)이 단방향 알림을 전송. 이 스킬에서 직접 제어하지 않음.
hooks/telegram_notify.py가 Claude Code Stop hook에서 자동 발송.

알림 포맷:
```
[planner] 여행기능 (#7. spec)
Spec 작성 완료

[pool-3] 캐싱전략 (#42. designing)
Plan 작성 완료

[pool-1] 여행계획 (#38. coding)
구현 완료
```
