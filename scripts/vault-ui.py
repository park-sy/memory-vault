#!/usr/bin/env python3
"""Memory Vault GUI Dashboard — Static HTML Generator.

Reads vault frontmatter + tmux session state and generates a single HTML
dashboard file with two tabs: Dashboard (memory monitoring) and Organization
(org chart + session status).

Supports the team structure (ADR-002):
  - Orchestrator (운영팀)
  - 코어팀: Planner, Researcher, Reviewer, QA, Coder
  - 도메인팀: per-project developer + context

Usage:
    python3 scripts/vault-ui.py                 # generate + open
    python3 scripts/vault-ui.py --install-handler  # install tmux URL scheme
"""

import html
import json
import os
import re
import subprocess
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

VAULT_DIR = Path.home() / "dev" / "memory-vault"
VAULT_NAME = "memory-vault"
OUTPUT_FILE = VAULT_DIR / "vault-dashboard.html"
EXCLUDE_DIRS = {".git", ".obsidian", "templates", "archive", ".trash"}
CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"

ROLE_COLORS = {
    "orchestrator": "#f59e0b",
    "planner": "#3b82f6",
    "researcher": "#8b5cf6",
    "reviewer": "#ec4899",
    "qa": "#14b8a6",
    "coder": "#f97316",
}
CORE_COLOR = "#7f6df2"
DOMAIN_COLOR = "#22c55e"

SESSION_COLORS = {"idle": "#22c55e", "busy": "#eab308", "off": "#6b7280"}
HEALTH_COLORS = {"hot": "#ef4444", "warm": "#f59e0b", "cold": "#3b82f6", "archive": "#6b7280"}

BUSY_KEYWORDS = [
    "thinking", "writing", "reading", "━", "⠋", "⠙", "⠹", "⠸",
    "⠼", "⠴", "⠦", "⠧", "⠇", "⠏", "running", "compiling",
]


# ── Data Collection ────────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from markdown text."""
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        colon = line.find(":")
        if colon == -1:
            continue
        key = line[:colon].strip()
        val = line[colon + 1:].strip().strip('"').strip("'")
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
        elif val.isdigit():
            val = int(val)
        elif val in ("true", "false"):
            val = val == "true"
        fm[key] = val
    return fm


def scan_vault(vault_dir: Path) -> list:
    """Scan vault for all markdown files with frontmatter."""
    files = []
    for md_path in sorted(vault_dir.rglob("*.md")):
        rel = md_path.relative_to(vault_dir)
        if any(p in EXCLUDE_DIRS for p in rel.parts):
            continue
        if rel.name == "CLAUDE.md" and len(rel.parts) == 1:
            continue
        try:
            text = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fm = parse_frontmatter(text)
        files.append({
            "path": str(rel),
            "name": rel.stem,
            "full_path": str(md_path),
            "frontmatter": fm,
            "has_frontmatter": bool(fm),
            "text": text,
        })
    return files


def scan_tmux_sessions() -> list:
    """Scan tmux sessions starting with cc-, capture last output line."""
    try:
        result = subprocess.run(
            ["tmux", "ls", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    sessions = []
    for name in result.stdout.strip().split("\n"):
        name = name.strip()
        if not name or not name.startswith("cc-"):
            continue
        try:
            cap = subprocess.run(
                ["tmux", "capture-pane", "-t", name, "-p"],
                capture_output=True, text=True, timeout=5,
            )
            last_lines = [l for l in cap.stdout.strip().split("\n") if l.strip()]
            last_line = last_lines[-1] if last_lines else ""
        except (subprocess.TimeoutExpired, OSError):
            last_line = ""

        status = "idle"
        if any(kw in last_line.lower() for kw in BUSY_KEYWORDS):
            status = "busy"

        # Map session name → group
        if "orchestration" in name:
            group = "orchestrator"
        elif "planner" in name:
            group = "core-planner"
        elif "pool" in name:
            group = "core-pool"
        else:
            group = "unknown"

        sessions.append({
            "name": name,
            "status": status,
            "group": group,
            "last_output": last_line[:80],
        })
    return sessions


def classify_health(file_info: dict, today: datetime) -> str:
    """Classify memory health: hot/warm/cold/archive."""
    fm = file_info.get("frontmatter", {})
    last = fm.get("last_accessed", "")
    importance = fm.get("importance", 5)
    if isinstance(importance, str):
        try:
            importance = int(importance)
        except ValueError:
            importance = 5
    if not last:
        return "cold"
    try:
        last_dt = datetime.strptime(str(last), "%Y-%m-%d")
    except ValueError:
        return "cold"
    days_ago = (today - last_dt).days
    if days_ago <= 3 and importance >= 7:
        return "hot"
    if days_ago <= 7:
        return "warm"
    if days_ago <= 30:
        return "cold"
    return "archive"


def compute_stats(files: list) -> dict:
    """Compute dashboard statistics."""
    today = datetime.now()
    total = len(files)
    tracked = sum(1 for f in files if f["has_frontmatter"])
    health_counts = Counter()
    tag_counts = Counter()
    type_counts = Counter()

    for f in files:
        if f["has_frontmatter"]:
            h = classify_health(f, today)
            f["health"] = h
            health_counts[h] += 1
            tags = f["frontmatter"].get("tags", [])
            if isinstance(tags, list):
                for t in tags:
                    tag_counts[t] += 1
            type_counts[f["frontmatter"].get("type", "unknown")] += 1
        else:
            f["health"] = "untracked"

    return {
        "total": total,
        "tracked": tracked,
        "date": today.strftime("%Y-%m-%d"),
        "health": dict(health_counts),
        "tags": dict(tag_counts.most_common(15)),
        "types": dict(type_counts),
    }


def extract_section_lines(text: str, heading: str, max_lines: int = 3) -> list:
    """Extract first N non-empty lines after a markdown heading."""
    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    lines = text.split("\n")
    found = False
    result = []
    for line in lines:
        if re.match(pattern, line):
            found = True
            continue
        if found:
            if line.startswith("## "):
                break
            stripped = line.strip()
            if stripped and stripped != "- (아직 없음)":
                result.append(stripped)
                if len(result) >= max_lines:
                    break
    return result


def _parse_role(file_info: dict) -> dict:
    """Extract role data from a role.md file."""
    text = file_info["text"]
    identity = extract_section_lines(text, "정체성", 2)
    boundaries = extract_section_lines(text, "경계 (하지 않는 것)", 4)
    if not boundaries:
        boundaries = extract_section_lines(text, "경계", 4)
    references = extract_section_lines(text, "읽어야 할 파일 (세션 시작 후)", 5)
    if not references:
        references = extract_section_lines(text, "읽어야 할 파일", 5)
    responsibilities = extract_section_lines(text, "책임", 6)

    # Extract completion keyword
    kw_match = re.search(r"```\s*\n(\w+_\w+)\s*\n```", text)
    completion_kw = kw_match.group(1) if kw_match else ""

    return {
        "identity": " ".join(identity) if identity else "",
        "boundaries": boundaries,
        "references": references,
        "responsibilities": responsibilities,
        "completion_keyword": completion_kw,
    }


def _parse_memory(file_info: dict) -> dict:
    """Extract memory data from a memory.md file."""
    fm = file_info["frontmatter"]
    text = file_info["text"]
    return {
        "importance": fm.get("importance", "?"),
        "access_count": fm.get("access_count", 0),
        "last_accessed": fm.get("last_accessed", "?"),
        "lessons": extract_section_lines(text, "교훈", 3),
        "patterns": extract_section_lines(text, "패턴", 3),
        "mistakes": extract_section_lines(text, "실수/회피", 3),
        "path": file_info["path"],
    }


def build_org_data(files: list, tmux_sessions: list) -> dict:
    """Build organization data reflecting 코어팀/도메인팀/운영팀 structure."""

    # ── Orchestrator ──
    orch_file = next((f for f in files if f["path"] == "01-org/enabling/orchestrator/role.md"), None)
    orch_mem_file = next((f for f in files if f["path"] == "01-org/enabling/orchestrator/memory.md"), None)
    orchestrator = {
        "role": _parse_role(orch_file) if orch_file else {},
        "role_path": orch_file["path"] if orch_file else "",
        "memory": _parse_memory(orch_mem_file) if orch_mem_file else {},
        "tmux_sessions": [s for s in tmux_sessions if s["group"] == "orchestrator"],
    }

    # ── Core Team ──
    team_file = next((f for f in files if f["path"] == "01-org/core/_team.md"), None)
    team_text = team_file["text"] if team_file else ""
    team_fm = team_file["frontmatter"] if team_file else {}

    # Extract mission
    mission_lines = extract_section_lines(team_text, "미션", 3) if team_text else []
    team_mission = " ".join(l.lstrip("- ") for l in mission_lines) if mission_lines else ""

    # Scan core roles
    core_role_names = ["planner", "researcher", "reviewer", "qa", "coder"]
    core_roles = []
    for rname in core_role_names:
        role_f = next((f for f in files if f["path"] == f"01-org/core/{rname}/role.md"), None)
        mem_f = next((f for f in files if f["path"] == f"01-org/core/{rname}/memory.md"), None)
        core_roles.append({
            "name": rname,
            "color": ROLE_COLORS.get(rname, CORE_COLOR),
            "role": _parse_role(role_f) if role_f else {},
            "role_path": role_f["path"] if role_f else "",
            "memory": _parse_memory(mem_f) if mem_f else {},
        })

    # tmux sessions for core team: planner + pool workers
    core_tmux = [s for s in tmux_sessions if s["group"].startswith("core-")]

    core_team = {
        "mission": team_mission,
        "team_path": team_file["path"] if team_file else "",
        "roles": core_roles,
        "tmux_sessions": core_tmux,
    }

    # ── Domain Teams ──
    # Each project in 03-projects/ with a developer.md is a domain team
    project_dirs = set()
    for f in files:
        if f["path"].startswith("03-projects/") and "/" in f["path"][len("03-projects/"):]:
            proj_name = f["path"].split("/")[1]
            project_dirs.add(proj_name)

    domain_teams = []
    for proj in sorted(project_dirs):
        dev_file = next((f for f in files if f["path"] == f"03-projects/{proj}/developer.md"), None)
        dev_mem = next((f for f in files if f["path"] == f"03-projects/{proj}/developer-memory.md"), None)
        ctx_file = next((f for f in files if f["path"] == f"03-projects/{proj}/context.md"), None)
        overview_file = next((f for f in files if f["path"] == f"03-projects/{proj}/context.md"), None)

        # Extract context summary
        ctx_summary = ""
        ctx_stack = ""
        if ctx_file:
            summary_lines = extract_section_lines(ctx_file["text"], "프로젝트 요약", 2)
            ctx_summary = " ".join(summary_lines) if summary_lines else ""
            stack_lines = extract_section_lines(ctx_file["text"], "스택", 5)
            ctx_stack = ", ".join(l.lstrip("- ").split(":")[0].strip("*") for l in stack_lines)

        domain_teams.append({
            "project": proj,
            "summary": ctx_summary,
            "stack": ctx_stack,
            "developer": _parse_role(dev_file) if dev_file else {},
            "developer_path": dev_file["path"] if dev_file else "",
            "memory": _parse_memory(dev_mem) if dev_mem else {},
            "context_path": ctx_file["path"] if ctx_file else "",
            "overview_path": overview_file["path"] if overview_file else "",
        })

    # Session files for related sessions
    session_files = [
        f for f in files
        if f["path"].startswith("05-sessions/") and f["name"] != "_distill-queue"
    ]

    return {
        "orchestrator": orchestrator,
        "core_team": core_team,
        "domain_teams": domain_teams,
        "session_files": session_files,
    }


# ── Link Generation ────────────────────────────────────────────────────────

def obsidian_uri(vault_name: str, file_path: str) -> str:
    fp = file_path[:-3] if file_path.endswith(".md") else file_path
    return f"obsidian://open?vault={html.escape(vault_name)}&file={html.escape(fp)}"


def tmux_attach_uri(session_name: str) -> str:
    return f"tmux-attach://{html.escape(session_name)}"


def tmux_clipboard_js(session_name: str) -> str:
    cmd = f"tmux attach -t {session_name}"
    return (
        f"navigator.clipboard.writeText('{cmd}')"
        f".then(()=>showToast('Copied: {cmd}'))"
    )


# ── URL Handler ────────────────────────────────────────────────────────────

def install_url_handler():
    """Install tmux-attach:// URL scheme handler on macOS."""
    app_dir = Path.home() / "Applications" / "TmuxAttach.app" / "Contents"
    macos_dir = app_dir / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)

    plist = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.memoryvault.tmuxattach</string>
    <key>CFBundleName</key>
    <string>TmuxAttach</string>
    <key>CFBundleExecutable</key>
    <string>tmux-attach</string>
    <key>CFBundleURLTypes</key>
    <array>
        <dict>
            <key>CFBundleURLName</key>
            <string>tmux-attach</string>
            <key>CFBundleURLSchemes</key>
            <array>
                <string>tmux-attach</string>
            </array>
        </dict>
    </array>
</dict>
</plist>"""
    (app_dir / "Info.plist").write_text(plist)

    script = """\
#!/bin/bash
SESSION="${1#tmux-attach://}"
SESSION="${SESSION%%/}"
if [ -n "$SESSION" ]; then
    osascript -e "
        tell application \\"Terminal\\"
            activate
            do script \\"tmux attach -t $SESSION\\"
        end tell
    "
fi
"""
    exe_path = macos_dir / "tmux-attach"
    exe_path.write_text(script)
    os.chmod(str(exe_path), 0o755)

    subprocess.run(
        ["/System/Library/Frameworks/CoreServices.framework/Frameworks/"
         "LaunchServices.framework/Support/lsregister",
         "-R", str(app_dir.parent)],
        capture_output=True,
    )
    print(f"Installed: {app_dir.parent}")
    print("URL scheme tmux-attach:// registered.")


# ── CSS ────────────────────────────────────────────────────────────────────

def _css() -> str:
    return """\
:root {
  --bg: #1e1e1e; --bg2: #252526; --bg3: #2d2d30;
  --text: #dcddde; --text2: #a0a0a0; --accent: #7f6df2;
  --border: #3e3e42;
  --hot: #ef4444; --warm: #f59e0b; --cold: #3b82f6; --archive: #6b7280;
  --idle: #22c55e; --busy: #eab308; --off: #6b7280;
  --core: #7f6df2; --domain: #22c55e; --orch: #f59e0b;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg); color: var(--text);
  line-height: 1.5; min-height: 100vh;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Header */
.header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 24px; background: var(--bg2); border-bottom: 1px solid var(--border);
}
.header h1 { font-size: 20px; font-weight: 600; }
.header-stats { display: flex; gap: 16px; font-size: 13px; color: var(--text2); }

/* Tabs */
.tab-nav {
  display: flex; background: var(--bg2);
  border-bottom: 2px solid var(--border); padding: 0 24px;
}
.tab-btn {
  padding: 10px 20px; cursor: pointer; border: none; background: none;
  color: var(--text2); font-size: 14px; font-weight: 500;
  border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all 0.2s;
}
.tab-btn:hover { color: var(--text); }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-content { display: none; padding: 24px; max-width: 1200px; margin: 0 auto; }
.tab-content.active { display: block; }

/* Cards */
.card {
  background: var(--bg2); border: 1px solid var(--border);
  border-radius: 8px; padding: 20px; margin-bottom: 20px;
}
.card h2 {
  font-size: 16px; font-weight: 600; margin-bottom: 16px;
  padding-bottom: 8px; border-bottom: 1px solid var(--border);
}
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }

/* Health donut */
.health-container { display: flex; align-items: center; gap: 32px; }
.health-chart { width: 180px; height: 180px; }
.health-legend { display: flex; flex-direction: column; gap: 8px; }
.legend-item { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }

/* Timeline */
.timeline { position: relative; padding-left: 24px; }
.timeline::before {
  content: ''; position: absolute; left: 7px; top: 4px; bottom: 4px;
  width: 2px; background: var(--border);
}
.tl-item { position: relative; margin-bottom: 20px; }
.tl-dot {
  position: absolute; left: -21px; top: 4px; width: 12px; height: 12px;
  border-radius: 50%; background: var(--accent); border: 2px solid var(--bg2);
}
.tl-date { font-size: 13px; color: var(--text2); margin-bottom: 2px; }
.tl-title { font-size: 14px; font-weight: 500; }
.tl-badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-top: 4px;
}
.tl-badge.distilled { background: var(--idle); color: #000; }
.tl-badge.not-distilled { background: var(--border); color: var(--text2); }

/* Knowledge cards */
.k-card {
  background: var(--bg3); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px; transition: border-color 0.2s;
}
.k-card:hover { border-color: var(--accent); }
.k-card .name { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
.k-card .meta { font-size: 12px; color: var(--text2); }
.k-card .tags { font-size: 11px; color: var(--accent); margin-top: 6px; }
.k-card .imp {
  display: inline-block; padding: 1px 6px; border-radius: 3px;
  font-size: 11px; font-weight: 600;
}

/* Bars */
.bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.bar-label { width: 120px; text-align: right; font-size: 13px; color: var(--text2); flex-shrink: 0; }
.bar-fill { height: 20px; border-radius: 3px; background: var(--accent); min-width: 2px; }
.bar-count { font-size: 12px; color: var(--text2); width: 30px; }

/* Table */
.file-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.file-table th {
  text-align: left; padding: 8px 12px; border-bottom: 2px solid var(--border);
  color: var(--text2); font-weight: 500; cursor: pointer; user-select: none;
}
.file-table th:hover { color: var(--text); }
.file-table td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
.file-table tr:hover td { background: var(--bg3); }
.search-box {
  padding: 8px 12px; background: var(--bg3); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text); font-size: 13px; width: 240px; margin-bottom: 12px;
}
.search-box::placeholder { color: var(--text2); }

/* Status dots */
.status-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px;
}
.status-dot.idle { background: var(--idle); }
.status-dot.busy { background: var(--busy); }
.status-dot.off { background: var(--off); }

/* ── Organization Tab ── */

/* Org overview: 3-column layout */
.org-overview {
  display: grid; grid-template-columns: 1fr 2fr 1fr; gap: 20px;
  align-items: start; margin-bottom: 20px;
}

/* Org node (Orchestrator / Core Team / Domain Teams) */
.org-node {
  background: var(--bg2); border: 1px solid var(--border);
  border-radius: 10px; padding: 20px; text-align: center;
  border-top: 3px solid var(--accent);
}
.org-node h3 { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
.org-node .subtitle { font-size: 12px; color: var(--text2); margin-bottom: 12px; }

/* Role chips inside core team node */
.role-chips { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.role-chip {
  padding: 4px 10px; border-radius: 6px; font-size: 12px;
  font-weight: 500; border: 1px solid; cursor: pointer; transition: all 0.2s;
}
.role-chip:hover { transform: translateY(-1px); }
.role-chip .kw { font-size: 10px; opacity: 0.7; margin-left: 4px; }

/* Domain chip */
.domain-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 6px; font-size: 13px;
  background: var(--bg3); border: 1px solid var(--domain);
  color: var(--domain); cursor: pointer; transition: all 0.2s;
  margin: 3px;
}
.domain-chip:hover { background: rgba(34, 197, 94, 0.1); }

/* Section cards (expandable) */
.section-card {
  background: var(--bg2); border: 1px solid var(--border);
  border-radius: 8px; margin-bottom: 16px; overflow: hidden;
}
.section-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px; cursor: pointer; user-select: none;
  transition: background 0.2s;
}
.section-header:hover { background: var(--bg3); }
.section-header h3 { font-size: 15px; display: flex; align-items: center; gap: 8px; }
.section-header .summary { font-size: 12px; color: var(--text2); }
.section-body { padding: 0 20px 20px; display: none; }
.section-card.open .section-body { display: block; }
.section-card.open .toggle-icon { transform: rotate(180deg); }
.toggle-icon { transition: transform 0.2s; font-size: 12px; color: var(--text2); }

/* Role detail block */
.role-block {
  background: var(--bg3); border-radius: 6px; padding: 16px;
  margin: 12px 0; border-left: 3px solid var(--accent);
}
.role-block h4 { font-size: 14px; font-weight: 600; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.role-meta { font-size: 13px; color: var(--text2); margin-bottom: 4px; }
.role-list { font-size: 13px; padding-left: 16px; margin: 4px 0; }
.role-list li { margin-bottom: 2px; }

.mem-grid {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 8px; margin: 8px 0; font-size: 13px;
}
.mem-stat {
  background: var(--bg2); padding: 8px; border-radius: 4px; text-align: center;
}
.mem-stat .label { color: var(--text2); font-size: 11px; }
.mem-stat .value { font-weight: 600; font-size: 16px; }

.tmux-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; background: var(--bg2); border-radius: 6px;
  margin: 6px 0; font-size: 13px;
}
.tmux-row .session-name { font-weight: 600; font-family: monospace; }
.tmux-row .session-output {
  flex: 1; color: var(--text2); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; font-family: monospace; font-size: 12px;
}

.btn-sm {
  padding: 3px 10px; border-radius: 4px; font-size: 11px;
  border: 1px solid var(--border); background: var(--bg3);
  color: var(--text); cursor: pointer; text-decoration: none;
  display: inline-flex; align-items: center; gap: 4px;
}
.btn-sm:hover { background: var(--border); text-decoration: none; }

/* Context info box */
.ctx-box {
  background: var(--bg3); border-radius: 6px; padding: 12px 16px;
  margin: 8px 0; font-size: 13px; border-left: 3px solid var(--domain);
}
.ctx-box .ctx-label { font-size: 11px; color: var(--text2); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }

/* Toast */
.toast {
  position: fixed; bottom: 24px; right: 24px; background: var(--accent);
  color: #fff; padding: 10px 20px; border-radius: 8px; font-size: 13px;
  opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 999;
}
.toast.show { opacity: 1; }

/* Responsive */
@media (max-width: 768px) {
  .grid-2 { grid-template-columns: 1fr; }
  .grid-3 { grid-template-columns: 1fr; }
  .org-overview { grid-template-columns: 1fr; }
  .health-container { flex-direction: column; }
  .header { flex-direction: column; gap: 8px; }
  .tab-nav { overflow-x: auto; }
  .mem-grid { grid-template-columns: 1fr; }
}
"""


# ── HTML Builders (Tab 1: Dashboard) ──────────────────────────────────────

def _html_header(stats: dict) -> str:
    return f"""\
<div class="header">
  <h1>Memory Vault</h1>
  <div class="header-stats">
    <span>{stats['total']} files</span>
    <span>{stats['tracked']} tracked</span>
    <span>{stats['date']}</span>
  </div>
</div>
<div class="tab-nav">
  <button class="tab-btn active" onclick="switchTab('dashboard')">Dashboard</button>
  <button class="tab-btn" onclick="switchTab('organization')">Organization</button>
</div>
"""


def _html_health(stats: dict) -> str:
    health = stats.get("health", {})
    legend = ""
    for key in ["hot", "warm", "cold", "archive"]:
        count = health.get(key, 0)
        legend += f'    <div class="legend-item"><span class="legend-dot" style="background:{HEALTH_COLORS[key]}"></span><span>{key.capitalize()}</span><span style="color:var(--text2);margin-left:auto">{count}</span></div>\n'
    return f"""\
<div class="card">
  <h2>Memory Health</h2>
  <div class="health-container">
    <div class="health-chart"><canvas id="healthChart"></canvas></div>
    <div class="health-legend">{legend}</div>
  </div>
</div>
"""


def _html_timeline(files: list) -> str:
    sessions = sorted(
        [f for f in files if f["frontmatter"].get("type") == "session" and f["name"] != "_distill-queue"],
        key=lambda f: f["name"], reverse=True,
    )
    items = ""
    for s in sessions:
        fm = s["frontmatter"]
        distilled = fm.get("distilled", False)
        badge_cls = "distilled" if distilled else "not-distilled"
        badge_text = "Distilled" if distilled else "Not Distilled"
        tags = fm.get("tags", [])
        tag_str = ", ".join(tags[:4]) if isinstance(tags, list) else ""
        uri = obsidian_uri(VAULT_NAME, s["path"])
        items += f"""\
    <div class="tl-item">
      <div class="tl-dot"></div>
      <div class="tl-date">{html.escape(s['name'])}</div>
      <div class="tl-title"><a href="{uri}">{html.escape(tag_str)}</a></div>
      <span class="tl-badge {badge_cls}">{badge_text}</span>
    </div>\n"""
    return f'<div class="card"><h2>Session Timeline</h2><div class="timeline">{items}</div></div>'


def _html_knowledge(files: list) -> str:
    knowledge = sorted(
        [f for f in files if f["has_frontmatter"] and f["frontmatter"].get("type") in ("pattern", "skill", "convention")],
        key=lambda f: f["frontmatter"].get("importance", 0), reverse=True,
    )
    cards = ""
    for k in knowledge:
        fm = k["frontmatter"]
        imp = fm.get("importance", "?")
        ftype = fm.get("type", "?")
        acc = fm.get("access_count", 0)
        last = fm.get("last_accessed", "?")
        tags = fm.get("tags", [])
        tag_str = ", ".join(tags[:3]) if isinstance(tags, list) else ""
        uri = obsidian_uri(VAULT_NAME, k["path"])
        imp_val = int(imp) if isinstance(imp, int) else 5
        imp_color = "var(--hot)" if imp_val >= 8 else "var(--warm)" if imp_val >= 6 else "var(--cold)"
        cards += f"""\
    <a href="{uri}" class="k-card" style="text-decoration:none;color:inherit;">
      <div class="name">{html.escape(k['name'])}</div>
      <div class="meta"><span class="imp" style="background:{imp_color};color:#000">{imp}</span> {html.escape(str(ftype))}</div>
      <div class="meta">acc:{acc} &nbsp; {html.escape(str(last))}</div>
      <div class="tags">{html.escape(tag_str)}</div>
    </a>\n"""
    return f'<div class="card"><h2>Knowledge &amp; Skills</h2><div class="grid-3">{cards}</div></div>'


def _html_tags(stats: dict) -> str:
    tags = stats.get("tags", {})
    if not tags:
        return ""
    max_count = max(tags.values()) if tags else 1
    bars = ""
    for tag, count in tags.items():
        w = int((count / max_count) * 100)
        bars += f'    <div class="bar-row"><span class="bar-label">{html.escape(tag)}</span><div class="bar-fill" style="width:{w}%"></div><span class="bar-count">{count}</span></div>\n'
    return f'<div class="card"><h2>Tag Distribution</h2>{bars}</div>'


def _html_table(files: list) -> str:
    rows = ""
    for f in sorted(files, key=lambda x: x["path"]):
        fm = f["frontmatter"]
        ftype = fm.get("type", "-")
        imp = fm.get("importance", "-")
        health = f.get("health", "-")
        last = fm.get("last_accessed", "-")
        tags = fm.get("tags", [])
        tag_str = ", ".join(tags[:3]) if isinstance(tags, list) else ""
        uri = obsidian_uri(VAULT_NAME, f["path"])
        hc = HEALTH_COLORS.get(health, "var(--text2)")
        rows += f'      <tr><td><a href="{uri}">{html.escape(f["path"])}</a></td><td>{html.escape(str(ftype))}</td><td>{imp}</td><td><span style="color:{hc}">{html.escape(str(health))}</span></td><td>{html.escape(str(last))}</td><td style="color:var(--text2)">{html.escape(tag_str)}</td></tr>\n'
    return f"""\
<div class="card">
  <h2>All Files</h2>
  <input type="text" class="search-box" id="fileSearch" placeholder="Search files..." oninput="filterTable()">
  <table class="file-table" id="fileTable">
    <thead><tr>
      <th onclick="sortTable(0)">Path</th><th onclick="sortTable(1)">Type</th>
      <th onclick="sortTable(2)">Imp</th><th onclick="sortTable(3)">Health</th>
      <th onclick="sortTable(4)">Last Accessed</th><th onclick="sortTable(5)">Tags</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


# ── HTML Builders (Tab 2: Organization) ───────────────────────────────────

def _html_tmux_row(session: dict) -> str:
    name = session["name"]
    status = session["status"]
    output = session.get("last_output", "")
    color = SESSION_COLORS.get(status, "#6b7280")
    attach_href = tmux_attach_uri(name)
    clipboard_js = tmux_clipboard_js(name)
    return f"""\
<div class="tmux-row">
  <span class="session-name">{html.escape(name)}</span>
  <span class="status-dot {status}"></span>
  <span style="color:{color};font-size:12px">{status}</span>
  <span class="session-output">{html.escape(output)}</span>
  <a class="btn-sm" href="{attach_href}"
     onclick="if(!isSchemeRegistered()){{event.preventDefault();{clipboard_js}}}">Attach</a>
</div>"""


def _html_memory_block(mem: dict, show_open_btn: bool = True) -> str:
    """Render a memory stats block."""
    if not mem:
        return '<div class="role-meta" style="color:var(--text2)">No memory file</div>'

    uri = obsidian_uri(VAULT_NAME, mem.get("path", ""))
    open_btn = f'<a href="{uri}" class="btn-sm" style="margin-left:8px">Open in Obsidian</a>' if show_open_btn else ""

    lessons = mem.get("lessons", [])
    patterns = mem.get("patterns", [])
    mistakes = mem.get("mistakes", [])
    ls = "<br>".join(html.escape(l) for l in lessons) if lessons else "<span style='color:var(--text2)'>empty</span>"
    ps = "<br>".join(html.escape(p) for p in patterns) if patterns else "<span style='color:var(--text2)'>empty</span>"
    ms = "<br>".join(html.escape(m) for m in mistakes) if mistakes else "<span style='color:var(--text2)'>empty</span>"

    return f"""\
<div style="margin-top:12px">
  <div class="role-meta"><strong>Memory</strong>{open_btn}</div>
  <div class="mem-grid">
    <div class="mem-stat"><div class="label">importance</div><div class="value">{mem.get('importance','?')}</div></div>
    <div class="mem-stat"><div class="label">access</div><div class="value">{mem.get('access_count',0)}</div></div>
    <div class="mem-stat"><div class="label">last</div><div class="value" style="font-size:12px">{mem.get('last_accessed','?')}</div></div>
  </div>
  <div style="font-size:12px;margin-top:8px">
    <div><strong>Lessons:</strong> {ls}</div>
    <div style="margin-top:4px"><strong>Patterns:</strong> {ps}</div>
    <div style="margin-top:4px"><strong>Mistakes:</strong> {ms}</div>
  </div>
</div>"""


def _html_org_overview(org: dict) -> str:
    """Render the top-level organization overview with 3 columns."""
    orch = org["orchestrator"]
    core = org["core_team"]
    domains = org["domain_teams"]

    # Orchestrator sessions count
    orch_sessions = orch.get("tmux_sessions", [])
    orch_online = sum(1 for s in orch_sessions if s["status"] in ("idle", "busy"))
    orch_status = f'<span class="status-dot idle"></span> online' if orch_online > 0 else '<span class="status-dot off"></span> off'

    # Core team session count
    core_sessions = core.get("tmux_sessions", [])
    core_online = sum(1 for s in core_sessions if s["status"] in ("idle", "busy"))
    core_total = len(core["roles"])

    # Role chips
    chips = ""
    for r in core["roles"]:
        color = r["color"]
        kw = r["role"].get("completion_keyword", "")
        kw_html = f'<span class="kw">{html.escape(kw)}</span>' if kw else ""
        chips += f'<span class="role-chip" style="color:{color};border-color:{color}" onclick="toggleSection(\'core-{r["name"]}\')">{r["name"].capitalize()}{kw_html}</span>\n'

    # Domain chips
    domain_chips = ""
    for d in domains:
        domain_chips += f'<span class="domain-chip" onclick="toggleSection(\'domain-{d["project"]}\')">{html.escape(d["project"])}</span>\n'

    return f"""\
<div class="org-overview">
  <!-- Orchestrator -->
  <div class="org-node" style="border-top-color:var(--orch)">
    <h3 style="color:var(--orch)">Orchestrator</h3>
    <div class="subtitle">Team Leader — 지시 해석, 작업 할당, 결과 추적</div>
    <div>{orch_status}</div>
  </div>

  <!-- Core Team -->
  <div class="org-node" style="border-top-color:var(--core)">
    <h3 style="color:var(--core)">Core Team <span style="font-size:12px;color:var(--text2)">(Platform)</span></h3>
    <div class="subtitle">{core_online} online / {core_total} roles</div>
    <div class="role-chips">{chips}</div>
  </div>

  <!-- Domain Teams -->
  <div class="org-node" style="border-top-color:var(--domain)">
    <h3 style="color:var(--domain)">도메인팀</h3>
    <div class="subtitle">{len(domains)} project(s)</div>
    <div>{domain_chips}</div>
  </div>
</div>

<!-- Head -->
<div style="text-align:center;margin-bottom:20px;font-size:13px;color:var(--text2)">
  Head: <strong style="color:var(--text)">상엽</strong> &middot; 코어팀/도메인팀/운영팀 구조 (ADR-002)
</div>
"""


def _html_orchestrator_section(org: dict) -> str:
    """Render orchestrator detail section."""
    orch = org["orchestrator"]
    role = orch.get("role", {})
    mem = orch.get("memory", {})
    sessions = orch.get("tmux_sessions", [])
    role_path = orch.get("role_path", "")

    identity = role.get("identity", "")
    boundaries = role.get("boundaries", [])
    bounds_html = ""
    if boundaries:
        items = "".join(f"<li>{html.escape(b.lstrip('- '))}</li>" for b in boundaries)
        bounds_html = f'<ul class="role-list">{items}</ul>'

    sessions_html = "\n".join(_html_tmux_row(s) for s in sessions) if sessions else '<div class="tmux-row"><span style="color:var(--text2)">No active sessions</span></div>'

    # Session summary for header
    session_summary = " | ".join(
        f'{html.escape(s["name"])} <span class="status-dot {s["status"]}"></span> {s["status"]}'
        for s in sessions
    ) if sessions else '<span class="status-dot off"></span> off'

    role_uri = obsidian_uri(VAULT_NAME, role_path) if role_path else "#"

    return f"""\
<div class="section-card" id="section-orchestrator">
  <div class="section-header" style="border-left:4px solid var(--orch)" onclick="toggleSection('orchestrator')">
    <h3><span style="color:var(--orch)">Orchestrator</span></h3>
    <div style="display:flex;align-items:center;gap:16px">
      <span style="font-size:12px">{session_summary}</span>
      <span class="toggle-icon">&#9660;</span>
    </div>
  </div>
  <div class="section-body">
    <div class="role-block" style="border-left-color:var(--orch)">
      <h4>
        <span style="color:var(--orch)">Orchestrator</span>
        <a href="{role_uri}" class="btn-sm">Open in Obsidian</a>
      </h4>
      <div class="role-meta">{html.escape(identity)}</div>
      {bounds_html}
      {_html_memory_block(mem)}
    </div>
    <div style="margin-top:16px">
      <div class="role-meta"><strong>tmux Sessions</strong></div>
      {sessions_html}
    </div>
  </div>
</div>"""


def _html_core_team_section(org: dict) -> str:
    """Render core team detail sections (one per role)."""
    core = org["core_team"]
    sections = ""

    for r in core["roles"]:
        rname = r["name"]
        color = r["color"]
        role = r.get("role", {})
        mem = r.get("memory", {})
        role_path = r.get("role_path", "")

        identity = role.get("identity", "")
        kw = role.get("completion_keyword", "")
        boundaries = role.get("boundaries", [])
        responsibilities = role.get("responsibilities", [])

        bounds_html = ""
        if boundaries:
            items = "".join(f"<li>{html.escape(b.lstrip('- '))}</li>" for b in boundaries)
            bounds_html = f'<div style="margin-top:8px"><strong style="font-size:12px">Boundaries:</strong><ul class="role-list">{items}</ul></div>'

        resp_html = ""
        if responsibilities:
            items = "".join(f"<li>{html.escape(r_item.lstrip('0123456789. '))}</li>" for r_item in responsibilities)
            resp_html = f'<div style="margin-top:8px"><strong style="font-size:12px">Responsibilities:</strong><ul class="role-list">{items}</ul></div>'

        # Match tmux sessions for this role
        role_sessions = [s for s in core.get("tmux_sessions", []) if rname in s["name"] or (rname == "coder" and "pool" in s["name"])]
        session_summary_parts = []
        for s in role_sessions:
            session_summary_parts.append(f'{html.escape(s["name"])} <span class="status-dot {s["status"]}"></span>')
        session_summary = " | ".join(session_summary_parts) if session_summary_parts else '<span class="status-dot off"></span> off'

        sessions_html = "\n".join(_html_tmux_row(s) for s in role_sessions) if role_sessions else '<div class="tmux-row"><span style="color:var(--text2)">No active sessions</span></div>'

        role_uri = obsidian_uri(VAULT_NAME, role_path) if role_path else "#"
        kw_badge = f'<span style="font-size:11px;padding:2px 8px;border-radius:4px;background:{color};color:#000;margin-left:8px">{html.escape(kw)}</span>' if kw else ""

        sections += f"""\
<div class="section-card" id="section-core-{rname}">
  <div class="section-header" style="border-left:4px solid {color}" onclick="toggleSection('core-{rname}')">
    <h3><span style="color:{color}">{rname.capitalize()}</span>{kw_badge}</h3>
    <div style="display:flex;align-items:center;gap:16px">
      <span class="summary">{session_summary}</span>
      <span class="toggle-icon">&#9660;</span>
    </div>
  </div>
  <div class="section-body">
    <div class="role-block" style="border-left-color:{color}">
      <h4>
        <span style="color:{color}">{rname.capitalize()}</span>
        <a href="{role_uri}" class="btn-sm">Open in Obsidian</a>
      </h4>
      <div class="role-meta">{html.escape(identity)}</div>
      {resp_html}
      {bounds_html}
      {_html_memory_block(mem)}
    </div>
    <div style="margin-top:12px">
      <div class="role-meta"><strong>tmux Sessions</strong></div>
      {sessions_html}
    </div>
  </div>
</div>\n"""

    return f"""\
<div style="margin-top:8px;margin-bottom:8px">
  <h2 style="font-size:15px;color:var(--core);padding:0 4px;margin-bottom:12px">Core Team (Platform)</h2>
  <div style="font-size:13px;color:var(--text2);margin-bottom:16px;padding:0 4px">{html.escape(core.get('mission', ''))}</div>
  {sections}
</div>"""


def _html_domain_teams_section(org: dict) -> str:
    """Render domain team sections."""
    domains = org["domain_teams"]
    if not domains:
        return ""

    sections = ""
    for d in domains:
        proj = d["project"]
        summary = d.get("summary", "")
        stack = d.get("stack", "")
        dev = d.get("developer", {})
        mem = d.get("memory", {})
        dev_path = d.get("developer_path", "")
        ctx_path = d.get("context_path", "")
        overview_path = d.get("overview_path", "")

        identity = dev.get("identity", "")

        # Context box
        ctx_html = ""
        if summary or stack:
            ctx_uri = obsidian_uri(VAULT_NAME, ctx_path) if ctx_path else "#"
            stack_line = f'<div style="margin-top:4px"><strong>Stack:</strong> {html.escape(stack)}</div>' if stack else ""
            ctx_html = f"""\
    <div class="ctx-box">
      <div class="ctx-label">Domain Context <a href="{ctx_uri}" class="btn-sm" style="margin-left:8px">Open</a></div>
      <div>{html.escape(summary)}</div>
      {stack_line}
    </div>"""

        # Developer role
        dev_uri = obsidian_uri(VAULT_NAME, dev_path) if dev_path else "#"
        overview_uri = obsidian_uri(VAULT_NAME, overview_path) if overview_path else "#"

        boundaries = dev.get("boundaries", [])
        bounds_html = ""
        if boundaries:
            items = "".join(f"<li>{html.escape(b.lstrip('- '))}</li>" for b in boundaries)
            bounds_html = f'<ul class="role-list">{items}</ul>'

        # Memory importance for summary
        mem_imp = mem.get("importance", "?") if mem else "?"

        sections += f"""\
<div class="section-card" id="section-domain-{proj}">
  <div class="section-header" style="border-left:4px solid var(--domain)" onclick="toggleSection('domain-{proj}')">
    <h3><span style="color:var(--domain)">{html.escape(proj)}</span></h3>
    <div style="display:flex;align-items:center;gap:16px">
      <span class="summary">{html.escape(summary[:50])}</span>
      <span class="toggle-icon">&#9660;</span>
    </div>
  </div>
  <div class="section-body">
    {ctx_html}
    <div class="role-block" style="border-left-color:var(--domain)">
      <h4>
        <span style="color:var(--domain)">Developer</span>
        <a href="{dev_uri}" class="btn-sm">Open in Obsidian</a>
        <a href="{overview_uri}" class="btn-sm">Overview</a>
      </h4>
      <div class="role-meta">{html.escape(identity)}</div>
      {bounds_html}
      {_html_memory_block(mem)}
    </div>
  </div>
</div>\n"""

    return f"""\
<div style="margin-top:24px;margin-bottom:8px">
  <h2 style="font-size:15px;color:var(--domain);padding:0 4px;margin-bottom:12px">도메인팀</h2>
  {sections}
</div>"""


# ── JavaScript ─────────────────────────────────────────────────────────────

def _js(data_json: str) -> str:
    return f"""\
const DATA = {data_json};

function switchTab(tab) {{
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  event.target.classList.add('active');
}}

function toggleSection(key) {{
  const el = document.getElementById('section-' + key);
  if (el) el.classList.toggle('open');
}}

function showToast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}}

let sortDir = {{}};
function sortTable(col) {{
  const table = document.getElementById('fileTable');
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  sortDir[col] = !sortDir[col];
  rows.sort((a, b) => {{
    const aVal = a.cells[col].textContent.trim();
    const bVal = b.cells[col].textContent.trim();
    const numA = parseFloat(aVal), numB = parseFloat(bVal);
    if (!isNaN(numA) && !isNaN(numB))
      return sortDir[col] ? numA - numB : numB - numA;
    return sortDir[col] ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
  }});
  rows.forEach(r => tbody.appendChild(r));
}}

function filterTable() {{
  const q = document.getElementById('fileSearch').value.toLowerCase();
  document.querySelectorAll('#fileTable tbody tr').forEach(r => {{
    r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}

function isSchemeRegistered() {{
  return !/iPhone|iPad|Android/i.test(navigator.userAgent);
}}

function renderHealthChart() {{
  const ctx = document.getElementById('healthChart');
  if (!ctx) return;
  const h = DATA.health || {{}};
  new Chart(ctx, {{
    type: 'doughnut',
    data: {{
      labels: ['Hot','Warm','Cold','Archive'],
      datasets: [{{
        data: [h.hot||0, h.warm||0, h.cold||0, h.archive||0],
        backgroundColor: ['{HEALTH_COLORS["hot"]}','{HEALTH_COLORS["warm"]}','{HEALTH_COLORS["cold"]}','{HEALTH_COLORS["archive"]}'],
        borderWidth: 0, hoverOffset: 8,
      }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false, cutout: '65%',
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ backgroundColor: '#2d2d30', titleColor: '#dcddde', bodyColor: '#dcddde' }}
      }}
    }}
  }});
}}

document.addEventListener('DOMContentLoaded', renderHealthChart);
"""


# ── Main HTML Assembly ─────────────────────────────────────────────────────

def generate_html(files: list, stats: dict, org: dict) -> str:
    data_json = json.dumps({
        "health": stats.get("health", {}),
        "tags": stats.get("tags", {}),
        "types": stats.get("types", {}),
        "total": stats["total"],
        "tracked": stats["tracked"],
    })

    return f"""\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Memory Vault Dashboard</title>
<script src="{CHART_JS_CDN}"></script>
<style>{_css()}</style>
</head>
<body>

{_html_header(stats)}

<div id="tab-dashboard" class="tab-content active">
  <div class="grid-2">
    {_html_health(stats)}
    {_html_timeline(files)}
  </div>
  {_html_knowledge(files)}
  {_html_tags(stats)}
  {_html_table(files)}
</div>

<div id="tab-organization" class="tab-content">
  {_html_org_overview(org)}
  {_html_orchestrator_section(org)}
  {_html_core_team_section(org)}
  {_html_domain_teams_section(org)}
</div>

<div class="toast" id="toast"></div>

<script>{_js(data_json)}</script>
</body>
</html>
"""


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    if "--install-handler" in sys.argv:
        install_url_handler()
        return

    print("Scanning vault...")
    files = scan_vault(VAULT_DIR)
    stats = compute_stats(files)

    print("Scanning tmux sessions...")
    tmux_sessions = scan_tmux_sessions()

    print("Building org data...")
    org = build_org_data(files, tmux_sessions)

    print("Generating HTML...")
    html_content = generate_html(files, stats, org)
    OUTPUT_FILE.write_text(html_content, encoding="utf-8")
    print(f"Generated: {OUTPUT_FILE}")
    print(f"  {stats['total']} files, {stats['tracked']} tracked")

    webbrowser.open(f"file://{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
