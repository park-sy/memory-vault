---
type: role-memory
importance: 9
created: 2026-02-28
last_accessed: 2026-03-02
access_count: 2
tags: [coder, core, lessons]
---

# Coder Memory
마지막 업데이트: 2026-03-02

## 교훈
- 외부 SQLite DB 읽기: `PRAGMA query_only=ON`으로 안전하게 읽기 전용 보장
- factory-monitor처럼 Level 0 전체인 feature는 SKILL.md 불필요 — service.py만으로 충분

## 패턴
- 외부 DB 접근: `sqlite3.connect()` 직접 사용, `db` 파라미터는 메인 productivity.db용
- PID 체크: `os.kill(pid, 0)` (시그널 0 = 존재 확인만)
- tmux 세션 확인: `tmux ls -F '#{session_name}'` subprocess
- `_` prefix 함수는 CLI에 노출 안 됨 → 내부 헬퍼에 활용

## 실수/회피
- (아직 없음)
