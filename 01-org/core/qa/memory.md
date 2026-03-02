---
type: role-memory
importance: 9
created: 2026-02-28
last_accessed: 2026-03-02
access_count: 2
tags: [qa, core, lessons]
---

# QA Memory
마지막 업데이트: 2026-03-02

## 교훈
- 구현 코드가 없어도 설계 문서 기준으로 DB 스키마, CLI 프레임워크 호환성, 데이터 흐름 검증이 가능하다
- spec.md는 개요 수준, SKILL.md가 구현 기준. 두 문서 간 교차 검증이 필수
- factory-monitor처럼 순수 읽기 전용 feature는 DB 스키마 존재 + 쿼리 실행 가능 여부가 핵심 검증 포인트

## 패턴
- Command-Level Verification 순서: DB 스키마 → 함수 시그니처 호환성 → 데이터 흐름 → 엣지 케이스
- whos-life CLI 프레임워크(`feature_cli.py`)는 service.py의 함수 시그니처를 인트로스펙션하여 자동 CLI 생성
  - `db` 파라미터: 첫 번째 인자 이름이 "db"면 자동 주입
  - Pydantic BaseModel: 두 번째 인자면 argparse 자동 변환
  - `--json`: 모든 method parser에 자동 추가

## 실수/회피
- spec.md만 보고 검증하면 불완전. 반드시 SKILL.md도 교차 확인
- SKILL.md에서 "6개 함수"라 했지만 실제 5개만 나열 — 문서 내 자기모순 주의
