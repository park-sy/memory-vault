---
type: decision
id: "003"
status: proposed
date: "2026-02-28"
participants: ["상엽", "얍"]
importance: 9
tags: [architecture, a2a, communication, session, independence]

---

# ADR-003: 독립 A2A 통신 체계 구축

> **Note (2026-03-01):** 이 ADR에서 "mailbox"로 언급된 시스템은 `msgbus.py`(MsgBus)로 통합되었다. 아래 본문은 작성 당시 용어를 그대로 보존한 역사적 기록.

## Context

### 현재 한계

1. **단방향 tmux**: `tmux send-keys`로 명령만 전달. 응답 수신은 `capture-pane` 파싱에 의존 (불안정)
2. **OpenClaw 의존**: 모든 세션 간 통신이 OpenClaw 인프라를 경유. OpenClaw 장애 시 전체 마비
3. **비동기 불가**: 메시지 큐 없음. 수신 세션이 바쁘면 메시지 유실
4. **구조화 부재**: 자유 텍스트로만 통신. 메시지 타입/우선순위/응답 추적 불가
5. **피드백 루프 없음**: 발신자가 메시지 전달/처리 여부를 확인할 수 없음

### OpenClaw 레퍼런스

OpenClaw의 통신 패턴을 참고하되, 의존하지 않는 독립 체계 구축:

| OpenClaw 패턴 | 레퍼런스 포인트 | 독립 구현 대응 |
|---------------|----------------|---------------|
| 듀얼봇 (Yap/Cobong) | 인바운드/아웃바운드 분리 | 채널별 방향성 분리 |
| tmux send-keys | 세션 간 명령 주입 | tmux 채널 (개선) |
| Long-polling | 비동기 수신 | SQLite mailbox polling |
| Inline keyboard | 구조화된 응답 옵션 | 메시지 타입 enum |
| Config-driven dispatch | 설정 기반 라우팅 | 라우팅 테이블 |

## Decision

### 6채널 통신 아키텍처

용도와 신뢰도에 따라 6개 채널을 계층적으로 설계한다.

```
┌─────────────────────────────────────────────────────┐
│                 Communication Channels               │
├──────────┬──────────┬──────────────────────────────────┤
│ Priority │ Channel  │ Use Case                         │
├──────────┼──────────┼──────────────────────────────────┤
│ 1 (즉시) │ tmux     │ 긴급 명령, 세션 제어              │
│ 2 (신뢰) │ SQLite   │ 구조화된 메시지, 작업 할당         │
│ 3 (벌크) │ File     │ 대용량 데이터, 코드 전달           │
│ 4 (이벤트)│ Hook     │ 도구 실행 전후 트리거             │
│ 5 (외부) │ Telegram │ 사람(상엽)과 직접 통신             │
│ 6 (표준) │ MCP      │ 표준화된 도구 호출                │
└──────────┴──────────┴──────────────────────────────────┘
```

### 채널 1: tmux (즉시 명령)

기존 `tmux send-keys` 개선.

```bash
# 발신
tmux send-keys -t {target_session} "{command}" Enter

# 수신 확인 (개선: 마커 기반)
MARKER="__MSG_$(date +%s)__"
tmux send-keys -t target "echo $MARKER && {command}" Enter
# capture-pane으로 MARKER 이후 출력 파싱
```

**개선점:**
- 마커 기반 응답 파싱으로 신뢰성 향상
- timeout 설정으로 무한 대기 방지
- 메시지 ID 부여로 추적 가능

### 채널 2: SQLite Mailbox (구조화 메시지)

세션 간 비동기 메시지 교환의 핵심 채널.

```sql
CREATE TABLE mailbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT DEFAULT (datetime('now')),
    sender      TEXT NOT NULL,        -- 'cc-pool-1', 'cc-orchestration'
    recipient   TEXT NOT NULL,        -- 'cc-pool-2', 'broadcast'
    msg_type    TEXT NOT NULL,        -- 'task', 'result', 'query', 'ack'
    priority    INTEGER DEFAULT 5,    -- 1=urgent, 5=normal, 9=low
    payload     TEXT NOT NULL,        -- JSON
    status      TEXT DEFAULT 'pending', -- 'pending', 'read', 'processed'
    reply_to    INTEGER REFERENCES mailbox(id),
    expires_at  TEXT                  -- 자동 만료
);

CREATE INDEX idx_recipient_status ON mailbox(recipient, status);
CREATE INDEX idx_created ON mailbox(created_at);
```

**메시지 타입:**

| msg_type | 용도 | payload 예시 |
|----------|------|-------------|
| `task` | 작업 할당 | `{"title": "...", "spec": "..."}` |
| `result` | 작업 결과 | `{"status": "done", "files": [...]}` |
| `query` | 질의 | `{"question": "...", "context": "..."}` |
| `ack` | 수신 확인 | `{"original_id": 42, "status": "received"}` |
| `broadcast` | 전체 공지 | `{"message": "토큰 80% 도달"}` |

**Polling 스크립트:**

```python
# scripts/mailbox.py
import sqlite3, json, time

DB = "~/dev/memory-vault/storage/mailbox.db"

def send(sender, recipient, msg_type, payload, priority=5):
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO mailbox (sender, recipient, msg_type, priority, payload) VALUES (?,?,?,?,?)",
            (sender, recipient, msg_type, priority, json.dumps(payload))
        )

def receive(recipient, limit=10):
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            "SELECT id, sender, msg_type, priority, payload FROM mailbox "
            "WHERE recipient IN (?, 'broadcast') AND status = 'pending' "
            "ORDER BY priority, created_at LIMIT ?",
            (recipient, limit)
        ).fetchall()
        ids = [r[0] for r in rows]
        if ids:
            conn.execute(
                f"UPDATE mailbox SET status = 'read' WHERE id IN ({','.join('?' * len(ids))})",
                ids
            )
        return [{"id": r[0], "sender": r[1], "type": r[2], "priority": r[3],
                 "payload": json.loads(r[4])} for r in rows]
```

### 채널 3: File Drop (대용량)

파일 시스템 기반 대용량 데이터 교환.

```
~/dev/memory-vault/storage/drops/
├── cc-pool-1/          # 수신함 (세션별)
│   ├── inbox/
│   │   └── 2026-02-28_task-spec.json
│   └── outbox/
│       └── 2026-02-28_result.tar.gz
├── cc-pool-2/
└── shared/             # 공유 영역
    └── code-review-checklist.md
```

**프로토콜:**
1. 발신자가 `{recipient}/inbox/` 에 파일 작성
2. 수신자가 inbox를 주기적으로 스캔 (또는 mailbox로 알림)
3. 처리 후 파일 이동 또는 삭제

### 채널 4: Hook (이벤트 트리거)

Claude Code의 Hook 시스템을 활용한 이벤트 기반 통신.

```json
// .claude/settings.json hooks
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "command": "python3 ~/dev/memory-vault/scripts/hook-notify.py file-changed $FILE_PATH"
      }
    ],
    "Stop": [
      {
        "command": "python3 ~/dev/memory-vault/scripts/hook-notify.py session-end $SESSION_ID"
      }
    ]
  }
}
```

**이벤트 타입:**
- `file-changed`: 파일 수정 시 관련 세션에 알림
- `session-end`: 세션 종료 시 결과 전달
- `plan-ready`: 계획 작성 완료 → 승인 요청

### 채널 5: Telegram 직접 (사람 통신)

OpenClaw 경유 없이 Telegram Bot API 직접 호출.

```python
# scripts/notify.py
import urllib.request, json

def notify_human(message, bot_token, chat_id):
    """OpenClaw 없이 직접 Telegram 알림"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())
```

**용도:**
- 긴급 알림 (토큰 소진, 크리티컬 에러)
- 승인 요청 (plan_ready)
- 일일 요약 보고

### 채널 6: MCP (표준 도구 호출)

Model Context Protocol 서버를 통한 표준화된 도구 교환.

```json
// .claude/settings.json
{
  "mcpServers": {
    "vault-tools": {
      "command": "python3",
      "args": ["~/dev/memory-vault/scripts/mcp-server.py"],
      "tools": ["read_memory", "write_memory", "search_vault", "send_message"]
    }
  }
}
```

**MCP 도구:**
- `read_memory`: vault에서 knowledge 조회
- `write_memory`: 새 knowledge 저장
- `search_vault`: 태그/키워드 검색
- `send_message`: mailbox를 통한 메시지 발신

## 채널 선택 가이드

```
시나리오                        → 채널
─────────────────────────────────────────
긴급 세션 제어 (kill, restart)  → tmux
작업 할당/결과 보고              → SQLite mailbox
코드 전달/대용량 데이터          → File drop
파일 변경 이벤트                → Hook
사람에게 알림                   → Telegram
표준화된 도구 호출              → MCP
```

## 구현 단계

### Step 1: SQLite Mailbox (핵심)

1. `storage/mailbox.db` 스키마 생성
2. `scripts/mailbox.py` 라이브러리 구현
3. 각 세션의 시작 hook에서 mailbox polling 시작
4. 테스트: 두 tmux 세션 간 메시지 교환

### Step 2: tmux 개선

1. 마커 기반 응답 파싱 구현
2. `scripts/tmux-comm.py` 래퍼 작성
3. timeout/retry 로직 추가
4. 기존 OpenClaw tmux 호출을 래퍼로 대체

### Step 3: Hook + File Drop

1. Hook 설정 추가 (PostToolUse, Stop)
2. `storage/drops/` 디렉토리 구조 생성
3. hook-notify.py 구현
4. mailbox와 연동 (파일 드롭 시 mailbox 알림)

### Step 4: Telegram 직접 + MCP

1. notify.py — 직접 Telegram 호출
2. MCP 서버 스켈레톤 구현
3. vault 도구 (read/write/search) 구현
4. send_message를 mailbox 경유로 연결

## Consequences

### 긍정적

- **OpenClaw 독립성**: OpenClaw 없이도 세션 간 통신 가능
- **장애 내성**: 채널 이중화로 단일 장애점 제거
- **비동기 지원**: SQLite mailbox로 메시지 유실 방지
- **구조화**: 메시지 타입/우선순위/추적 가능
- **확장성**: 새 채널 추가 시 기존 채널 영향 없음
- **감사 추적**: 모든 메시지가 DB에 기록 → 디버깅 용이

### 부정적

- **초기 구현 비용**: 6개 채널 모두 구현 필요
- **복잡도 증가**: 채널 선택 로직 필요
- **유지보수**: mailbox DB 관리 (만료, 정리)
- **Telegram 토큰 관리**: 독립 호출 시 토큰 별도 관리 필요

### 대응

| 단점 | 해소 수단 |
|------|----------|
| 초기 비용 | Step 1(mailbox)만으로 즉시 효과. 나머지는 점진적 |
| 채널 선택 | 가이드 테이블 + 기본값(mailbox) 설정 |
| DB 관리 | cron으로 만료 메시지 자동 정리 |
| 토큰 관리 | .env 파일에서 로드 (기존 패턴 활용) |

## Related

- [[001-vault-structure]] — Memory Vault 기본 구조
- [[002-platform-team-structure]] — Platform Team 조직 편제
- [[openclaw-messenger-architecture]] — OpenClaw 통신 분석 (레퍼런스)
