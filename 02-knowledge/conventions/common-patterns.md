---
type: convention
importance: 7
created: 2026-02-25
tags: [patterns, skeleton, api, repository-pattern]
source: manual

---

# Common Patterns

## 시스템 신설 시 문서 필수

새로운 시스템(데몬, DB, 자동화 파이프라인 등)을 만들면 반드시 `02-knowledge/infrastructure/`에 아키텍처 문서를 작성한다. 코드에만 지식이 남으면 새 세션이 맨땅에서 시작하게 된다.

필수 포함 항목:
- DB 위치 및 테이블 구조
- 접근 경로 (어떤 모듈이 어떤 DB를 어떻게 접근하는지)
- 설정 조회/변경 방법
- 데몬/프로세스 상태 확인 방법
- CLAUDE.md 시스템 문서 레퍼런스 테이블에 행 추가

## Skeleton Projects

When implementing new functionality:
1. Search for battle-tested skeleton projects
2. Use parallel agents to evaluate options:
   - Security assessment
   - Extensibility analysis
   - Relevance scoring
   - Implementation planning
3. Clone best match as foundation
4. Iterate within proven structure

## Design Patterns

### Repository Pattern

Encapsulate data access behind a consistent interface:
- Define standard operations: findAll, findById, create, update, delete
- Concrete implementations handle storage details (database, API, file, etc.)
- Business logic depends on the abstract interface, not the storage mechanism
- Enables easy swapping of data sources and simplifies testing with mocks

### API Response Format

Use a consistent envelope for all API responses:
- Include a success/status indicator
- Include the data payload (nullable on error)
- Include an error message field (nullable on success)
- Include metadata for paginated responses (total, page, limit)
