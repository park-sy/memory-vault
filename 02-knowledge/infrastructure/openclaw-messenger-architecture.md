---
type: knowledge
importance: 7
created: "2026-02-28"
last_accessed: "2026-02-28"
access_count: 1
tags: [openclaw, messenger, telegram, architecture, reference]
source: "codebase-analysis"
---

# OpenClaw 메신저 통신 아키텍처

## 전체 아키텍처

OpenClaw은 **Telegram 단일 채널 + 듀얼봇** 구조.
ChannelPlugin 추상화 없이, Telegram API를 직접 호출하는 lean 아키텍처.

```
┌─────────────────┐
│   User (상엽)    │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
  Yap Bot   Cobong Bot
 (양방향)    (알림전용)
    │         ▲
    │         │ Direct HTTP POST
    │         │ (urllib, sync/async)
    ▼         │
 OpenClaw     │
 (Router)     │
    │         │
    ▼ tmux send-keys
cc-orchestration (main brain)
    │
    ├─→ scheduler.py (토큰 관리, 작업 배분)
    ├─→ orchestration_commands.py (명령 핸들러)
    ├─→ feedback.py (피드백 분류 루프)
    └─→ session_pool.py (워커/플래너 관리)
```

### 핵심 특징

- **프레임워크 없음**: 외부 메시징 SDK 미사용, Python stdlib만 사용 (urllib, json, sqlite3, subprocess)
- **단일 채널**: Telegram만 지원. Slack/Discord 미구현
- **듀얼봇 패턴**: 인바운드(Yap)와 아웃바운드(Cobong) 분리
- **tmux 통신**: 봇 → cc-orchestration 세션으로 `tmux send-keys`

## Telegram 상세

### 라이브러리

**raw urllib** — grammY 등 프레임워크 미사용.
`urllib.request.urlopen()`으로 Telegram Bot API 직접 호출.

### Polling vs Webhook

**Long-Polling (5초 timeout)**

```python
# telegram.py
def get_updates(config, offset=0, limit=10):
    url = f"https://api.telegram.org/bot{config.bot_token}/getUpdates"
    params = urllib.parse.urlencode({"offset": offset, "limit": limit, "timeout": 5})
    with urllib.request.urlopen(f"{url}?{params}", timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("result", []) if result.get("ok") else []
```

- Webhook 인프라 없음 (서버리스/stateless 구조에 적합)
- 단순하지만 실시간성 제한 (최대 5초 지연)

### Outbound HTTP

```python
# telegram.py
def send_message(config, message):
    url = f"https://api.telegram.org/bot{config.bot_token}/sendMessage"
    payload = {
        "chat_id": config.chat_id,
        "text": message.text,
        "parse_mode": "Markdown",
        "reply_to_message_id": message.reply_to_message_id,
        "reply_markup": message.reply_markup
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

### 듀얼봇 구조

| 봇 | 역할 | 방향 | 용도 |
|------|------|------|------|
| **Yap Bot** | 양방향 | Inbound + Outbound | 명령 수신, 피드백 수집 |
| **Cobong Bot** | 알림 전용 | Outbound only | plan_ready, complete, crash 알림 |

**Cobong Bot 알림 메시지:**

```python
# telegram_notify.py
def _format_plan_ready_message(session_name, info):
    return f"[{session_name}] {task_title}\nPlan 작성 완료"

def _build_inline_keyboard(session_url):
    return {
        "inline_keyboard": [[
            {"text": "Claude 앱에서 열기", "url": session_url},
        ]],
    }
```

### 환경 변수

```
TELEGRAM_BOT_TOKEN    # Bot API 토큰
TELEGRAM_CHAT_ID      # 대상 채팅/그룹 ID
```

## 데이터 모델

### Immutable Dataclass 패턴

```python
@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str

@dataclass(frozen=True)
class TelegramMessage:
    text: str
    parse_mode: str = "Markdown"
    reply_to_message_id: Optional[int] = None
    reply_markup: Optional[dict] = None
```

### Context Manager 패턴

```python
@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

## 메시지 라우팅

**추상화 레이어 없음** — 모든 로직이 Telegram 포맷에 직접 결합.

### Inbound: 피드백 분류 (정규화 아님)

```python
# feedback.py
def _classify_feedback(text):
    keywords = {
        "fix": ["버그", "에러", "fix", "bug", "수정"],
        "style": ["디자인", "스타일", "색상", "ui"],
        "feature": ["추가", "기능", "feature", "구현"],
        "general": [anything_else]
    }
```

### Outbound: 오케스트레이션 명령

```python
# orchestration_commands.py
def approve(session_name, message="")
def reject(session_name, feedback="")
def assign_feature(title, description="")
def add_task(title, description="")
def pause() / resume() / status()
```

호출 흐름: Yap Bot → OpenClaw 파싱 → `tmux send-keys -t cc-orchestration "approve pool-3"`

## 비교: 현재 vs 이상적 멀티채널

| 차원 | 현재 (Telegram only) | 이상적 (ChannelPlugin 추상화) |
|------|---------------------|---------------------------|
| 채널 수 | 1 (Telegram) | N (Telegram, Slack, Discord, ...) |
| 추상화 | 없음 | ChannelPlugin 인터페이스 |
| 메시지 포맷 | Telegram raw JSON | 정규화된 NormalizedMessage |
| 라우팅 | 하드코딩 | 플러그인 레지스트리 |
| 확장성 | 리라이트 필요 | 플러그인 추가만 |
| 복잡도 | 낮음 (장점) | 중간 |
| 의존성 | stdlib만 | SDK별 의존성 |

## 설정

```json
// config.json
{
  "notify_channel": "telegram",
  "session_pool": {
    "size": 3,
    "tmux_prefix": "cc-pool",
    "planner_tmux_name": "cc-planner",
    "orchestration_tmux_name": "cc-orchestration"
  },
  "token_thresholds": {
    "pause_all": 90,
    "tier1": { "max_pct": 50, "designing": 5, "coding": 1 },
    "tier2": { "max_pct": 70, "designing": 3, "coding": 1 },
    "tier3": { "max_pct": 90, "designing": 1, "coding": 0 }
  }
}
```

## 핵심 파일 맵

| 파일 | 줄수 | 역할 |
|------|------|------|
| `skills/auto-dev/telegram.py` | 165 | Telegram Bot API 래퍼 (send/receive) |
| `skills/auto-dev/hooks/telegram_notify.py` | 218 | Hook 트리거 알림 (Cobong Bot) |
| `skills/auto-dev/orchestration_commands.py` | 399 | 명령 핸들러 (approve/reject/status) |
| `skills/auto-dev/feedback.py` | 286 | 피드백 분류 + 큐 연동 |
| `skills/auto-dev/scheduler.py` | 1,628 | 토큰 관리 + 작업 배분 |
| `skills/auto-dev/session_pool.py` | 1,009 | 워커/플래너 세션 관리 |
| `skills/auto-dev/session_status.py` | 394 | Hook 핸들러 (상태 전이) |
| `skills/auto-dev/config.json` | — | 설정 |

## 보안 참고

- Telegram 봇 토큰은 환경 변수로 관리 (하드코딩 아님)
- `--dangerously-skip-permissions` 플래그 사용 중 (보안 우려)
- Telegram API 호출에 rate limiting 없음
- 연결 풀링 미사용 (매 요청 새 연결)

## Related

- [[003-independent-a2a-communication]] — OpenClaw 의존 없는 독립 통신 설계
- [[002-platform-team-structure]] — 코어팀 조직 구조
- `docs/openclaw-architecture.md` — OpenClaw 전체 아키텍처 문서
- `docs/reviews/auto-dev-pipeline-review.md` — 보안 리뷰 결과
