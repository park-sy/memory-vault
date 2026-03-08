---
type: skill
importance: 8
created: "2026-03-06"
tags: [domain-team, onboarding, checklist, infrastructure]

---

# Domain Team Onboarding — 도메인팀 온보딩

새 도메인팀을 생성할 때 따르는 체크리스트. 모든 도메인팀 유형(project, experimentation, research)에 적용.

## 도메인팀 유형별 역할

| 유형 | 전문가 역할 | 역할 파일 | 기억 파일 |
|------|-------------|-----------|-----------|
| project | developer | `developer.md` | `developer-memory.md` |
| experimentation | specialist | `specialist.md` | `specialist-memory.md` |
| research | analyst | `analyst.md` | `analyst-memory.md` |

## 체크리스트

### 1. 파일 생성

- [ ] `03-projects/{name}/context.md` — 도메인 컨텍스트
  - project: 스택, 구조, 기능 목록
  - experimentation: 프로필, 가설, 검증 현황
  - research: 주제 정의, 범위, 핵심 질문
- [ ] `03-projects/{name}/{role}.md` — 전문가 역할 정의
  - "읽어야 할 파일" 섹션 포함
  - 핵심 책임, 경계, 완료 키워드 정의
- [ ] `03-projects/{name}/{role}-memory.md` — 누적 기억 (빈 파일 + frontmatter)
- [ ] 유형별 추가 파일:
  - experimentation: `experiment-log.md`, `methods/` 디렉토리, `methods/_index.md`
  - project: `backlog.md` (선택)
  - research: `findings/` 디렉토리 (선택)

### 2. 인프라 등록

- [ ] `scripts/pool.sh` — `_resolve_role()` case문에 역할 추가:
  ```bash
  {name}-{role})
      echo "${VAULT_DIR}/03-projects/{name}/{role}.md"
      ;;
  ```
  + help 텍스트 역할 목록에 추가
- [ ] `scripts/access_tracker.py` — 역할 감지 자동 (코드 수정 불필요)
  - `{role}-memory.md` 파일명이 `specialist-memory.md` 또는 `developer-memory.md`이면 자동 감지
  - 새 역할 유형(analyst 등) 추가 시 `_infer_role()` 확장 필요
- [ ] Telegram 채널 생성 (토픽 생성 + .env 등록 + bridge 재시작 + 테스트):
  ```bash
  bash scripts/telegram-channel.sh add {name}
  ```

### 3. 시스템 등록

- [ ] `CLAUDE.md` — 역할 전환 섹션에 트리거 추가:
  ```markdown
  - "{트리거}" → `03-projects/{name}/{role}.md` 읽고 {role} 모드
  ```
- [ ] `02-knowledge/infrastructure/platform-team-operations.md`:
  - 역할 진입/전환 테이블에 추가
  - 워커 풀 사용 가능 역할 목록에 추가
- [ ] `04-decisions/002-platform-team-structure.md` — 도메인팀 유형 테이블에 해당 유형 있는지 확인

### 4. 검증

- [ ] 역할 전환 트리거로 진입 확인 (role.md + 연관 파일 로드)
- [ ] `pool.sh init 1 --role {name}-{role}` 워커 생성 확인
- [ ] Telegram 채널에 테스트 메시지 전송 확인:
  ```bash
  python3 scripts/notify.py "test" --channel {name}
  ```
- [ ] access_tracker에서 `{role}-memory.md` 읽기 시 `{name}-{role}` 역할 감지 확인

## 예시: learning 도메인팀

```
1. 파일: 03-projects/learning/{context, specialist, specialist-memory, experiment-log}.md + methods/
2. pool.sh: learning-specialist case 추가
3. Telegram: create-topic "learning" → .env에 TELEGRAM_TOPIC_LEARNING={id}
4. CLAUDE.md: "학습 해줘" / "러닝 해줘" 트리거
5. 검증: pool.sh init 1 --role learning-specialist
```

## Related

- [[02-knowledge/infrastructure/platform-team-operations]] — 팀 운영 가이드
- [[04-decisions/002-platform-team-structure]] — 팀 구조 결정
- [[02-knowledge/infrastructure/communication-system]] — 통신 체계
