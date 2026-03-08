#!/usr/bin/env python3
"""Decision Clone — 상엽 의사결정 복제 시스템 CLI.

Captures, synthesizes, and replays decision patterns.

Usage:
    python3 scripts/decision-clone.py add <category> "<context>" "<chosen>" "<rationale>"
    python3 scripts/decision-clone.py list [--category <cat>] [--pending-review]
    python3 scripts/decision-clone.py stats
    python3 scripts/decision-clone.py seed
    python3 scripts/decision-clone.py synthesize
    python3 scripts/decision-clone.py score <ID> <correct|wrong|partial> ["feedback"]
    python3 scripts/decision-clone.py tag <ID> <tag>
    python3 scripts/decision-clone.py batch-score
    python3 scripts/decision-clone.py clone-review
"""

import argparse
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

VAULT_DIR = Path(__file__).resolve().parent.parent
CLONE_DIR = VAULT_DIR / "07-clone"
DECISION_LOG = CLONE_DIR / "decision-log.md"
PROFILE_MD = CLONE_DIR / "profile.md"
CLONE_DECISIONS = CLONE_DIR / "clone-decisions.md"
SESSIONS_DIR = VAULT_DIR / "05-sessions"

CATEGORIES = {
    "architecture",
    "workflow",
    "tooling",
    "communication",
    "risk-tolerance",
    "trade-offs",
    "uncategorized",
}


# ── Data ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Decision:
    id: str
    category: str
    date: str
    context: str
    options: str
    chosen: str
    rationale: str
    confidence: str = "medium"
    outcome: str = "pending"
    tags: str = ""
    feedback: str = ""

    def with_update(self, **kwargs) -> "Decision":
        """Return a new Decision with updated fields (immutable)."""
        fields = {
            "id": self.id,
            "category": self.category,
            "date": self.date,
            "context": self.context,
            "options": self.options,
            "chosen": self.chosen,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "outcome": self.outcome,
            "tags": self.tags,
            "feedback": self.feedback,
        }
        fields.update(kwargs)
        return Decision(**fields)

    def to_markdown(self) -> str:
        lines = [
            f"### {self.id} | {self.category} | {self.date}",
            f"- **context**: {self.context}",
            f"- **options**: {self.options}",
            f"- **chosen**: {self.chosen}",
            f"- **rationale**: {self.rationale}",
            f"- **confidence**: {self.confidence}",
            f"- **outcome**: {self.outcome}",
            f"- **tags**: {self.tags}",
        ]
        if self.feedback:
            lines.append(f"- **feedback**: {self.feedback}")
        return "\n".join(lines)


# ── Parsing ────────────────────────────────────────────────────────────────


def parse_decisions(path: Path) -> list:
    """Parse decision-log.md into Decision objects."""
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    entries = re.split(r"(?=^### D-\d+)", text, flags=re.MULTILINE)

    decisions = []
    for entry in entries:
        entry = entry.strip()
        if not entry.startswith("### D-"):
            continue

        header_match = re.match(r"### (D-\d+) \| (\S+) \| (\S+)", entry)
        if not header_match:
            continue

        did, category, d_date = header_match.groups()

        def _extract(field_name: str) -> str:
            m = re.search(rf"\*\*{field_name}\*\*:\s*(.+)", entry)
            return m.group(1).strip() if m else ""

        decisions.append(
            Decision(
                id=did,
                category=category,
                date=d_date,
                context=_extract("context"),
                options=_extract("options"),
                chosen=_extract("chosen"),
                rationale=_extract("rationale"),
                confidence=_extract("confidence") or "medium",
                outcome=_extract("outcome") or "pending",
                tags=_extract("tags"),
                feedback=_extract("feedback"),
            )
        )

    return decisions


def next_id(decisions: list) -> str:
    """Generate next D-xxx ID."""
    if not decisions:
        return "D-001"
    nums = [int(d.id.split("-")[1]) for d in decisions]
    return f"D-{max(nums) + 1:03d}"


def _build_frontmatter(created: str, total: int) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "type: clone-data\n"
        "subtype: decision-log\n"
        f"created: {created}\n"
        f"last_updated: {today}\n"
        f"total_entries: {total}\n"
        "tags: [decision-clone, decisions]\n"
        "---"
    )


def write_decisions(path: Path, decisions: list, created: str = "") -> None:
    """Write decisions to markdown file."""
    today = date.today().isoformat()
    if not created:
        created = today

    parts = [
        _build_frontmatter(created, len(decisions)),
        "",
        "# Decision Log",
        "",
    ]

    for d in decisions:
        parts.append(d.to_markdown())
        parts.append("")

    path.write_text("\n".join(parts), encoding="utf-8")


# ── Seed Data ──────────────────────────────────────────────────────────────


def _build_seeds() -> list:
    """Pre-extracted decisions from session history."""
    return [
        # ── 2026-02-22 ──
        Decision(
            "", "architecture", "2026-02-22",
            "프레임워크 비교 후 whos-life UI 프레임워크 선택",
            "NiceGUI, FastAPI+React, Reflex, FastHTML, Streamlit, Gradio",
            "NiceGUI 유지",
            "에이전트 편의성 9/10, 같은 프로세스 MCP+UI",
            "high", "pending", "framework, nicegui, whos-life",
        ),
        Decision(
            "", "architecture", "2026-02-22",
            "멀티 에이전트에서 코봉을 별도 에이전트로 분리할지",
            "별도 에이전트, sub-agent, 단일 에이전트",
            "sub-agent 방식",
            "같은 모델/머신이면 분리 불필요. 모델/권한 다를 때만 분리.",
            "high", "pending", "multi-agent, agent-architecture",
        ),
        Decision(
            "", "architecture", "2026-02-22",
            "LLM 실행 범위 결정",
            "모든 작업 LLM, 판단만 LLM + 실행은 코드, 코드 전부",
            "LLM은 판단만, 실행은 코드",
            "토큰 절약 + 안정성. Level 0(코드)/1(정형 LLM)/2(비정형 LLM)",
            "high", "pending", "llm-boundary, 3-tier",
        ),
        Decision(
            "", "architecture", "2026-02-22",
            "에이전트 분리 기준 정의",
            "기능별 분리, 모델/권한별 분리, 단일 에이전트",
            "모델/권한이 다를 때만 분리",
            "같은 모델/머신이면 sub-agent로 충분",
            "high", "pending", "multi-agent, agent-architecture",
        ),
        Decision(
            "", "workflow", "2026-02-22",
            "Skill과 Code의 관계 정의",
            "skill만 사용, code만 사용, skill-first",
            "Skill-first (skill로 검증 → 반복 패턴만 code로)",
            "skill = 프로토타입/설계서, code = 최적화된 실행. 성숙할수록 code 비중 증가.",
            "high", "pending", "skill-first, pipeline",
        ),
        Decision(
            "", "risk-tolerance", "2026-02-22",
            "git push 자동화 수준",
            "자동 push, 반자동, 수동만",
            "반드시 상엽 확인 후 push",
            "코드 변경은 리뷰 필수. 자동화 범위에 push 제외.",
            "high", "pending", "git, safety",
        ),
        Decision(
            "", "tooling", "2026-02-22",
            "OpenClaw config 수정 방법",
            "직접 수정, CLI 사용",
            "CLI 사용 원칙",
            "직접 수정 시 토큰 공백/중복 발생. CLI가 안전.",
            "medium", "pending", "openclaw, config",
        ),
        # ── 2026-02-23 ──
        Decision(
            "", "architecture", "2026-02-23",
            "코봉(coder agent) 유지 여부",
            "유지, 제거",
            "제거 (sub-agent로 대체)",
            "같은 모델/머신이면 별도 에이전트 불필요",
            "high", "pending", "multi-agent, agent-architecture",
        ),
        Decision(
            "", "tooling", "2026-02-23",
            "cron 스케줄러 모델 선택",
            "Flash, Opus",
            "Opus",
            "Flash rate limit 문제 발생. Opus가 안정적.",
            "medium", "pending", "cron, model-selection",
        ),
        # ── 2026-02-25 ──
        Decision(
            "", "workflow", "2026-02-25",
            "Feature pipeline에 계획 승인 게이트 도입 여부",
            "승인 없이 자동, Plan Mode(승인 게이트)",
            "Plan Mode 도입",
            "designing/coding 진입 시 plan 생성 → 사용자 승인 → 실행. 4개 승인 게이트.",
            "high", "pending", "plan-mode, pipeline",
        ),
        Decision(
            "", "trade-offs", "2026-02-25",
            "설계 원칙 우선순위",
            "기능 완성도 우선, 사용자 입력 우선, 기술 우수성 우선",
            "사용자 입력 우선 + 점진적 보강",
            "초안 먼저 내고 보강하는 방식. reject 히스토리 자동 누적.",
            "high", "pending", "design-principles, trade-offs",
        ),
        Decision(
            "", "architecture", "2026-02-25",
            "Feature pipeline 세션 구조",
            "단일 세션, planner+worker 분리, per-feature 세션",
            "3-Tier (planner 1개 + worker N개)",
            "planner가 spec 전담, worker가 구현. scheduler가 배정.",
            "high", "pending", "3-tier, pipeline, multi-session",
        ),
        # ── 2026-02-28 ──
        Decision(
            "", "architecture", "2026-02-28",
            "AI 에이전트 조직 구조 선택",
            "Hub-and-Spoke, Platform Team (Team Topologies)",
            "Platform Team 구조 채택",
            "코어 전문팀 + 가벼운 도메인팀 + 자유 소통. AI 고유 이점으로 단점 전부 해소.",
            "high", "pending", "team-topologies, organization, platform-team",
        ),
        Decision(
            "", "communication", "2026-02-28",
            "팀 간 커뮤니케이션 구조",
            "Hub-and-Spoke(오케스트레이터 경유), 자유 소통(direct)",
            "자유 소통 (Collaboration Mode)",
            "옵시디언 wiki-link로 지식 공유, 직접 참조 가능. 병목 제거.",
            "high", "pending", "communication, team-topologies",
        ),
        Decision(
            "", "communication", "2026-02-28",
            "조직 구조 명칭 선택",
            "헥사고날 아키텍처, Platform Team (Team Topologies)",
            "Platform Team (Team Topologies)",
            "헥사고날은 소프트웨어 Ports & Adapters 패턴 → 부적합. Team Topologies가 정확.",
            "high", "pending", "naming, team-topologies",
        ),
        Decision(
            "", "trade-offs", "2026-02-28",
            "Platform Team 단점 해소 전략",
            "단점 수용, 구조 변경, AI 이점 활용",
            "AI 고유 이점으로 전부 해소",
            "세션 복제, 컨텍스트 스위칭 0, 메모리 공유, 에고 없음, 롤백 가능.",
            "high", "pending", "ai-advantage, team-topologies",
        ),
    ]


# ── Commands ───────────────────────────────────────────────────────────────


def cmd_add(args) -> None:
    """Add a new decision entry."""
    category = args.category
    if category not in CATEGORIES:
        print(f"Error: category must be one of {sorted(CATEGORIES)}")
        sys.exit(1)

    decisions = parse_decisions(DECISION_LOG)
    new_id = next_id(decisions)
    created = decisions[0].date if decisions else date.today().isoformat()

    decision = Decision(
        id=new_id,
        category=category,
        date=date.today().isoformat(),
        context=args.context,
        options=args.options if args.options else "-",
        chosen=args.chosen,
        rationale=args.rationale,
        confidence=args.confidence or "medium",
        tags=args.tags or category,
    )

    updated = [*decisions, decision]
    write_decisions(DECISION_LOG, updated, created)
    print(f"Added {new_id} ({category}): {args.chosen}")


def cmd_list(args) -> None:
    """List decisions with optional filters."""
    decisions = parse_decisions(DECISION_LOG)

    if not decisions:
        print("No decisions found.")
        return

    if args.category:
        decisions = [d for d in decisions if d.category == args.category]

    if args.pending_review:
        decisions = [d for d in decisions if d.outcome == "pending"]

    for d in decisions:
        icon = {
            "correct": "+",
            "wrong": "x",
            "partial": "~",
        }.get(d.outcome, "?")
        print(f"  [{icon}] {d.id} | {d.category:16s} | {d.chosen[:50]}")

    print(f"\n  Total: {len(decisions)}")


def cmd_stats(args) -> None:
    """Show decision statistics."""
    all_decisions = parse_decisions(DECISION_LOG)

    if not all_decisions:
        print("No decisions found.")
        return

    exploratory = [d for d in all_decisions if not _is_decision(d)]
    decisions = [d for d in all_decisions if _is_decision(d)]

    cat_counts = Counter(d.category for d in decisions)
    outcome_counts = Counter(d.outcome for d in decisions)
    reviewed = [d for d in decisions if d.outcome in ("correct", "wrong", "partial")]
    total = len(decisions)

    cat_accuracy = {}
    for cat in cat_counts:
        cat_reviewed = [
            d for d in decisions
            if d.category == cat and d.outcome in ("correct", "wrong", "partial")
        ]
        if cat_reviewed:
            score = sum(
                1.0 if d.outcome == "correct" else 0.5 if d.outcome == "partial" else 0.0
                for d in cat_reviewed
            )
            cat_accuracy[cat] = score / len(cat_reviewed)
        else:
            cat_accuracy[cat] = None

    print("Decision Clone Stats")
    print("=" * 50)
    print(f"  Total entries: {len(all_decisions)}")
    if exploratory:
        print(f"  Exploratory (filtered): {len(exploratory)}")
    print(f"  Valid decisions: {total}")
    if total:
        print(f"  Reviewed: {len(reviewed)} ({len(reviewed)/total*100:.0f}%)")
    print()

    print("By Category:")
    for cat in sorted(cat_counts, key=cat_counts.get, reverse=True):
        acc = cat_accuracy[cat]
        acc_str = f"accuracy: {acc:.0%}" if acc is not None else "not reviewed"
        print(f"  {cat:16s}: {cat_counts[cat]:3d} ({acc_str})")

    print()
    print("By Outcome:")
    for outcome in ["correct", "partial", "wrong", "pending"]:
        if outcome in outcome_counts:
            print(f"  {outcome:10s}: {outcome_counts[outcome]}")


def cmd_seed(args) -> None:
    """Bootstrap decisions from existing session files."""
    decisions = parse_decisions(DECISION_LOG)

    if decisions:
        print(f"Decision log already has {len(decisions)} entries.")
        print("Seed only runs on an empty log. Use 'add' for new entries.")
        return

    seeds = _build_seeds()
    numbered = []
    for seed in seeds:
        sid = next_id(numbered)
        numbered.append(seed.with_update(id=sid))

    created = numbered[0].date if numbered else date.today().isoformat()
    write_decisions(DECISION_LOG, numbered, created)
    print(f"Seeded {len(numbered)} decisions from session history.")


def _is_decision(d: Decision) -> bool:
    """exploratory 태그가 있으면 결정이 아닌 탐색."""
    return "exploratory" not in d.tags


def cmd_synthesize(args) -> None:
    """Synthesize profile from decision log."""
    all_decisions = parse_decisions(DECISION_LOG)

    if not all_decisions:
        print("No decisions to synthesize.")
        return

    # exploratory 필터링
    decisions = [d for d in all_decisions if _is_decision(d)]
    skipped = len(all_decisions) - len(decisions)
    if skipped:
        print(f"Filtered {skipped} exploratory entries.")

    by_cat = defaultdict(list)
    for d in decisions:
        by_cat[d.category].append(d)

    reviewed = [d for d in decisions if d.outcome in ("correct", "wrong", "partial")]
    overall = 0.0
    if reviewed:
        overall = sum(
            1.0 if d.outcome == "correct" else 0.5 if d.outcome == "partial" else 0.0
            for d in reviewed
        ) / len(reviewed)

    sections = []
    for cat in sorted(by_cat.keys()):
        cat_decisions = by_cat[cat]
        cat_reviewed = [
            d for d in cat_decisions
            if d.outcome in ("correct", "wrong", "partial")
        ]

        if cat_reviewed:
            cat_acc = sum(
                1.0 if d.outcome == "correct" else 0.5 if d.outcome == "partial" else 0.0
                for d in cat_reviewed
            ) / len(cat_reviewed)
            acc_str = f"{cat_acc:.2f}"
        else:
            acc_str = "N/A"

        # Extract tendencies
        tendency_counts = Counter()
        tendency_ids = defaultdict(list)
        for d in cat_decisions:
            tendency_counts[d.chosen] += 1
            tendency_ids[d.chosen].append(d.id)

        total_cat = len(cat_decisions)
        section_lines = [
            f"## {cat.replace('-', ' ').title()} ({len(cat_decisions)} decisions, accuracy: {acc_str})",
            "",
            "| 성향 | 빈도 | 신뢰도 | 근거 |",
            "|------|------|--------|------|",
        ]

        for chosen, count in tendency_counts.most_common():
            freq = f"{count}/{total_cat}"
            ids = tendency_ids[chosen]

            relevant_reviewed = [
                d for d in cat_decisions
                if d.chosen == chosen and d.outcome in ("correct", "wrong", "partial")
            ]
            if relevant_reviewed:
                conf = sum(
                    1.0 if d.outcome == "correct" else 0.5 if d.outcome == "partial" else 0.0
                    for d in relevant_reviewed
                ) / len(relevant_reviewed)
                conf_str = f"{conf:.2f}"
            else:
                conf_str = f"{count/total_cat:.2f}"

            id_refs = ", ".join(ids[:3])
            if len(ids) > 3:
                id_refs += f" +{len(ids) - 3}"

            section_lines.append(f"| {chosen} | {freq} | {conf_str} | {id_refs} |")

        sections.append("\n".join(section_lines))

    today = date.today().isoformat()
    profile_lines = [
        "---",
        "type: clone-data",
        "subtype: profile",
        "status: inactive",
        f"last_synthesized: {today}",
        f"total_decisions: {len(decisions)}",
        f"overall_accuracy: {overall:.2f}",
        "tags: [decision-clone, profile]",
        "---",
        "",
        "# Decision Profile — 상엽",
        "",
    ]

    for section in sections:
        profile_lines.append(section)
        profile_lines.append("")

    PROFILE_MD.write_text("\n".join(profile_lines), encoding="utf-8")
    print(f"Synthesized profile from {len(decisions)} decisions.")
    print(f"Categories: {len(by_cat)}")
    if reviewed:
        print(f"Overall accuracy: {overall:.0%}")
    else:
        print("No reviewed decisions yet.")


def cmd_score(args) -> None:
    """Score a decision outcome."""
    decisions = parse_decisions(DECISION_LOG)

    target_idx = None
    for i, d in enumerate(decisions):
        if d.id == args.id.upper():
            target_idx = i
            break

    if target_idx is None:
        print(f"Error: {args.id} not found.")
        sys.exit(1)

    if args.outcome not in ("correct", "wrong", "partial"):
        print("Error: outcome must be correct, wrong, or partial")
        sys.exit(1)

    target = decisions[target_idx]
    updated_target = target.with_update(
        outcome=args.outcome,
        feedback=args.feedback if args.feedback else target.feedback,
    )

    updated = [*decisions[:target_idx], updated_target, *decisions[target_idx + 1:]]
    created = updated[0].date if updated else date.today().isoformat()
    write_decisions(DECISION_LOG, updated, created)

    msg = f"Scored {updated_target.id}: {args.outcome}"
    if args.feedback:
        msg += f" — {args.feedback}"
    print(msg)


def cmd_tag(args) -> None:
    """Add a tag to an existing decision entry."""
    decisions = parse_decisions(DECISION_LOG)
    target_idx = None
    for i, d in enumerate(decisions):
        if d.id == args.id.upper():
            target_idx = i
            break

    if target_idx is None:
        print(f"Error: {args.id} not found.")
        sys.exit(1)

    target = decisions[target_idx]
    existing_tags = {t.strip() for t in target.tags.split(",") if t.strip()}
    new_tag = args.tag.strip()
    if new_tag in existing_tags:
        print(f"{target.id} already has tag '{new_tag}'.")
        return

    updated_tags = ", ".join(sorted(existing_tags | {new_tag}))
    updated_target = target.with_update(tags=updated_tags)
    updated = [*decisions[:target_idx], updated_target, *decisions[target_idx + 1:]]
    created = updated[0].date if updated else date.today().isoformat()
    write_decisions(DECISION_LOG, updated, created)
    print(f"Tagged {updated_target.id}: {updated_tags}")


def cmd_batch_score(args) -> None:
    """Interactive batch scoring of pending decisions."""
    decisions = parse_decisions(DECISION_LOG)
    pending = [d for d in decisions if d.outcome == "pending" and _is_decision(d)]

    if not pending:
        print("No pending decisions to score.")
        return

    print(f"Pending decisions: {len(pending)}")
    print("For each: [c]orrect / [w]rong / [p]artial / [s]kip / [q]uit\n")

    scored = 0
    for d in pending:
        print(f"  {d.id} | {d.category} | {d.date}")
        print(f"    Context: {d.context}")
        print(f"    Chosen: {d.chosen}")
        print(f"    Rationale: {d.rationale}")

        try:
            choice = input("  Score> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            break

        if choice == "q":
            break
        if choice == "s":
            print()
            continue

        outcome_map = {"c": "correct", "w": "wrong", "p": "partial"}
        outcome = outcome_map.get(choice)
        if not outcome:
            print(f"  Unknown input '{choice}', skipping.\n")
            continue

        # Re-parse to avoid stale state
        fresh = parse_decisions(DECISION_LOG)
        fresh_idx = None
        for i, fd in enumerate(fresh):
            if fd.id == d.id:
                fresh_idx = i
                break

        if fresh_idx is None:
            print(f"  {d.id} disappeared, skipping.\n")
            continue

        updated_target = fresh[fresh_idx].with_update(outcome=outcome)
        updated = [*fresh[:fresh_idx], updated_target, *fresh[fresh_idx + 1:]]
        created = updated[0].date if updated else date.today().isoformat()
        write_decisions(DECISION_LOG, updated, created)
        scored += 1
        print(f"  → {outcome}\n")

    print(f"Scored {scored} decisions.")


def cmd_clone_review(args) -> None:
    """Show clone decisions pending review."""
    if not CLONE_DECISIONS.exists():
        print("No clone decisions file.")
        return

    decisions = parse_decisions(CLONE_DECISIONS)
    pending = [d for d in decisions if d.outcome == "pending"]

    if not pending:
        print("No clone decisions pending review.")
        return

    print(f"Clone decisions pending review: {len(pending)}\n")
    for d in pending:
        print(f"  {d.id} | {d.category} | {d.date}")
        print(f"    Context: {d.context}")
        print(f"    Chosen: {d.chosen}")
        print(f"    Rationale: {d.rationale}")
        print()


# ── Main ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decision Clone — 상엽 의사결정 복제 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add a new decision")
    p_add.add_argument("category", choices=sorted(CATEGORIES))
    p_add.add_argument("context", help="Decision context")
    p_add.add_argument("chosen", help="What was chosen")
    p_add.add_argument("rationale", help="Why it was chosen")
    p_add.add_argument("--options", default="-", help="Available options")
    p_add.add_argument(
        "--confidence", default="medium", choices=["low", "medium", "high"]
    )
    p_add.add_argument("--tags", default="", help="Comma-separated tags")

    # list
    p_list = sub.add_parser("list", help="List decisions")
    p_list.add_argument("--category", choices=sorted(CATEGORIES))
    p_list.add_argument("--pending-review", action="store_true")

    # stats
    sub.add_parser("stats", help="Show statistics")

    # seed
    sub.add_parser("seed", help="Bootstrap from session history")

    # synthesize
    sub.add_parser("synthesize", help="Generate profile from decisions")

    # score
    p_score = sub.add_parser("score", help="Score a decision outcome")
    p_score.add_argument("id", help="Decision ID (e.g., D-001)")
    p_score.add_argument("outcome", choices=["correct", "wrong", "partial"])
    p_score.add_argument(
        "feedback", nargs="?", default="", help="Optional feedback"
    )

    # tag
    p_tag = sub.add_parser("tag", help="Add a tag to a decision")
    p_tag.add_argument("id", help="Decision ID (e.g., D-018)")
    p_tag.add_argument("tag", help="Tag to add (e.g., exploratory)")

    # batch-score
    sub.add_parser("batch-score", help="Interactive batch scoring of pending decisions")

    # clone-review
    sub.add_parser("clone-review", help="Review pending clone decisions")

    args = parser.parse_args()

    CLONE_DIR.mkdir(parents=True, exist_ok=True)

    commands = {
        "add": cmd_add,
        "list": cmd_list,
        "stats": cmd_stats,
        "seed": cmd_seed,
        "synthesize": cmd_synthesize,
        "score": cmd_score,
        "tag": cmd_tag,
        "batch-score": cmd_batch_score,
        "clone-review": cmd_clone_review,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
