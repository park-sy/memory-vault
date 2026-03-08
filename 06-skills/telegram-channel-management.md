---
type: skill
importance: 6
created: "2026-03-08"
tags: [telegram, channel, topic, infrastructure, automation]

---

# Telegram 채널(토픽) 관리

기존 포럼 그룹에 토픽을 추가/조회/테스트하는 통합 CLI.

## CLI

```bash
# 토픽 추가 (생성 + .env 등록 + bridge 재시작 + 테스트 메시지)
bash scripts/telegram-channel.sh add <name>

# 등록된 토픽 목록
bash scripts/telegram-channel.sh list

# 테스트 메시지 전송
bash scripts/telegram-channel.sh test <name>

# 메시지 전송
bash scripts/telegram-channel.sh send <name> "<message>"
```

## 새 도메인/기능 추가 시

1. `bash scripts/telegram-channel.sh add <name>` — 한 줄로 끝
2. 코드에서 `--channel <name>` 옵션으로 해당 토픽에 메시지 전송
3. bridge가 자동으로 토픽 라우팅 처리

## 동작 원리

```
add 명령
  → telegram_api.py create-topic → Telegram API createForumTopic
  → .env에 TELEGRAM_TOPIC_<NAME>=<id> 추가
  → daemon.sh restart bridge (새 토픽 인식)
  → notify.py로 테스트 메시지
```

## 현재 등록된 토픽

| 이름 | 용도 |
|------|------|
| ops | 시스템 제어, 세션 상태 |
| approval | 승인 요청 |
| report | 작업 완료, 빌드 결과 |
| clone | 의사결정 캡처 |
| learning | 학습 도메인 |
| boss | AI Boss 상사 패널 |

## 참조

- `scripts/telegram-channel.sh` — 통합 CLI
- `scripts/telegram_api.py` — Bot API 래퍼 (create_forum_topic)
- `scripts/notify.py` — 아웃바운드 알림 (`--channel` 옵션)
- `scripts/telegram_bridge.py` — 토픽 라우팅 (channel → thread_id)
