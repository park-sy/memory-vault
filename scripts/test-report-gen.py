#!/usr/bin/env python3
"""test-report-gen.py — Convert JSONL test results to an HTML report.

Usage:
    python3 test-report-gen.py \
        --input /tmp/cc-test-results.jsonl \
        --output storage/test-report.html \
        --elapsed 42 --total 55 --pass 50 --fail 5
"""

import argparse
import json
import html
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path


def load_results(path):
    """Load JSONL file into list of dicts."""
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


def group_by_suite(results):
    """Group results by suite name, preserving order."""
    suites = OrderedDict()
    for r in results:
        suite = r.get("suite", "Unknown")
        if suite not in suites:
            suites[suite] = []
        suites[suite].append(r)
    return suites


def load_comms(path):
    """Load communication events JSONL file."""
    if path is None:
        return []
    p = Path(path)
    if not p.exists():
        return []
    events = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


EVENT_STYLES = {
    "send":          {"color": "#58a6ff", "icon": "\u2192",  "label": "send"},
    "receive":       {"color": "#3fb950", "icon": "\u25c0",  "label": "receive"},
    "ack":           {"color": "#bc8cff", "icon": "\u2713",  "label": "ack"},
    "log-notify":    {"color": "#d29922", "icon": "\U0001f514", "label": "notify"},
    "escalations":   {"color": "#f85149", "icon": "\u26a0",  "label": "escalation"},
    "count-pending": {"color": "#8b949e", "icon": "?",       "label": "count"},
    "stale":         {"color": "#8b949e", "icon": "\u23f3",  "label": "stale"},
}


def generate_timeline_html(comms):
    """Generate per-suite collapsible timeline HTML."""
    if not comms:
        return ""

    suites = OrderedDict()
    for ev in comms:
        suite = ev.get("suite", "Unknown")
        if suite not in suites:
            suites[suite] = []
        suites[suite].append(ev)

    sections = []
    for suite_name, events in suites.items():
        cards = []
        for ev in events:
            event_type = ev.get("event", "unknown")
            style = EVENT_STYLES.get(event_type, {"color": "#8b949e", "icon": "·", "label": event_type})
            ts = html.escape(ev.get("ts", ""))

            # Build description based on event type
            desc_parts = []
            if event_type == "send":
                sender = html.escape(ev.get("from", "?"))
                recipient = html.escape(ev.get("to", "?"))
                msg_type = html.escape(ev.get("msg_type", ""))
                msg_id = html.escape(str(ev.get("msg_id", "")))
                desc_parts.append(
                    f'<span class="comm-sender">{sender}</span> '
                    f'<span class="comm-arrow" style="color:{style["color"]}">\u2500\u2500[{msg_type}]\u2500\u2500\u25b6</span> '
                    f'<span class="comm-recipient">{recipient}</span>'
                    f' <span class="comm-id">#{msg_id}</span>'
                )
                payload = ev.get("payload", "")
                if payload:
                    desc_parts.append(f'<div class="event-payload">{html.escape(payload[:200])}</div>')
            elif event_type == "receive":
                recipient = html.escape(ev.get("recipient", "?"))
                had = "\u2709 msgs" if ev.get("had_messages") else "empty"
                desc_parts.append(
                    f'<span class="comm-recipient">{recipient}</span> '
                    f'<span class="comm-arrow" style="color:{style["color"]}">\u25c0\u2500\u2500 receive</span> '
                    f'({had})'
                )
            elif event_type == "ack":
                msg_id = html.escape(str(ev.get("msg_id", "")))
                desc_parts.append(
                    f'<span class="comm-id">#{msg_id}</span> '
                    f'<span style="color:{style["color"]}">\u2713 ack \u2192 processed</span>'
                )
            elif event_type == "log-notify":
                msg_id = html.escape(str(ev.get("msg_id", "")))
                recipient = html.escape(ev.get("recipient", "?"))
                ntype = html.escape(ev.get("notify_type", "reminder"))
                desc_parts.append(
                    f'\U0001f514 <span class="comm-sender">watcher</span> \u2192 '
                    f'<span class="comm-recipient">{recipient}</span> '
                    f'{ntype} <span class="comm-id">#{msg_id}</span>'
                )
            elif event_type == "count-pending":
                recipient = html.escape(ev.get("recipient", "?"))
                count = html.escape(str(ev.get("count", "?")))
                desc_parts.append(
                    f'<span class="comm-recipient">{recipient}</span> '
                    f'pending = <strong>{count}</strong>'
                )
            elif event_type == "stale":
                count = html.escape(str(ev.get("count", "0")))
                desc_parts.append(f'stale check \u2192 {count} found')
            elif event_type == "escalations":
                count = html.escape(str(ev.get("count", "0")))
                desc_parts.append(
                    f'<span style="color:{style["color"]}">\u26a0 escalation check \u2192 {count} found</span>'
                )

            desc_html = "\n".join(desc_parts)
            cards.append(f"""
            <div class="timeline-event">
                <div class="event-dot" style="background:{style['color']}"></div>
                <div class="event-content">
                    <span class="event-time">{ts}</span>
                    <span class="event-badge" style="background:{style['color']}20;color:{style['color']}">{style['icon']} {style['label']}</span>
                    <div class="event-desc">{desc_html}</div>
                </div>
            </div>""")

        cards_html = "\n".join(cards)
        sections.append(f"""
        <details class="timeline-suite">
            <summary>
                <span class="suite-name">{html.escape(suite_name)}</span>
                <span class="suite-stats"><span class="badge" style="background:#1f2937;color:#8b949e">{len(events)} events</span></span>
            </summary>
            <div class="timeline-container">
                {cards_html}
            </div>
        </details>""")

    return "\n".join(sections)


def generate_flow_summary_html(comms):
    """Generate sender→recipient flow summary from send events."""
    if not comms:
        return ""

    sends = [e for e in comms if e.get("event") == "send"]
    if not sends:
        return '<p style="color:var(--text-dim)">No send events recorded.</p>'

    # Aggregate: (from, to) → {total, types: {type: count}}
    flows = OrderedDict()
    for ev in sends:
        key = (ev.get("from", "?"), ev.get("to", "?"))
        if key not in flows:
            flows[key] = {"total": 0, "types": OrderedDict()}
        flows[key]["total"] += 1
        mt = ev.get("msg_type", "unknown")
        flows[key]["types"][mt] = flows[key]["types"].get(mt, 0) + 1

    cards = []
    for (sender, recipient), data in flows.items():
        total = data["total"]
        unit = "msg" if total == 1 else "msgs"
        type_badges = " ".join(
            f'<span class="flow-type-badge">{html.escape(t)}\u00d7{c}</span>'
            for t, c in data["types"].items()
        )
        cards.append(f"""
        <div class="flow-card">
            <span class="flow-sender">{html.escape(sender)}</span>
            <span class="flow-arrow">\u2550\u2550\u2550\u2550\u2550\u25b6</span>
            <span class="flow-recipient">{html.escape(recipient)}</span>
            <span class="flow-count">{total} {unit}</span>
            <div class="flow-types">{type_badges}</div>
        </div>""")

    return "\n".join(cards)


def generate_html(results, elapsed, total, passed, failed, comms=None):
    """Generate HTML report string."""
    comms = comms or []
    suites = group_by_suite(results)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pass_rate = (passed / total * 100) if total > 0 else 0
    status_class = "success" if failed == 0 else "failure"
    status_text = "ALL PASSED" if failed == 0 else f"{failed} FAILED"

    suite_cards = []
    for suite_name, items in suites.items():
        s_pass = sum(1 for i in items if i["result"] == "PASS")
        s_fail = sum(1 for i in items if i["result"] != "PASS")
        s_total = len(items)
        s_class = "suite-pass" if s_fail == 0 else "suite-fail"

        rows = []
        for item in items:
            is_pass = item["result"] == "PASS"
            badge = '<span class="badge pass">PASS</span>' if is_pass else '<span class="badge fail">FAIL</span>'
            detail = html.escape(item.get("detail", ""))
            detail_cell = f'<span class="detail">{detail}</span>' if detail else ""
            rows.append(
                f'<tr class="{"row-pass" if is_pass else "row-fail"}">'
                f"<td>{badge}</td>"
                f"<td>{html.escape(item['label'])}</td>"
                f"<td>{detail_cell}</td>"
                f"</tr>"
            )

        rows_html = "\n".join(rows)
        suite_cards.append(f"""
        <details class="{s_class}" {"" if s_fail > 0 else ""}>
            <summary>
                <span class="suite-name">{html.escape(suite_name)}</span>
                <span class="suite-stats">
                    <span class="badge pass">{s_pass}</span>
                    {"<span class='badge fail'>" + str(s_fail) + "</span>" if s_fail > 0 else ""}
                    <span class="suite-total">/ {s_total}</span>
                </span>
            </summary>
            <table>
                <thead><tr><th>Result</th><th>Test</th><th>Detail</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </details>
        """)

    cards_html = "\n".join(suite_cards)

    timeline_html = generate_timeline_html(comms)
    flow_html = generate_flow_summary_html(comms)
    has_comms = bool(comms)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Memory Vault Test Report</title>
<style>
:root {{
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-dim: #8b949e;
    --green: #3fb950;
    --green-bg: #0d2818;
    --red: #f85149;
    --red-bg: #2d1117;
    --blue: #58a6ff;
    --purple: #bc8cff;
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
}}

.container {{ max-width: 900px; margin: 0 auto; }}

h1 {{
    font-size: 1.5rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
}}

.meta {{ color: var(--text-dim); font-size: 0.85rem; margin-bottom: 1.5rem; }}

/* Dashboard */
.dashboard {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
}}

.card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.2rem;
    text-align: center;
}}

.card .value {{
    font-size: 2rem;
    font-weight: 700;
    display: block;
}}

.card .label {{
    font-size: 0.8rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

.card.status {{ border-top: 3px solid; }}
.card.success {{ border-top-color: var(--green); }}
.card.success .value {{ color: var(--green); }}
.card.failure {{ border-top-color: var(--red); }}
.card.failure .value {{ color: var(--red); }}
.card .value.green {{ color: var(--green); }}
.card .value.red {{ color: var(--red); }}
.card .value.blue {{ color: var(--blue); }}

/* Progress bar */
.progress-bar {{
    background: var(--red-bg);
    border-radius: 6px;
    height: 8px;
    margin-bottom: 2rem;
    overflow: hidden;
}}

.progress-fill {{
    background: var(--green);
    height: 100%;
    border-radius: 6px;
    transition: width 0.3s;
}}

/* Suites */
details {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 0.75rem;
    overflow: hidden;
}}

details.suite-fail {{ border-left: 3px solid var(--red); }}
details.suite-pass {{ border-left: 3px solid var(--green); }}

details[open] summary {{ border-bottom: 1px solid var(--border); }}

summary {{
    cursor: pointer;
    padding: 0.8rem 1.2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 500;
    user-select: none;
}}

summary:hover {{ background: rgba(255,255,255,0.03); }}

.suite-name {{ flex: 1; }}
.suite-stats {{ display: flex; align-items: center; gap: 0.4rem; }}
.suite-total {{ color: var(--text-dim); font-size: 0.85rem; }}

/* Badges */
.badge {{
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.3px;
}}

.badge.pass {{ background: var(--green-bg); color: var(--green); }}
.badge.fail {{ background: var(--red-bg); color: var(--red); }}

/* Table */
table {{
    width: 100%;
    border-collapse: collapse;
}}

th {{
    text-align: left;
    padding: 0.5rem 1rem;
    font-size: 0.75rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    background: rgba(0,0,0,0.2);
}}

td {{
    padding: 0.5rem 1rem;
    border-top: 1px solid var(--border);
    font-size: 0.9rem;
}}

td:first-child {{ width: 70px; }}

tr.row-fail {{ background: rgba(248, 81, 73, 0.05); }}

.detail {{
    color: var(--text-dim);
    font-size: 0.8rem;
    font-family: 'SF Mono', 'Fira Code', monospace;
}}

/* Footer */
.footer {{
    text-align: center;
    color: var(--text-dim);
    font-size: 0.75rem;
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
}}

/* Communication Timeline */
.section-title {{
    font-size: 1.3rem;
    font-weight: 600;
    margin: 2rem 0 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
}}

.timeline-suite {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 0.75rem;
    border-left: 3px solid var(--blue);
}}

.timeline-container {{
    padding: 1rem 1.2rem;
    position: relative;
}}

.timeline-container::before {{
    content: '';
    position: absolute;
    left: 2rem;
    top: 0.5rem;
    bottom: 0.5rem;
    width: 2px;
    background: var(--border);
}}

.timeline-event {{
    display: flex;
    align-items: flex-start;
    gap: 0.8rem;
    padding: 0.4rem 0;
    position: relative;
    padding-left: 1.5rem;
}}

.event-dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 0.35rem;
    z-index: 1;
}}

.event-content {{
    flex: 1;
    min-width: 0;
}}

.event-time {{
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.75rem;
    color: var(--text-dim);
    margin-right: 0.5rem;
}}

.event-badge {{
    display: inline-block;
    padding: 0.1rem 0.45rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.3px;
    margin-right: 0.3rem;
}}

.event-desc {{
    margin-top: 0.2rem;
    font-size: 0.85rem;
}}

.event-payload {{
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.75rem;
    color: var(--text-dim);
    background: rgba(0,0,0,0.3);
    padding: 0.3rem 0.5rem;
    border-radius: 4px;
    margin-top: 0.2rem;
    word-break: break-all;
    max-width: 600px;
}}

.comm-sender {{
    color: var(--blue);
    font-weight: 500;
}}

.comm-recipient {{
    color: var(--green);
    font-weight: 500;
}}

.comm-arrow {{
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.8rem;
}}

.comm-id {{
    color: var(--purple);
    font-size: 0.8rem;
}}

/* Flow Summary */
.flow-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.8rem 1.2rem;
    margin-bottom: 0.5rem;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.6rem;
}}

.flow-sender {{
    color: var(--blue);
    font-weight: 600;
    min-width: 100px;
}}

.flow-arrow {{
    font-family: 'SF Mono', 'Fira Code', monospace;
    color: var(--text-dim);
    font-size: 0.9rem;
}}

.flow-recipient {{
    color: var(--green);
    font-weight: 600;
    min-width: 100px;
}}

.flow-count {{
    color: var(--text);
    font-weight: 500;
    margin-left: auto;
}}

.flow-types {{
    width: 100%;
    display: flex;
    gap: 0.3rem;
    flex-wrap: wrap;
    padding-left: 100px;
}}

.flow-type-badge {{
    display: inline-block;
    background: rgba(88, 166, 255, 0.1);
    color: var(--blue);
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
    font-size: 0.7rem;
    font-weight: 500;
}}
</style>
</head>
<body>
<div class="container">
    <h1>Memory Vault Test Report</h1>
    <div class="meta">{now} &middot; {elapsed}s elapsed</div>

    <div class="dashboard">
        <div class="card status {status_class}">
            <span class="value">{status_text}</span>
            <span class="label">Status</span>
        </div>
        <div class="card">
            <span class="value blue">{total}</span>
            <span class="label">Total</span>
        </div>
        <div class="card">
            <span class="value green">{passed}</span>
            <span class="label">Passed</span>
        </div>
        <div class="card">
            <span class="value {"red" if failed > 0 else "green"}">{failed}</span>
            <span class="label">Failed</span>
        </div>
        <div class="card">
            <span class="value blue">{pass_rate:.1f}%</span>
            <span class="label">Pass Rate</span>
        </div>
    </div>

    <div class="progress-bar">
        <div class="progress-fill" style="width: {pass_rate:.1f}%"></div>
    </div>

    {cards_html}

    {"<h2 class='section-title'>Communication Timeline</h2>" + timeline_html if has_comms else ""}

    {"<h2 class='section-title'>Flow Summary</h2>" + flow_html if has_comms else ""}

    <div class="footer">
        Generated by test-report-gen.py &middot; {len(suites)} suites &middot; {total} assertions
    </div>
</div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Convert JSONL test results to HTML report")
    parser.add_argument("--input", required=True, help="Path to JSONL results file")
    parser.add_argument("--output", required=True, help="Path to output HTML file")
    parser.add_argument("--elapsed", type=int, default=0, help="Test duration in seconds")
    parser.add_argument("--total", type=int, default=0, help="Total assertions")
    parser.add_argument("--pass", dest="passed", type=int, default=0, help="Passed count")
    parser.add_argument("--fail", type=int, default=0, help="Failed count")
    parser.add_argument("--comms", default=None, help="Path to communication events JSONL")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[error] Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    results = load_results(input_path)
    comms = load_comms(args.comms)

    # Use JSONL data for counts if CLI args are 0
    total = args.total if args.total > 0 else len(results)
    passed = args.passed if args.passed > 0 else sum(1 for r in results if r["result"] == "PASS")
    failed = args.fail if args.fail > 0 else sum(1 for r in results if r["result"] != "PASS")

    html_content = generate_html(results, args.elapsed, total, passed, failed, comms)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")

    print(f"[report] {output_path} ({total} tests, {passed} passed, {failed} failed)")


if __name__ == "__main__":
    main()
