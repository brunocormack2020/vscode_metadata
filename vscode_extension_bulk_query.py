#!/usr/bin/env python3
"""Crawl the entire VS Code Marketplace and dump extension metadata to JSONL.

Paginates through all extensions (~138k as of writing) sorted by title for
stable, gap-free pagination, and writes one JSON object per line so the
output can be processed without loading everything into memory. Supports
resuming an interrupted crawl via a sidecar progress file.
"""

import argparse
import json
import time
import urllib.error

from vscode_extension_query import build_payload, query_marketplace, summarize

SORT_BY_TITLE = 2
SORT_ORDER_ASC = 1
MAX_PAGE_SIZE = 1000
MAX_RETRIES = 5


def progress_path(output_path):
    return output_path + ".progress.json"


def load_progress(output_path):
    try:
        with open(progress_path(output_path), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_progress(output_path, last_completed_page):
    with open(progress_path(output_path), "w", encoding="utf-8") as f:
        json.dump({"last_completed_page": last_completed_page}, f)


def fetch_page(page_number, page_size):
    payload = build_payload(
        page_size=page_size,
        page_number=page_number,
        sort_by=SORT_BY_TITLE,
        sort_order=SORT_ORDER_ASC,
    )
    delay = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return query_marketplace(payload, timeout=30)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if attempt == MAX_RETRIES:
                raise
            print(f"  page {page_number}: error ({e}), retrying in {delay:.0f}s [{attempt}/{MAX_RETRIES}]")
            time.sleep(delay)
            delay *= 2


def main():
    parser = argparse.ArgumentParser(description="Bulk-dump VS Code Marketplace extension metadata to JSONL.")
    parser.add_argument("--output", default="vscode_extensions_full.jsonl", help="Output JSONL file")
    parser.add_argument("--page-size", type=int, default=MAX_PAGE_SIZE, help=f"Results per request (max {MAX_PAGE_SIZE})")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to sleep between requests (default: 0.5)")
    parser.add_argument("--max-pages", type=int, default=None, help="Stop after this many pages (for testing)")
    parser.add_argument("--resume", action="store_true", help="Resume from the last completed page in the progress file")
    parser.add_argument("--raw", action="store_true", help="Write full raw extension objects instead of the summary")
    args = parser.parse_args()

    page_size = min(args.page_size, MAX_PAGE_SIZE)
    start_page = 1
    file_mode = "w"

    if args.resume:
        progress = load_progress(args.output)
        if progress:
            start_page = progress["last_completed_page"] + 1
            file_mode = "a"
            print(f"Resuming from page {start_page}")

    total_written = 0
    page_number = start_page

    with open(args.output, file_mode, encoding="utf-8") as out:
        while True:
            if args.max_pages is not None and (page_number - start_page) >= args.max_pages:
                print(f"Reached --max-pages limit ({args.max_pages}), stopping.")
                break

            data = fetch_page(page_number, page_size)
            results = data.get("results") or []
            extensions = results[0].get("extensions") if results else []

            if not extensions:
                print(f"Page {page_number}: no more extensions, done.")
                break

            for ext in extensions:
                record = ext if args.raw else summarize(ext)
                out.write(json.dumps(record, ensure_ascii=False) + "\n")

            out.flush()
            total_written += len(extensions)
            save_progress(args.output, page_number)

            print(f"Page {page_number}: +{len(extensions)} extensions (total written this run: {total_written})")

            page_number += 1
            time.sleep(args.delay)

    print(f"Done. Wrote {total_written} extensions to {args.output}")


if __name__ == "__main__":
    main()
