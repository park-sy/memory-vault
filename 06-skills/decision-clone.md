---
type: skill
importance: 8
created: 2026-02-28
tags: [decision-clone, methodology, automation]
last_accessed: 2026-02-28
access_count: 1
---

# Decision Clone — 의사결정 복제 방법론

상엽의 의사결정 패턴을 캡처 → 합성 → 실행 → 리뷰하는 4단계 사이클.

## 개요

```
CAPTURE (세션 중)  →  SYNTHESIZE (주기적)  →  EXECUTE (클론 모드)  →  REVIEW (스코어링)
decision-log.md       profile.md              clone-decisions.md       score 커맨드
```

**클론은 새 역할이 아니라 기존 역할 위에 얹는 행동 레이어.**
`head.md`처럼 모든 역할에 적용된다.

## Phase 1: Capture

### 대상
세션 중 상엽이 내리는 모든 의미 있는 결정:
- 선택 (A vs B)
- 방향 설정 ("이쪽으로 가자")
- reject / approve
- trade-off 판단

### 카테고리 (6종)

| 카테고리 | 설명 | 예시 |
|----------|------|------|
| architecture | 구조, 패턴, 시스템 설계 | 에이전트 분리 기준, 프레임워크 선택 |
| workflow | 프로세스, 파이프라인, 흐름 | Plan Mode 도입, Skill-first |
| tooling | 도구, 모델, 설정 선택 | CLI 사용 원칙, 모델 선택 |
| communication | 소통 구조, 명칭, 문서화 | 자유 소통, 명칭 교정 |
| risk-tolerance | 안전/위험 수용 범위 | git push 수동, 자동화 범위 |
| trade-offs | 우선순위, 절충, 원칙 | 사용자 입력 우선, AI 이점 활용 |

### 엔트리 포맷

```markdown
### D-001 | architecture | 2026-02-22
- **context**: 멀티 에이전트에서 코봉을 별도 에이전트로 분리할지
- **options**: 별도 에이전트, sub-agent, 단일 에이전트
- **chosen**: sub-agent
- **rationale**: 같은 모델/머신이면 분리 불필요. 모델/권한 다를 때만 분리.
- **confidence**: high
- **outcome**: pending
- **tags**: multi-agent, agent-architecture
```

### CLI

```bash
# 수동 추가
python3 scripts/decision-clone.py add architecture "컨텍스트" "선택" "이유"

# 세션 히스토리에서 부트스트랩 (최초 1회)
python3 scripts/decision-clone.py seed
```

### 세션 중 캡처 규칙
- 상엽이 선택/방향/승인/거부를 표현하면 즉시 기록
- 사소한 UI 선호 등은 제외 (importance < 3 수준)
- 같은 결정의 재확인은 기존 엔트리에 feedback 추가

## Phase 2: Synthesize

축적된 개별 결정 → 카테고리별 성향(tendency) 프로필 생성.

### 프로세스
1. decision-log.md의 모든 엔트리 파싱
2. 카테고리별 그룹핑
3. 빈도 + reviewed outcome 기반 성향 추출
4. 신뢰도 계산: `(correct + 0.5 * partial) / total_reviewed`
5. `07-clone/profile.md` 생성

### CLI

```bash
python3 scripts/decision-clone.py synthesize
```

### 실행 시점
- 결정 10개 이상 누적 시
- 스코어링 5개 이상 추가 시
- 상엽이 명시적으로 요청 시

## Phase 3: Execute (향후)

profile.md의 `status: active`일 때 작동.

### 신뢰도별 분기

| 신뢰도 | 행동 | 예시 |
|--------|------|------|
| >= 0.8 | 자동 결정 + clone-decisions.md 기록 | "단순한 솔루션 우선 (0.88)" |
| 0.5~0.8 | 결정 + 플래그 표시 (상엽 주목) | "중간 신뢰도: ..." |
| < 0.5 | 상엽에게 직접 질문 | "아직 패턴 부족: ..." |

### 기록
모든 자율 결정 → `07-clone/clone-decisions.md`에 기록.

## Phase 4: Review (향후)

상엽이 클론 결정을 평가하고 피드백.

### CLI

```bash
# 리뷰 대기열 확인
python3 scripts/decision-clone.py clone-review

# 스코어링
python3 scripts/decision-clone.py score D-001 correct
python3 scripts/decision-clone.py score D-002 wrong "이건 복잡한 솔루션이 맞았음"
python3 scripts/decision-clone.py score D-003 partial "방향은 맞지만 세부 틀림"

# 통계 확인
python3 scripts/decision-clone.py stats
```

### 피드백 루프
score → 재 synthesize → 신뢰도 조정 → 더 정확한 자율 결정

## 파일 구조

```
07-clone/
├── decision-log.md       ← 상엽 의사결정 원본 로그
├── profile.md            ← 합성된 성향 프로필 (status: inactive/active)
└── clone-decisions.md    ← 클론 대리 결정 기록

06-skills/
└── decision-clone.md     ← 이 파일 (방법론)

scripts/
└── decision-clone.py     ← CLI 도구
```

## 관련 문서
- [[07-clone/decision-log|Decision Log]]
- [[07-clone/profile|Decision Profile]]
- [[07-clone/clone-decisions|Clone Decisions]]
