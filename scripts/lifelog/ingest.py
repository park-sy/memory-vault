#!/usr/bin/env python3
"""Lifelog ingest — CLI entry point for logging and classifying life entries.

Usage:
    python3 scripts/lifelog/ingest.py "점심에 파스타 먹었다"
    python3 scripts/lifelog/ingest.py --source git "feat: login page added"
    python3 scripts/lifelog/ingest.py --classify-pending
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import init_db, insert_entry, get_unclassified, update_classification
from classify import classify_text


def ingest(content: str, source: str = "manual") -> None:
    """Insert entry, classify with Haiku, update classification."""
    init_db()

    # 1. Raw 즉시 저장
    entry_id = insert_entry(content=content, source=source)
    print(f"[ingest] Saved entry #{entry_id}: {content[:50]}", file=sys.stderr)

    # 2. Haiku 분류
    result = classify_text(content)

    if result:
        # 3. 분류 결과 업데이트
        update_classification(
            entry_id=entry_id,
            categories=result["categories"],
            tags=result["tags"],
            sentiment=result["sentiment"],
        )
        print(
            f"[ingest] Classified #{entry_id}: "
            f"categories={result['categories']}, "
            f"tags={result['tags']}, "
            f"sentiment={result['sentiment']}",
            file=sys.stderr,
        )
    else:
        print(f"[ingest] Classification failed for #{entry_id}, will retry later", file=sys.stderr)


def classify_pending() -> None:
    """Retry classification for unclassified entries."""
    init_db()
    entries = get_unclassified()

    if not entries:
        print("[ingest] No unclassified entries", file=sys.stderr)
        return

    print(f"[ingest] Found {len(entries)} unclassified entries", file=sys.stderr)
    success = 0

    for entry in entries:
        result = classify_text(entry.content)
        if result:
            update_classification(
                entry_id=entry.id,
                categories=result["categories"],
                tags=result["tags"],
                sentiment=result["sentiment"],
            )
            success += 1
            print(f"[ingest] Classified #{entry.id}: {result['categories']}", file=sys.stderr)
        else:
            print(f"[ingest] Still failed #{entry.id}", file=sys.stderr)

    print(f"[ingest] Classified {success}/{len(entries)} entries", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lifelog ingest CLI")
    parser.add_argument("content", nargs="?", help="Text to log")
    parser.add_argument("--source", default="manual", help="Entry source (default: manual)")
    parser.add_argument(
        "--classify-pending", action="store_true", dest="classify_pending",
        help="Retry classification for unclassified entries",
    )

    args = parser.parse_args()

    if args.classify_pending:
        classify_pending()
    elif args.content:
        ingest(args.content, source=args.source)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
