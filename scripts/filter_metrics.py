#!/usr/bin/env python3
"""Filter an existing metrics JSON export to repos with matching contributors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path("metrics_data/data/metrics_2026-06-08_to_2026-07-31.json")

# Contributor fields searched for a username/handle match, in priority order.
DEFAULT_MATCH_FIELDS = ("login", "username", "name")


def contributor_matches(
    contributor: dict[str, Any], needles: list[str], fields: tuple[str, ...]
) -> bool:
    """True if any needle is a substring of any of the contributor's searched fields."""
    for field in fields:
        value = str(contributor.get(field, "")).lower()
        if value and any(needle in value for needle in needles):
            return True
    return False


def filter_metrics_data(
    payload: dict[str, Any],
    patterns: list[str],
    fields: tuple[str, ...] = DEFAULT_MATCH_FIELDS,
) -> dict[str, Any]:
    """Return a copy of the payload containing only matching repos and contributors."""
    needles = [pattern.lower() for pattern in patterns]
    filtered_repos: list[dict[str, Any]] = []

    for repo in payload.get("repos", []):
        contributors = repo.get("contributors") or []
        matching_contributors = [
            contributor
            for contributor in contributors
            if contributor_matches(contributor, needles, fields)
        ]
        if not matching_contributors:
            continue

        filtered_repo = dict(repo)
        filtered_repo["contributors"] = matching_contributors
        filtered_repo["committer_count"] = len(matching_contributors)
        filtered_repos.append(filtered_repo)

    filtered_payload = dict(payload)
    filtered_payload["repos"] = filtered_repos
    filtered_payload["total_repo_count"] = len(filtered_repos)
    return filtered_payload


def build_output_path(input_path: Path, patterns: list[str]) -> Path:
    if len(patterns) == 1:
        suffix = f"_filtered_{patterns[0].lower()}"
    else:
        suffix = "_filtered_multi"
    return input_path.with_name(f"{input_path.stem}{suffix}.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "patterns",
        nargs="+",
        help="One or more substrings to match against contributor usernames/names",
    )
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT, help="Path to the metrics JSON file"
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional output path")
    parser.add_argument(
        "--field",
        dest="fields",
        action="append",
        default=None,
        help=(
            "Contributor field to match against (repeatable). "
            f"Defaults to: {', '.join(DEFAULT_MATCH_FIELDS)}"
        ),
    )
    args = parser.parse_args()

    fields = tuple(args.fields) if args.fields else DEFAULT_MATCH_FIELDS

    input_path = args.input
    if not input_path.is_absolute():
        input_path = Path.cwd() / input_path

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with input_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    filtered_payload = filter_metrics_data(payload, args.patterns, fields)

    output_path = args.output or build_output_path(input_path, args.patterns)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(filtered_payload, handle, indent=2)
        handle.write("\n")

    matched = filtered_payload["total_repo_count"]
    print(
        f"Matched {matched} repo(s) for {len(args.patterns)} pattern(s); "
        f"wrote filtered metrics to {output_path}"
    )


if __name__ == "__main__":
    main()