#!/usr/bin/env python3
"""Suggest or create a task branch for the current repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib import get_repo_root, run, slugify


ROUTES = {"new", "continue", "review", "hotfix", "ship"}


def current_branch(root: Path, is_git_repo: bool) -> str | None:
    if not is_git_repo:
        return None
    result = run(["git", "branch", "--show-current"], root)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def branch_exists(root: Path, name: str) -> bool:
    result = run(["git", "rev-parse", "--verify", name], root)
    return result.returncode == 0


def build_branch_name(title: str, route: str, prefix: str) -> str:
    normalized_prefix = prefix.strip("/")
    slug = slugify(title)
    if normalized_prefix:
        return f"{normalized_prefix}/{route}-{slug}"
    return f"{route}-{slug}"


def maybe_create_branch(root: Path, name: str, create: bool) -> dict[str, Any]:
    if not create:
        return {"created": False, "switched": False, "error": None}

    if branch_exists(root, name):
        result = run(["git", "switch", name], root)
        return {
            "created": False,
            "switched": result.returncode == 0,
            "error": (result.stderr.strip() or None) if result.returncode != 0 else None,
        }

    result = run(["git", "switch", "-c", name], root)
    return {
        "created": result.returncode == 0,
        "switched": result.returncode == 0,
        "error": (result.stderr.strip() or None) if result.returncode != 0 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("title", help="Task title used to derive the branch name")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--route", default="new", choices=sorted(ROUTES))
    parser.add_argument("--prefix", default="codex", help="Branch prefix, default: codex")
    parser.add_argument("--create", action="store_true", help="Create or switch to the branch")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    repo_root, is_git_repo = get_repo_root(Path(args.repo))
    branch_name = build_branch_name(args.title, args.route, args.prefix)
    payload: dict[str, Any] = {
        "repo_root": str(repo_root),
        "is_git_repo": is_git_repo,
        "current_branch": current_branch(repo_root, is_git_repo),
        "suggested_branch": branch_name,
        "route": args.route,
        "created": False,
        "switched": False,
        "error": None,
    }

    if args.create:
        if not is_git_repo:
            payload["error"] = "Cannot create a branch outside a git repository."
        else:
            payload.update(maybe_create_branch(repo_root, branch_name, create=True))
            payload["current_branch"] = current_branch(repo_root, True)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"repo_root: {payload['repo_root']}")
        print(f"is_git_repo: {payload['is_git_repo']}")
        print(f"current_branch: {payload['current_branch'] or 'n/a'}")
        print(f"suggested_branch: {payload['suggested_branch']}")
        print(f"route: {payload['route']}")
        print(f"created: {payload['created']}")
        print(f"switched: {payload['switched']}")
        if payload["error"]:
            print(f"error: {payload['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
