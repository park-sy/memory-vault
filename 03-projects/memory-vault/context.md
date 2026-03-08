---
type: domain-context
project: memory-vault
importance: 8
created: 2026-02-28
tags: [memory-vault, context, domain]

---

# memory-vault — 도메인 컨텍스트

코어팀에 전달할 최소 컨텍스트. 이 파일을 읽으면 프로젝트 작업이 가능하다.

## 프로젝트 요약

AI 에이전트의 옵시디언 기반 장기기억 체계.

## 스택

- **에디터**: Obsidian
- **버전관리**: Git (obsidian-git 플러그인 10분 자동 커밋)
- **포맷**: Markdown + YAML frontmatter + wiki-link

## 아키텍처

- 코어팀/도메인팀/운영팀 구조 ([[04-decisions/002-platform-team-structure]])
- 코어팀 (01-org/core/) + 도메인팀 (03-projects/{name}/)
- 운영팀 (01-org/enabling/) — 오케스트레이터 등 운영/최적화
- 위키링크 기반 상호참조

## Key Paths

- 프로젝트 루트: `/Users/hiyeop/dev/memory-vault/`
- CLAUDE.md: 세션 시작 프로토콜
- pool.sh: `scripts/pool.sh`

## 주요 컨벤션

- 새 파일 생성 시 반드시 frontmatter 포함
- importance 자가 평가 (1-10)
- 관련 노트에 `[[wiki-link]]` 연결
- 디렉토리 구조 가이드: CLAUDE.md 참조

## Related

- [[04-decisions/001-vault-structure]]
- [[04-decisions/002-platform-team-structure]]
