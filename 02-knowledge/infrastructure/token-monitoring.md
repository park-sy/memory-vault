---
type: knowledge
importance: 8
created: "2026-03-01"
last_accessed: "2026-03-01"
access_count: 1
tags: [token, monitoring, llm, cost, rate-limit, infrastructure]
---

# Token Monitoring — LLM 호출별 토큰 관리 및 모니터링

## 개요

whos-life 프로젝트의 토큰 추적 시스템. 5개 컴포넌트가 협력하여 개별 LLM 호출부터 전체 Rate Limit까지 추적한다.

```
┌──────────────────────────────────────────────────────────┐
│                    토큰 추적 아키텍처                       │
│                                                          │
│  ClaudeRunner.run_ephemeral()                            │
│       │                                                  │
│       ▼                                                  │
│  LLMTracker ──────────────────→ llm_call_log (DB)        │
│  (개별 LLM 호출 자동 기록)        feature별, method별 추적   │
│                                                          │
│  Claude Code JSONL 파일들                                 │
│       │                                                  │
│       ▼                                                  │
│  Token Dashboard scanner.py ──→ claude_token_usage (DB)  │
│  (세션 파일 파싱)                 프로젝트별, 모델별 집계     │
│                                                          │
│  Anthropic OAuth API                                     │
│       │                                                  │
│       ▼                                                  │
│  Token Monitor service.py ───→ token_snapshots (DB)      │
│  (Rate Limit 추적)              다중 윈도우 시계열 스냅샷   │
│                                                          │
│  Token Monitor service.py ───→ work_queue (DB)           │
│  (토큰 인지 작업 추천)           예상 비용 기반 작업 큐      │
│                                                          │
│  Token Monitor service.py ───→ feature_dev_log (DB)      │
│  (Feature 개발 활동 추적)        feature별 토큰 사용 %      │
└──────────────────────────────────────────────────────────┘
```

## 1. ClaudeRunner — LLM 실행기

> 파일: `~/dev/whos-life/integrations/claude_cli.py`

Claude CLI를 래핑하여 2가지 모드를 제공:

### 모드 비교

| 모드 | 명령 | 토큰 추적 | 세션 유지 | 반환값 |
|------|------|----------|----------|--------|
| `run()` | `claude -p "..." --system "..."` | X | O | (stdout, return_code) |
| `run_ephemeral()` | `claude -p "..." --output-format json --no-session-persistence --system "..."` | O | X | LLMResult |

### LLMResult 구조

```python
@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    # total_tokens = input + output + cache_read + cache_creation

@dataclass(frozen=True)
class LLMResult:
    text: str              # LLM 응답 텍스트
    usage: LLMUsage        # 4종 토큰 상세
    cost_usd: float        # 실제 비용 (total_cost_usd)
    model: str             # 사용된 모델 (modelUsage에서 추출)
    session_id: str        # Ephemeral 세션 UUID
    duration_ms: int       # 벽시계 시간
    return_code: int
    success: bool
```

### JSON 출력 파싱

`run_ephemeral()`은 Claude CLI의 `--output-format json` 응답을 파싱:

```json
{
    "result": "응답 텍스트",
    "usage": {
        "input_tokens": 1500,
        "output_tokens": 800,
        "cache_read_input_tokens": 200,
        "cache_creation_input_tokens": 50
    },
    "total_cost_usd": 0.0042,
    "modelUsage": { "claude-sonnet-4-20250514": {} },
    "session_id": "abc-123"
}
```

## 2. LLMTracker — 자동 호출 기록

> 파일: `~/dev/whos-life/core/llm_tracker.py`

`ClaudeRunner.run_ephemeral()` 래퍼. 호출 후 자동으로 `llm_call_log` 테이블에 기록.

### API

```python
class LLMTracker:
    async def run(feature_name, method, prompt, system="", timeout=120) -> LLMResult
    def get_feature_stats(feature_name) -> FeatureCallStats
    def get_all_stats() -> list[FeatureCallStats]            # cost DESC 정렬
    def get_daily_summary(days=30) -> list[DailyCallSummary]  # 일별 집계
```

### 기록 필드 (`llm_call_log` 테이블)

| 필드 | 타입 | 설명 |
|------|------|------|
| feature_name | TEXT | 호출한 feature |
| method | TEXT | 호출한 method |
| model | TEXT | 사용 모델 |
| input_tokens | INT | 입력 토큰 |
| output_tokens | INT | 출력 토큰 |
| cache_read_tokens | INT | 캐시 읽기 토큰 |
| cache_creation_tokens | INT | 캐시 생성 토큰 |
| cost_usd | TEXT | 비용 (**문자열** — IEEE 754 부동소수점 문제 방지) |
| duration_ms | INT | 실행 시간 |
| session_id | TEXT | 세션 UUID |

### 에러 처리

DB 기록 실패 시 로깅만 하고 예외를 전파하지 않는다 (LLM 호출 자체는 성공).

## 3. 세션 수명주기: Core vs Ephemeral

`ai_sessions` 테이블에서 `lifecycle` 필드로 구분:

| 수명주기 | 설명 | 세션 유지 | 정리 |
|----------|------|----------|------|
| `core` | 장기 보존 대화, 메인 에이전트 세션 | O | 수동 |
| `ephemeral` | 1회성 LLM 호출 (분석, 요약) | X | 24시간 후 자동 cleanup |

`SessionManager.cleanup_ephemeral(max_age_hours=24)`: 만료된 ephemeral 세션 자동 정리.

## 4. Token Dashboard — JSONL 스캐너

> 파일: `~/dev/whos-life/features/ai-ops/token-dashboard/`

Claude Code가 남기는 JSONL 세션 파일을 파싱하여 프로젝트별, 모델별 토큰 사용량을 집계.

### 파이프라인

```
~/.claude/projects/*/JSONL 파일들
    │
    ▼
scanner.py
    ├── discover: 변경된 파일만 스캔
    ├── parse: requestId 기반 스트리밍 청크 중복 제거
    └── extract: TokenRecord (session, project, model, tokens)
    │
    ▼
claude_token_usage (DB)
    │
    ▼
service.py — get_dashboard_data()
    ├── Rate Limits (Anthropic OAuth API)
    ├── Daily usage (30일)
    ├── Summary: total messages, tokens, sessions, active days
    └── Grouped by: project, model
    │
    ▼
render.py — NiceGUI 대시보드
    ├── Rate Limit 게이지 (녹색 <70%, 주황 70-90%, 빨강 >90%)
    ├── 일별 토큰 사용량 차트
    ├── 프로젝트별 테이블
    └── 모델별 테이블
```

### `DashboardData` 구조 (Pydantic)

```python
class DashboardData(BaseModel):
    rate_limits: list[RateLimitStatus]
    daily_usage: list[DailyUsage]
    summary: SummaryStats
    by_project: list[ProjectStats]
    by_model: list[ModelStats]
```

## 5. Token Monitor — Rate Limit + 작업 추천

> 파일: `~/dev/whos-life/features/ai-ops/token-monitor/`

Anthropic OAuth API로 다중 모델의 Rate Limit 사용률을 추적하고, 토큰 인지 작업 추천을 제공.

### Rate Limit 윈도우

| 윈도우 | 설명 |
|--------|------|
| 5시간 | 5시간 롤링 윈도우 |
| 7일 전체 | 7일 전체 토큰 |
| 7일 Sonnet | 7일 Sonnet 전용 |
| 7일 Opus | 7일 Opus 전용 |

### API 흐름 (Anthropic OAuth)

```
macOS Keychain ("Claude Code-credentials")
    → OAuth access_token 추출
    → GET https://api.anthropic.com/api/oauth/usage
    → Headers: anthropic-beta: oauth-2025-04-20
    → 응답: 윈도우별 { utilization: 45.2, resets_at: "..." }
```

### 토큰 인지 작업 추천

`recommend_work()`: 현재 사용률 기반으로 가용 용량에 맞는 작업을 추천.

- **Available % = 70 - current_utilization** (70%를 임계값으로 설정)
- `work_queue` 테이블에서 `estimated_pct`가 가용 용량 이하인 작업만 추천

### Feature 개발 활동 추적

`log_feature_dev()`: feature 개발 세션을 기록.

| 필드 | 설명 |
|------|------|
| feature_name | 기능 이름 |
| action | create / update / fix / refactor |
| tokens_used_pct | 가용 토큰 대비 사용률 % |
| model_used | 사용 모델 |
| duration_sec | 소요 시간 |
| files_changed | 변경된 파일 수 |

`get_feature_dev_stats()`: feature별 총 토큰, 개발 횟수, 마지막 수정일 집계.

## DB 테이블 요약

| 테이블 | 용도 | 주요 인덱스 |
|--------|------|------------|
| `llm_call_log` | 개별 LLM 호출 기록 (LLMTracker) | feature_name, created_at |
| `claude_token_usage` | JSONL 스캔 결과 (Token Dashboard) | session_id, project, timestamp |
| `ai_sessions` | 세션 수명주기 (Core/Ephemeral) | scope, provider_id |
| `token_snapshots` | Rate Limit 시계열 (Token Monitor) | provider, snapshot_at |
| `work_queue` | 토큰 인지 작업 큐 (Token Monitor) | priority, status |
| `feature_dev_log` | Feature 개발 활동 (Token Monitor) | feature_name |

## 비용 저장 규약

`cost_usd`는 모든 테이블에서 **TEXT 타입**으로 저장한다.
이유: IEEE 754 부동소수점 정밀도 문제 방지 (0.1 + 0.2 ≠ 0.3).

## Related

- [[03-projects/whos-life/context]] — LLM 2-tier 구조 요약
- [[06-skills/feature-pipeline]] — 토큰 제어 정책 (3-Tier 세션)
- [[02-knowledge/infrastructure/openclaw-messenger-architecture]] — OpenClaw config.json 토큰 설정
