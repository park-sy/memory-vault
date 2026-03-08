---
type: pattern
importance: 7
created: 2026-03-07
tags: [tmux, agent, background, automation, infrastructure]
---

# Tmux Background Agent Pattern

Claude Code 세션을 백그라운드 tmux 세션으로 스폰하는 공용 패턴.

## When to Use

| 상황 | 패턴 |
|------|------|
| 5분 이내, 결과 즉시 필요 | `subprocess.run(["claude", ...])` 직접 호출 |
| 수분~수십분, 백그라운드 | `tmux_agent.launch()` — tmux 세션 |
| 병렬 분석, 팀 협업 | `tmux_agent.launch(agent_teams=True)` |

## Basic Launch

```python
from scripts.tmux_agent import launch, is_alive, kill_session

session = launch(
    "code-reviewer",
    system_prompt="You are a code reviewer. Focus on security.",
    initial_message="Review ~/dev/app/src/auth.py",
    cwd="~/dev/app",
)

# 상태 확인
if is_alive(session.session_name):
    print("Running")

# 종료
kill_session(session.session_name)
```

### 파라미터

| 파라미터 | 설명 | 기본값 |
|----------|------|--------|
| `session_name` | tmux 세션 이름 (고유) | 필수 |
| `system_prompt` | `--append-system-prompt`로 전달 | `""` |
| `initial_message` | 시작 후 첫 메시지 | `""` |
| `cwd` | 작업 디렉토리 | 현재 디렉토리 |
| `env_vars` | 추가 환경변수 dict | `None` |
| `agent_teams` | Agent Teams 모드 활성화 | `False` |
| `claude_path` | claude 바이너리 경로 | 자동 탐색 |
| `on_done_hook` | Claude 종료 후 실행할 쉘 명령 | `None` |

## Agent Teams 스폰

`agent_teams=True` → `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true` 자동 설정.

```python
session = launch(
    "feature-team",
    system_prompt="""You are a team lead. Spawn teammates:
- researcher: Research the codebase
- coder: Implement changes
- reviewer: Review code""",
    initial_message="Implement user auth for the app",
    agent_teams=True,
    cwd="~/dev/app",
)
```

## Completion Hook (on_done_hook)

Claude 명령 뒤에 ` ; <hook> || true` 체이닝. 성공/실패 무관 실행.

```python
# MsgBus 알림
session = launch(
    "worker-1",
    initial_message="Run tests",
    on_done_hook="python3 scripts/notify.py 'Worker done' --channel ops",
)

# Webhook
session = launch(
    "worker-2",
    initial_message="Deploy staging",
    on_done_hook="curl -s https://hooks.example.com/deploy-done",
)
```

## Status Detection

```python
from scripts.tmux_agent import is_alive, list_sessions

# 단일 세션 확인
is_alive("code-reviewer")  # True / False

# 접두사로 필터
list_sessions(prefix="cc-")  # ["cc-pool-1", "cc-pool-2"]

# 전체 목록
list_sessions()  # 모든 tmux 세션 이름
```

## 메시지 전달

```python
from scripts.tmux_agent import send_message

# 짧은 메시지: tmux send-keys
send_message("worker-1", "Review auth.py")

# 긴 메시지(>500자): tmux load-buffer → paste-buffer
send_message("worker-1", long_text)
```

## 프롬프트 파일 위치

시스템 프롬프트는 `storage/agent-prompts/{session_id}.md`에 저장.
`AgentSession.prompt_file`로 경로 확인 가능.

## 기존 시스템과의 관계

| 시스템 | 역할 | tmux_agent와의 관계 |
|--------|------|-------------------|
| `pool.sh` | 워커 풀 관리 (bash) | tmux_agent는 pool.sh 대체가 아닌 **하위 레벨 라이브러리** |
| `worker_manager.py` | Feature Factory 워커 | 향후 tmux_agent.launch()로 리팩토링 가능 |
| `daemon.sh` | 서비스 데몬 관리 | 독립. tmux_agent는 에이전트 전용 |

## 관련 문서

- [[02-knowledge/infrastructure/platform-team-operations]] — 팀 운영
- [[02-knowledge/infrastructure/feature-factory-architecture]] — Feature Factory
- [[02-knowledge/infrastructure/communication-system]] — 통신 체계
