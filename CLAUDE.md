# Memory Vault

AI 에이전트의 장기기억 체계. 옵시디언 vault 구조로 관리.

## 세션 시작 프로토콜

세션 시작 시 아래 순서로 읽을 것:

1. `01-org/head.md` — 상위 지침 (SOUL)
2. `01-org/user.md` — 사용자 정보
3. `05-sessions/` 최신 2개 — 최근 컨텍스트

## 기억 기록 규칙

- 새 기억은 `02-knowledge/` 또는 역할별 `*-memory.md`에 기록
- 3회 이상 검증된 패턴만 `02-knowledge/patterns/`로 승격
- 세션 로그는 `05-sessions/YYYY-MM-DD.md`에 작성
- 증류 대상은 `05-sessions/_distill-queue.md`에 등록

## 디렉토리 구조

| 디렉토리 | 용도 |
|----------|------|
| `00-MOC/` | Maps of Content (진입점, 인덱스) |
| `01-org/` | 조직 구조 (head, user, 부서별 역할/기억) |
| `02-knowledge/` | 공유 지식 (패턴, 스택, 컨벤션, 실수 DB) |
| `03-projects/` | 프로젝트별 컨텍스트 |
| `04-decisions/` | ADR (Architecture Decision Records) |
| `05-sessions/` | 세션 로그 → 증류 → permanent note |
| `06-skills/` | 공유 스킬 (방법론 문서) |
| `templates/` | 노트 템플릿 |

## 위키링크 규칙

- 부서 파일(`_department.md`)에서 `[[위키링크]]`로 상호 참조
- 역할 파일에서는 **절대경로**로 명시 (`--append-system-prompt`용)
- `02-knowledge/`가 부서 간 공유 허브
