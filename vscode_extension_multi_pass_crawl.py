#!/usr/bin/env python3
"""Multi-pass crawl of the VS Code Marketplace to close pagination coverage gaps.

The Marketplace gallery API's pagination is not stable: an identical repeated
request can return a different result set (confirmed empirically -- ~72%
overlap on an immediate retry of the same page). A single sorted sweep of
~138k extensions therefore misses a meaningful fraction of them (~27% in an
initial single-pass crawl).

This script runs several full sweeps using different sort strategies and
merges results into a SQLite store keyed by extensionId, so re-running it
(or resuming with more passes) only ever adds coverage -- it never loses
what a previous pass already found. Convergence (new extensions found per
pass) is printed after every pass so you can judge when further passes stop
paying off.
"""

import argparse
import json
import sqlite3
import time

from vscode_extension_bulk_query import fetch_page, MAX_PAGE_SIZE

# Sort strategies confirmed to produce genuinely distinct, correctly-ordered
# pagination (verified against the live API -- several other sortBy codes
# either no-op to relevance order or don't sort as their name implies).
SORT_STRATEGIES = [
    (2, 1, "title_asc"),
    (2, 2, "title_desc"),
    (1, 1, "last_updated_asc"),
    (1, 2, "last_updated_desc"),
]


def open_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS extensions ("
        "extension_id TEXT PRIMARY KEY, "
        "publisher_name TEXT, "
        "extension_name TEXT, "
        "raw_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS crawl_log ("
        "pass_number INTEGER PRIMARY KEY AUTOINCREMENT, "
        "sort_by INTEGER, sort_order INTEGER, strategy TEXT, "
        "pages INTEGER, new_unique INTEGER, run_at TEXT)"
    )
    conn.commit()
    return conn


def run_pass(conn, pass_number, sort_by, sort_order, strategy_name, page_size, delay, max_pages):
    page_number = 1
    new_unique = 0
    seen_this_pass = 0

    while True:
        if max_pages is not None and page_number > max_pages:
            print(f"    reached --max-pages limit ({max_pages}), stopping pass early")
            break

        data = fetch_page(page_number, page_size, sort_by=sort_by, sort_order=sort_order)
        results = data.get("results") or []
        extensions = results[0].get("extensions") if results else []

        if not extensions:
            break

        for ext in extensions:
            ext_id = ext.get("extensionId")
            cur = conn.execute(
                "INSERT OR IGNORE INTO extensions (extension_id, publisher_name, extension_name, raw_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    ext_id,
                    ext.get("publisher", {}).get("publisherName"),
                    ext.get("extensionName"),
                    json.dumps(ext, ensure_ascii=False),
                ),
            )
            if cur.rowcount:
                new_unique += 1

        seen_this_pass += len(extensions)
        conn.commit()

        print(f"    page {page_number}: +{len(extensions)} seen ({new_unique} new unique so far this pass)")

        page_number += 1
        time.sleep(delay)

    conn.execute(
        "INSERT INTO crawl_log (pass_number, sort_by, sort_order, strategy, pages, new_unique, run_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (pass_number, sort_by, sort_order, strategy_name, page_number - 1, new_unique),
    )
    conn.commit()
    return seen_this_pass, new_unique


def main():
    parser = argparse.ArgumentParser(description="Multi-pass VS Code Marketplace crawl merged by extensionId.")
    parser.add_argument("--db", default="vscode_extensions.db", help="SQLite store (persists across runs)")
    parser.add_argument("--passes", type=int, default=4, help="Number of additional sweeps to run this invocation")
    parser.add_argument("--page-size", type=int, default=MAX_PAGE_SIZE, help=f"Results per request (max {MAX_PAGE_SIZE})")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to sleep between requests")
    parser.add_argument("--max-pages", type=int, default=None, help="Cap pages per pass (for testing)")
    parser.add_argument("--export", default=None, help="Export deduped raw records to this JSONL path when done")
    args = parser.parse_args()

    page_size = min(args.page_size, MAX_PAGE_SIZE)
    conn = open_db(args.db)

    prior_passes = conn.execute("SELECT COUNT(*) FROM crawl_log").fetchone()[0]
    prior_total = conn.execute("SELECT COUNT(*) FROM extensions").fetchone()[0]
    print(f"Starting with {prior_total} unique extensions already in {args.db} ({prior_passes} prior passes)")

    for i in range(args.passes):
        pass_number = prior_passes + i + 1
        sort_by, sort_order, strategy_name = SORT_STRATEGIES[(pass_number - 1) % len(SORT_STRATEGIES)]
        print(f"Pass {pass_number} ({strategy_name}, sortBy={sort_by}, sortOrder={sort_order}):")

        seen, new_unique = run_pass(conn, pass_number, sort_by, sort_order, strategy_name, page_size, args.delay, args.max_pages)
        total_now = conn.execute("SELECT COUNT(*) FROM extensions").fetchone()[0]

        print(f"  Pass {pass_number} done: {seen} seen, {new_unique} newly unique, {total_now} total unique so far")

    if args.export:
        total = conn.execute("SELECT COUNT(*) FROM extensions").fetchone()[0]
        with open(args.export, "w", encoding="utf-8") as out:
            for (raw_json,) in conn.execute("SELECT raw_json FROM extensions"):
                out.write(raw_json + "\n")
        print(f"Exported {total} deduped extensions to {args.export}")

    conn.close()


if __name__ == "__main__":
    main()
