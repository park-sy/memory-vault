---
type: decision
id: "001"
status: accepted
date: "2026-02-27"
participants: ["상엽", "얍"]
---

# ADR-001: Memory Vault 구조 채택

## Context
AI 에이전트의 기억이 세션마다 초기화되는 문제.
OpenClaw에서 Claude Code 단일 체계로 전환하면서 장기기억 시스템 필요.

## Decision
옵시디언 vault 구조로 장기기억을 관리한다.
- ~/dev/memory-vault/에 git 저장소
- 위키링크 기반 상호참조
- 세션 → 증류 → permanent note 파이프라인
- 부서별 조직 구조 (ops/product/engineering)

## Consequences
- 옵시디언 그래프 뷰로 지식 연결 시각화 가능
- git으로 버전 관리 + 원격 백업
- 세션 시작 시 역할 파일 + memory.md 로드로 빠른 컨텍스트 복구
- ~/.claude/rules/common/은 유지하되 vault에서도 관리
