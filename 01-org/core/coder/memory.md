---
type: role-memory
importance: 9
created: 2026-02-28
tags: [coder, core, lessons]

---

# Coder Memory
마지막 업데이트: 2026-03-03

## 교훈
- 외부 SQLite DB 읽기: `PRAGMA query_only=ON`으로 안전하게 읽기 전용 보장
- factory-monitor처럼 Level 0 전체인 feature는 SKILL.md 불필요 — service.py만으로 충분

## 패턴
- 외부 DB 접근: `sqlite3.connect()` 직접 사용, `db` 파라미터는 메인 productivity.db용
- PID 체크: `os.kill(pid, 0)` (시그널 0 = 존재 확인만)
- tmux 세션 확인: `tmux ls -F '#{session_name}'` subprocess
- `_` prefix 함수는 CLI에 노출 안 됨 → 내부 헬퍼에 활용

## 실수/회피

### factory-monitor 제어판 강화 (2026-03-02) — 상엽 피드백

| # | 피드백 | 원인 | 수정 |
|---|--------|------|------|
| 1 | 다크모드에서 tmux 명령어가 안 보임 | background: #f5f5f5 하드코딩 | rgba(128,128,128,0.15) 반투명으로 변경 |
| 2 | 데몬 시작 중인지 알 수 없음 | PID 기반 체크만 존재, 중간 상태 미구분 | (미해결 — 향후 개선) |
| 3 | telegram_bridge 모니터링 안 됨 | 대시보드에 bridge 상태 체크 자체가 없었음 | tmux 세션 체크 + 시작/종료 추가 |
| 4 | 데몬/브릿지 개별 제어가 혼란 | 둘은 항상 같이 켜야 하는데 분리됨 | 시스템 한 버튼으로 통합 |
| 5 | MsgBus 30 미읽음 — 이유 불명 | 브릿지 꺼져서 아웃바운드가 쌓인 건데 원인 설명 없음 | (미해결 — 원인 힌트 표시 필요) |
| 6 | 전반적으로 사용자 친화적이지 않음 | 개발자 시점으로 만들고 사용자 시점 검증 안 함 | 패턴 문서화 → ui-ux-checklist |

### 상위 교훈
- "동작하는 코드"와 "사용자가 쓸 수 있는 코드"는 다르다
- 정보 풍부성 + 세밀한 조절 가능성이 코드 품질의 핵심 기준
- MVP라도 사용자 시점에서 충분한 정보와 제어를 제공해야 한다
