#!/usr/bin/env python3
"""CLI to query the VS Code Marketplace (Visual Studio Gallery) API for extension metadata."""

import argparse
import json
import urllib.request
import urllib.error

API_URL = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
API_VERSION = "3.0-preview.1"

# Flags bitmask — pulls back the metadata fields we care about.
# 0x1   IncludeVersions
# 0x2   IncludeFiles
# 0x10  IncludeVersionProperties
# 0x80  IncludeStatistics
# 0x100 IncludeLatestVersionOnly
FLAGS = 0x1 | 0x2 | 0x10 | 0x80 | 0x100

FILTER_TYPE_EXTENSION_NAME = 7  # exact "publisher.extension-name" lookup
FILTER_TYPE_SEARCH_TEXT = 10
FILTER_TYPE_TARGET = 8


def build_payload(search_text=None, extension_name=None, page_size=25, page_number=1, sort_by=0, sort_order=0):
    criteria = [{"filterType": FILTER_TYPE_TARGET, "value": "Microsoft.VisualStudio.Code"}]

    if extension_name:
        criteria.append({"filterType": FILTER_TYPE_EXTENSION_NAME, "value": extension_name})
    elif search_text:
        criteria.append({"filterType": FILTER_TYPE_SEARCH_TEXT, "value": search_text})

    return {
        "filters": [
            {
                "criteria": criteria,
                "pageNumber": page_number,
                "pageSize": page_size,
                "sortBy": sort_by,
                "sortOrder": sort_order,
            }
        ],
        "assetTypes": [],
        "flags": FLAGS,
    }


def query_marketplace(payload, timeout=20):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": f"application/json;api-version={API_VERSION}",
            "User-Agent": "vscode-extension-query/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def stat_value(stats, name):
    for s in stats or []:
        if s.get("statisticName") == name:
            return s.get("value")
    return None


def summarize(extension):
    versions = extension.get("versions") or []
    latest = versions[0] if versions else {}
    stats = extension.get("statistics") or []

    return {
        "publisher": extension.get("publisher", {}).get("publisherName"),
        "extensionName": extension.get("extensionName"),
        "displayName": extension.get("displayName"),
        "extensionId": extension.get("extensionId"),
        "shortDescription": extension.get("shortDescription"),
        "latestVersion": latest.get("version"),
        "lastUpdated": extension.get("lastUpdated"),
        "publishedDate": extension.get("publishedDate"),
        "installs": stat_value(stats, "install"),
        "averageRating": stat_value(stats, "averagerating"),
        "ratingCount": stat_value(stats, "ratingcount"),
        "trendingWeekly": stat_value(stats, "trendingweekly"),
        "categories": extension.get("categories"),
        "tags": extension.get("tags"),
    }


def main():
    parser = argparse.ArgumentParser(description="Query VS Code Marketplace extension metadata.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="Exact extension id, e.g. ms-python.python")
    group.add_argument("--search", help="Free-text search query, e.g. 'python linter'")
    parser.add_argument("--limit", type=int, default=10, help="Max results to return (default: 10)")
    parser.add_argument("--raw", action="store_true", help="Print raw API JSON instead of the summary")
    args = parser.parse_args()

    payload = build_payload(search_text=args.search, extension_name=args.id, page_size=args.limit)
    try:
        data = query_marketplace(payload)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} error from marketplace API: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Network error contacting marketplace API: {e.reason}")

    if args.raw:
        print(json.dumps(data, indent=2))
        return

    results = data.get("results") or []
    extensions = results[0].get("extensions") if results else []

    if not extensions:
        print("No extensions found.")
        return

    for ext in extensions:
        info = summarize(ext)
        print(f"{info['publisher']}.{info['extensionName']}  -  {info['displayName']}")
        print(f"  Version:     {info['latestVersion']}")
        print(f"  Installs:    {info['installs']}")
        print(f"  Rating:      {info['averageRating']} ({info['ratingCount']} ratings)")
        print(f"  Updated:     {info['lastUpdated']}")
        print(f"  Description: {info['shortDescription']}")
        print()


if __name__ == "__main__":
    main()
