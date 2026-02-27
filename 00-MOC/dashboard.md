---
type: moc
purpose: "기억 상태 대시보드 — Dataview 자동 렌더링"
---

# Memory Dashboard

> Dataview 커뮤니티 플러그인 필요. Obsidian에서 열면 자동 렌더링.

---

## Hot Memories (importance >= 8, access_count >= 5)

자주 참조하는 핵심 기억.

```dataview
TABLE importance, access_count, last_accessed, tags
FROM ""
WHERE importance >= 8 AND access_count >= 5
SORT access_count DESC
```

---

## Warm Memories (최근 14일 접근, importance >= 5)

활발하게 사용 중인 기억.

```dataview
TABLE importance, access_count, last_accessed, type
FROM ""
WHERE last_accessed >= date(today) - dur(14 days) AND importance >= 5
SORT last_accessed DESC
```

---

## Cold Memories (30일 이상 미접근)

오래 참조하지 않은 기억. 리뷰 필요.

```dataview
TABLE importance, access_count, last_accessed, type
FROM ""
WHERE last_accessed AND last_accessed < date(today) - dur(30 days)
SORT last_accessed ASC
```

---

## Archive Candidates (importance <= 3, access_count <= 2, 60일 미접근)

정리 대상 후보.

```dataview
TABLE importance, access_count, last_accessed, type
FROM ""
WHERE importance <= 3 AND access_count <= 2 AND last_accessed < date(today) - dur(60 days)
SORT importance ASC
```

---

## Undistilled Sessions (distilled = false)

증류 대기 중인 세션 로그.

```dataview
TABLE created, tags
FROM "05-sessions"
WHERE distilled = false AND type = "session"
SORT created DESC
```

---

## Tag Distribution

태그별 노트 개수.

```dataview
TABLE length(rows) AS "Count"
FROM ""
WHERE tags
FLATTEN tags AS tag
GROUP BY tag
SORT length(rows) DESC
```

---

## All Tracked Memories

전체 추적 기억 목록 (importance 순).

```dataview
TABLE type, importance, access_count, last_accessed
FROM ""
WHERE importance
SORT importance DESC, access_count DESC
```
