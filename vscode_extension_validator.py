#!/usr/bin/env python3
"""Tier VS Code Marketplace extensions for a bank security baseline review.

Reads the raw JSONL produced by vscode_extension_bulk_query.py --raw and
scores each extension into a review tier based on publisher domain
verification, Marketplace validation status, and adoption. Writes a CSV
review queue (Tiers A and B) for manual vetting; Tier C (long tail) is
only summarized, not dumped, since it's the bulk of the 135k extensions
and isn't worth reviewing individually.

This is metadata triage, not a code/security scan. Anything promoted out
of the review queue into an actual allowlist still needs its source
inspected (see repositoryUrl) before approval.
"""

import argparse
import csv
import json

TIER_EXCLUDED = "EXCLUDED_UNPUBLISHED_OR_LOCKED"
TIER_A = "A_VERIFIED_PUBLISHER_DOMAIN"
TIER_B = "B_HIGH_ADOPTION_UNVERIFIED"
TIER_C = "C_LOW_PRIORITY_LONG_TAIL"

REPO_PROPERTY_KEYS = (
    "Microsoft.VisualStudio.Services.Links.Source",
    "Microsoft.VisualStudio.Services.Links.GitHub",
    "Microsoft.VisualStudio.Services.Links.Repository",
    "Microsoft.VisualStudio.Services.Links.Getstarted",
)

CSV_FIELDS = [
    "tier",
    "publisherName",
    "publisherDomain",
    "isDomainVerified",
    "extensionId",
    "extensionName",
    "displayName",
    "latestVersion",
    "installs",
    "averageRating",
    "ratingCount",
    "lastUpdated",
    "publishedDate",
    "flags",
    "repositoryUrl",
    "shortDescription",
]


def stat_value(stats, name):
    for s in stats or []:
        if s.get("statisticName") == name:
            return s.get("value")
    return None


def find_repo_url(version):
    props = {p.get("key"): p.get("value") for p in (version.get("properties") or [])}
    for key in REPO_PROPERTY_KEYS:
        value = props.get(key)
        if value:
            return value
    return None


def evaluate(extension, min_installs):
    publisher = extension.get("publisher") or {}
    flags = extension.get("flags") or ""
    flag_set = {f.strip() for f in flags.split(",")}
    versions = extension.get("versions") or []
    latest = versions[0] if versions else {}
    stats = extension.get("statistics") or []
    installs = stat_value(stats, "install") or 0

    is_domain_verified = bool(publisher.get("isDomainVerified"))
    is_validated = "validated" in flag_set
    is_unpublished = "unpublished" in flag_set
    is_locked = "locked" in flag_set

    if is_unpublished or is_locked:
        tier = TIER_EXCLUDED
    elif is_domain_verified and is_validated:
        tier = TIER_A
    elif is_validated and installs >= min_installs:
        tier = TIER_B
    else:
        tier = TIER_C

    return {
        "tier": tier,
        "publisherName": publisher.get("publisherName"),
        "publisherDomain": publisher.get("domain"),
        "isDomainVerified": is_domain_verified,
        "extensionId": extension.get("extensionId"),
        "extensionName": extension.get("extensionName"),
        "displayName": extension.get("displayName"),
        "latestVersion": latest.get("version"),
        "installs": installs,
        "averageRating": stat_value(stats, "averagerating"),
        "ratingCount": stat_value(stats, "ratingcount"),
        "lastUpdated": extension.get("lastUpdated"),
        "publishedDate": extension.get("publishedDate"),
        "flags": flags,
        "repositoryUrl": find_repo_url(latest),
        "shortDescription": extension.get("shortDescription"),
    }


def main():
    parser = argparse.ArgumentParser(description="Tier VS Code Marketplace extensions into a security review queue.")
    parser.add_argument("--input", default="../vscode_extensions_full.jsonl", help="Raw JSONL from the bulk crawler")
    parser.add_argument("--output", default="vscode_extensions_review_queue.csv", help="CSV output path")
    parser.add_argument("--min-installs", type=int, default=50000, help="Install threshold for Tier B (default: 50000)")
    parser.add_argument("--include-tier-c", action="store_true", help="Also write Tier C (long tail) rows to the CSV")
    args = parser.parse_args()

    by_extension_id = {}
    duplicate_lines = 0

    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            extension = json.loads(line)
            row = evaluate(extension, args.min_installs)
            ext_id = row["extensionId"]

            existing = by_extension_id.get(ext_id)
            if existing is not None:
                duplicate_lines += 1
                if row["installs"] <= existing["installs"]:
                    continue
            by_extension_id[ext_id] = row

    counts = {TIER_EXCLUDED: 0, TIER_A: 0, TIER_B: 0, TIER_C: 0}
    rows = []
    for row in by_extension_id.values():
        counts[row["tier"]] += 1
        if row["tier"] in (TIER_A, TIER_B) or (args.include_tier_c and row["tier"] == TIER_C):
            rows.append(row)

    rows.sort(key=lambda r: (r["tier"], -r["installs"]))

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    total = sum(counts.values())
    print(f"Processed {total} unique extensions ({duplicate_lines} duplicate lines collapsed):")
    print(f"  {TIER_A}: {counts[TIER_A]} (domain-verified publisher + Marketplace-validated)")
    print(f"  {TIER_B}: {counts[TIER_B]} (validated, unverified publisher, >= {args.min_installs} installs)")
    print(f"  {TIER_C}: {counts[TIER_C]} (long tail, not written unless --include-tier-c)")
    print(f"  {TIER_EXCLUDED}: {counts[TIER_EXCLUDED]} (unpublished or locked, never candidates)")
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
