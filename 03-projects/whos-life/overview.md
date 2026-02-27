---
type: project
name: whos-life
status: active
stack: ["NiceGUI", "SQLite WAL", "MCP", "Tailscale"]
importance: 8
last_accessed: 2026-02-27
access_count: 1
tags: [project, productivity, ai-agent, local-first]
---

# whos-life

개인 생산성 플랫폼 + AI 에이전트 시스템.

## Architecture
- NiceGUI + MCP + SQLite WAL + Tailscale, 로컬 우선
- Feature = service.py(@tool) + render.py(NiceGUI)
- 3단계 실행 모델: Level 0(코드), Level 1(정형 LLM), Level 2(비정형 LLM)

## Key Paths
- `/Users/hiyeop/dev/whos-life/`
- DB: `db/productivity.db`
- Features: `features/{category}/{name}/`

## Related
- [[03-projects/whos-life/ideas-backlog]]
- [[06-skills/feature-pipeline]]
