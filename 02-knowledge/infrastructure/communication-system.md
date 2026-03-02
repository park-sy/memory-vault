---
type: knowledge
importance: 8
created: "2026-03-01"
last_accessed: "2026-03-01"
access_count: 1
tags: [communication, telegram, msgbus, tmux, infrastructure]
---

# Communication System — 통신 체계

## 개요

memory-vault 시스템의 통신은 3개 계층으로 구성된다:

```
┌─────────────────────────────────────────────┐
│              외부 통신 (Telegram)              │
│  상엽 ↔ Telegram Bot ↔ 브릿지/오케스트레이터   │
├─────────────────────────────────────────────┤
│           메시지 버스 (MsgBus)                │
│  SQLite 기반, 4채널 분류, 비동기 통신           │
├─────────────────────────────────────────────┤
│           내부 통신 (tmux)                    │
│  세션 간 직접 통신, pool.sh, send-keys         │
└─────────────────────────────────────────────┘
```

## 1. 외부 통신: Telegram

상엽과 AI 에이전트 간 양방향 통신.

### 아키텍처

```
상엽 (Telegram App)
    │
    ▼
Telegram Bot API
    │
    ├──── Yap Bot (양방향)
    │       │
    │       ▼
    │    telegram_bridge.py ── Long-Polling (5초)
    │       │
    │       ▼
    │    SQLite MsgBus
    │       │
    │       ▼
    │    Claude 세션들
    │
    └──── Cobong Bot (알림 전용)
            ▲
            │ Direct HTTP POST
            │
         telegram_notify.py (Hook에서 호출)
```

### 두 봇 체계

| 봇 | 역할 | 방향 | 위치 |
|------|------|------|------|
| Yap Bot | 양방향 통신 | Inbound + Outbound | telegram_bridge.py |
| Cobong Bot | 알림 전용 | Outbound only | telegram_notify.py (Hook) |

### 환경변수 (`.env`)

```
TELEGRAM_BOT_TOKEN    # Yap Bot 토큰
TELEGRAM_CHAT_ID      # 대상 채팅/그룹 ID
# 토픽 ID는 .env에 설정
```

### Telegram 명령 라우팅

| 명령 | 수신자 |
|------|--------|
| `/pool1 <text>` | cc-pool-1 워커 |
| `/pool2 <text>` | cc-pool-2 워커 |
| `/orch <text>` | cc-orchestration |
| `/status` | cc-orchestration (query) |
| 일반 텍스트 | cc-orchestration |

## 2. 메시지 버스: MsgBus

Telegram 브릿지와 Claude 세션 사이의 SQLite 기반 비동기 메시지 큐.

### 스크립트 맵

| 스크립트 | 역할 |
|----------|------|
| `scripts/msgbus.py` | 통합 메시지 버스 (messages + channel_refs 테이블, 단일 DB) |
| `scripts/inbox-deliver.py` | Stop hook — pending 메시지 자동 전달 |
| `scripts/telegram_api.py` | Telegram Bot API 래퍼 (stdlib urllib) |
| `scripts/telegram_bridge.py` | 브릿지 데몬 (이중 polling: Telegram + MsgBus) |
| `scripts/notify.py` | 아웃바운드 알림 CLI |
| `scripts/check_inbox.py` | 인바운드 메시지 확인 CLI |

### 4채널 토픽 구조

포럼 그룹의 4개 토픽으로 메시지를 분류:

| 채널 | 용도 | 알림 |
|------|------|------|
| `ops` | 시스템 제어, 세션 상태, 풀 관리 | 무음 |
| `approval` | 승인 요청 (plan_ready 등) | ON |
| `report` | 작업 완료, 빌드 결과, 요약 | 무음 |
| `clone` | 의사결정 캡처, 패턴 학습 | 무음 |

### 아웃바운드 (알림 보내기)

```bash
python3 scripts/notify.py "Plan ready" --channel approval --actions approve reject
python3 scripts/notify.py "Build done" --channel report --sender cc-pool-1
python3 scripts/notify.py "Session started" --channel ops
python3 scripts/notify.py "CRITICAL: Token limit" --channel ops --priority 1
```

### 인바운드 (메시지 확인)

```bash
python3 scripts/check_inbox.py cc-pool-1         # 내 메시지 확인 (read 처리)
python3 scripts/check_inbox.py cc-pool-1 --json   # JSON 출력
python3 scripts/check_inbox.py cc-pool-1 --peek   # 읽기만 (상태 변경 없음)
python3 scripts/check_inbox.py --ack 42            # 처리 완료
```

### 브릿지 시작

```bash
tmux new-session -d -s cc-telegram-bridge \
  -c ~/dev/memory-vault \
  "python3 scripts/telegram_bridge.py"
```

## 3. 내부 통신: MsgBus + tmux + Stop Hook

Claude 세션 간 통신. MsgBus(DB)가 메시지 큐, tmux가 전달 수단, Stop hook이 자동 전달.

### 아키텍처 (ADR-004 Amendment)

```
오케스트레이터: pool.sh send → msgbus.db 기록 + tmux 직접 전달 + ack
Telegram:       bridge.py → msgbus.db 기록 (pending)
Stop hook:      inbox-deliver.py → msgbus.db 확인 → pending 있으면 tmux 전달
```

MCP 대신 Stop hook을 사용하는 이유: [[04-decisions/004-cli-over-mcp-for-features]] Amendment 참조.

### 세션 구조

```
cc-orchestration     오케스트레이터 (팀 리더)
cc-pool-1            워커 1 (CC_SESSION=cc-pool-1)
cc-pool-2            워커 2 (CC_SESSION=cc-pool-2)
cc-pool-N            워커 N
cc-telegram-bridge   Telegram 브릿지 데몬
```

### 메시지 전달 흐름

**직접 전달 (pool.sh send)**:
1. `pool.sh send 1 "작업"` → msgbus.db에 기록
2. tmux send-keys로 워커에 직접 전달
3. 전달 성공 시 msgbus에서 즉시 ack (audit 용도)

**비동기 전달 (Telegram → 워커)**:
1. Telegram 메시지 → bridge.py → msgbus.db에 pending 기록
2. 워커가 현재 작업 완료 → Stop hook 발동
3. `inbox-deliver.py`: msgbus.db에서 pending 메시지 확인
4. 있으면 tmux send-keys로 워커에 전달 (receive → read 마킹)

### pool.sh를 통한 워커 관리

```bash
bash scripts/pool.sh init 3                    # 워커 3개 생성
bash scripts/pool.sh send 1 "작업 메시지"        # 워커 1에 작업 전달
bash scripts/pool.sh capture 1                 # 워커 1 출력 확인
bash scripts/pool.sh status                    # 전체 상태
```

상세: [[02-knowledge/infrastructure/platform-team-operations]] "워커 풀" 섹션

### 완료 키워드 기반 핸드오프

워커가 완료 키워드를 출력하면 오케스트레이터가 감지:

```
워커 작업 완료 → "SPEC_READY" / "CODE_DONE" 등 출력
  → Stop hook: inbox-deliver.py가 다음 pending 메시지 자동 전달
  → 오케스트레이터가 capture로 상태 확인
  → 다음 단계 진행 또는 상엽에게 승인 요청
```

## 4. OpenClaw 시스템 (별도 프로젝트)

memory-vault MsgBus와 별도로, OpenClaw이라는 프로젝트가 더 정교한 Telegram 통신을 제공한다.
듀얼봇(Yap + Cobong), 피드백 분류, 오케스트레이션 명령 핸들러 등.

상세: [[02-knowledge/infrastructure/openclaw-messenger-architecture]]

### MsgBus vs OpenClaw 비교

| 차원 | MsgBus (memory-vault) | OpenClaw |
|------|----------------------|----------|
| 위치 | `~/dev/memory-vault/scripts/` | `~/.openclaw/workspace/` |
| 아키텍처 | SQLite MsgBus + 단순 브릿지 | 듀얼봇 + 피드백 분류 + 스케줄러 |
| 용도 | 범용 세션 간 통신 | Feature Pipeline 전용 오케스트레이션 |
| 봇 | Yap Bot (양방향) | Yap Bot (양방향) + Cobong Bot (알림) |
| 기반 | stdlib (urllib, sqlite3) | stdlib (urllib, sqlite3, subprocess) |

## 전체 통신 흐름 예시

### 새 기능 요청 흐름

```
1. 상엽이 Telegram에서 "/feature 여행 기능" 입력
2. Yap Bot → telegram_bridge.py → MsgBus
3. cc-orchestration이 MsgBus에서 메시지 수신
4. 오케스트레이터: 케이스 2 판별 → Feature Pipeline 진입
5. pool.sh send 1 "spec 작성 시작" → cc-pool-1 (planner)
6. planner가 상엽과 대화하며 spec 작성
7. "SPEC_READY" 출력 → 오케스트레이터 감지
8. notify.py "Spec 완료" --channel approval → Telegram
9. 상엽: "승인" → 다음 단계 진행
```

## Related

- [[02-knowledge/infrastructure/openclaw-messenger-architecture]] — OpenClaw 상세
- [[02-knowledge/infrastructure/platform-team-operations]] — 워커 풀 운영
- [[06-skills/feature-pipeline]] — Feature Pipeline (통신 기반 워크플로우)
