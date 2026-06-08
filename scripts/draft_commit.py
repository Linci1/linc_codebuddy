#!/usr/bin/env python3
"""Suggest a commit message based on route, title, and changed files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from lib import get_repo_root, is_agent_metadata_path, run


DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
TEST_HINTS = ("test", "spec", "__tests__", "tests/")
CONFIG_HINTS = (
    ".github/",
    ".gitignore",
    "Dockerfile",
    "docker-compose",
    "compose.",
    "Makefile",
    "justfile",
)


def get_changed_files(root: Path) -> list[str]:
    result = run(["git", "status", "--porcelain"], root)
    if result.returncode != 0:
        return []

    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if is_agent_metadata_path(path):
            continue
        files.append(path)
    return files


def normalize_subject(title: str) -> str:
    cleaned = re.sub(r"^(feat|fix|refactor|docs|test|chore)(\([^)]+\))?:\s*", "", title, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    if not cleaned:
        return "update current task"
    return cleaned[0].lower() + cleaned[1:]


def infer_scope(files: list[str]) -> str | None:
    if not files:
        return None
    top_levels = {Path(path).parts[0] for path in files if Path(path).parts}
    if len(top_levels) == 1:
        scope = next(iter(top_levels))
        if scope and scope not in {".github"}:
            return scope.replace("_", "-")
    return None


def is_docs_only(files: list[str]) -> bool:
    return bool(files) and all(Path(path).suffix.lower() in DOC_SUFFIXES for path in files)


def is_tests_only(files: list[str]) -> bool:
    return bool(files) and all(any(hint in path for hint in TEST_HINTS) for path in files)


def is_config_only(files: list[str]) -> bool:
    return bool(files) and all(
        any(hint in path for hint in CONFIG_HINTS) or Path(path).suffix in {".yml", ".yaml", ".toml", ".json"}
        for path in files
    )


def infer_type(route: str, title: str, files: list[str]) -> str:
    lowered_title = title.lower()
    if route == "hotfix":
        return "fix"
    if is_docs_only(files) or "doc" in lowered_title:
        return "docs"
    if is_tests_only(files) or lowered_title.startswith("test"):
        return "test"
    if is_config_only(files):
        return "chore"
    if "refactor" in lowered_title:
        return "refactor"
    if "fix" in lowered_title or "bug" in lowered_title:
        return "fix"
    if route == "ship":
        return "chore"
    if route == "review":
        return "chore"
    return "feat"


def build_message(commit_type: str, scope: str | None, subject: str) -> str:
    if scope:
        return f"{commit_type}({scope}): {subject}"
    return f"{commit_type}: {subject}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--route", default="continue", choices=["new", "continue", "review", "hotfix", "ship"])
    parser.add_argument("--title", required=True, help="Task title used to derive the commit subject")
    parser.add_argument("--scope", help="Optional explicit scope")
    parser.add_argument("--body", action="append", default=[], help="Optional commit body lines")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    repo_root, _ = get_repo_root(Path(args.repo))
    changed_files = get_changed_files(repo_root)
    subject = normalize_subject(args.title)
    scope = args.scope or infer_scope(changed_files)
    commit_type = infer_type(args.route, args.title, changed_files)
    message = build_message(commit_type, scope, subject)
    payload: dict[str, Any] = {
        "repo_root": str(repo_root),
        "route": args.route,
        "commit_type": commit_type,
        "scope": scope,
        "subject": subject,
        "message": message,
        "body": args.body,
        "changed_files": changed_files,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"repo_root: {payload['repo_root']}")
        print(f"route: {payload['route']}")
        print(f"commit_type: {payload['commit_type']}")
        print(f"scope: {payload['scope'] or 'n/a'}")
        print(f"subject: {payload['subject']}")
        print(f"message: {payload['message']}")
        if payload["body"]:
            print("body:")
            for line in payload["body"]:
                print(f"  - {line}")
        if payload["changed_files"]:
            print("changed_files:")
            for path in payload["changed_files"]:
                print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
