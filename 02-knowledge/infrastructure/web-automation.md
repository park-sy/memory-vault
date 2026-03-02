---
type: knowledge
importance: 7
created: 2026-03-01
tags: [infrastructure, web-automation, playwright, tier-cascade]
last_accessed: 2026-03-01
access_count: 1
---

# Web Automation — 4-Tier Cascade

## 아키텍처

```
Tier 1: web-search.py (검색 + 정적 fetch)
  ↓ 실패 (빈 껍데기, JS 필요)
Tier 2: web-auto.py (Playwright 어댑터)
  ↓ 실패 (fallback:tier3 시그널)
Tier 3: Chrome MCP (AI 브라우저, 최후 수단)
```

### Tier 판단 기준

| 조건 | Tier |
|------|------|
| 검색 결과 + 정적 HTML | 1 |
| JS 렌더링, `<noscript>`, CloudFlare | 2 |
| Tier 2 실패, 사이트 구조 변경 | 3 |
| 로그인 필요 + 어댑터 있음 | 2 |
| 로그인 필요 + 어댑터 없음 | 3 → record → 2 |

## 어댑터 패턴

사이트별 자동화를 `storage/site-adapters/{domain}.json`에 선언적으로 정의.

### 구조

```json
{
  "domain": "example.com",
  "version": 1,
  "flows": [
    {
      "name": "scrape_deals",
      "flow_type": "read",
      "steps": [
        {"step_id": 1, "action": "navigate", "value": "https://..."},
        {"step_id": 2, "action": "extract", "selector": {"css": ".item"}, "extract_key": "items"}
      ]
    }
  ],
  "rate_limit_seconds": 5.0,
  "daily_cap": 100,
  "trust_level": "manual"
}
```

### 액션 타입

| 액션 | 용도 |
|------|------|
| `navigate` | URL 이동 ({{변수}} 템플릿 지원) |
| `click` | 요소 클릭 |
| `type` | 입력 필드에 텍스트 입력 |
| `wait` | 대기 (ms) |
| `extract` | 텍스트 추출 → extract_key로 저장 |
| `screenshot` | 전체 페이지 캡처 |
| `submit` | 폼 제출 |

### 셀렉터 우선순위

`css` → `xpath` → `text_contains` 순서로 시도.

## 안전장치

### 승인 게이트 (write 플로우만)

| trust_level | 동작 |
|-------------|------|
| `manual` (기본) | 매번 수동 승인 필요 |
| `review` | 자동 실행, 5분 내 거부 가능 |
| `auto` | 즉시 실행, 로그만 |

### Trust Level 승격/강등

- manual → review: write 10회 연속 성공
- review → auto: 30회 연속 무거부
- 에러 1회 → 즉시 manual로 강등

### Rate Limit

- 도메인별 `rate_limit_seconds` 간격 제한
- 도메인별 `daily_cap` 일일 상한
- 스텝 간 ±30% jitter 딜레이

### Anti-Detection

- User-Agent 풀 (Chrome/Firefox, 3개 OS)
- Viewport 풀 (1920x1080, 1440x900, 1366x768)
- 중복 게시 방지 (같은 URL write 차단)

## 데이터 저장

| 위치 | 내용 |
|------|------|
| `storage/web-auto.db` | 실행 이력, 승인, rate limit, 세션 (SQLite WAL) |
| `storage/site-adapters/*.json` | 어댑터 설정 (git 추적) |
| `storage/screenshots/` | 스크린샷 (gitignore) |

## CLI 레퍼런스

```bash
# 실행
python3 scripts/web-auto.py run <domain> <flow> [--input '{}'] [--dry-run] [--headed]

# 어댑터 등록
python3 scripts/web-auto.py record <domain> <flow> --steps-json '[...]'

# 조회
python3 scripts/web-auto.py adapters [--domain X]
python3 scripts/web-auto.py history [--domain X]
python3 scripts/web-auto.py check <domain>
python3 scripts/web-auto.py backends

# 승인
python3 scripts/web-auto.py approve <id> [--reject]
python3 scripts/web-auto.py approvals

# 세션
python3 scripts/web-auto.py session <domain> [--export file] [--import file]
```
