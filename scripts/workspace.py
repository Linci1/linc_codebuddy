#!/usr/bin/env python3
"""Manage the cross-repo workspace manifest (~/.linc_codebuddy/workspace.json)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_state import load_state
from lifecycle import load_active_change

WORKSPACE_DIR = Path.home() / ".linc_codebuddy"
WORKSPACE_PATH = WORKSPACE_DIR / "workspace.json"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_workspace() -> dict[str, Any]:
    data = read_json(WORKSPACE_PATH)
    if "repos" not in data:
        data["repos"] = {}
    return data


def save_workspace(data: dict[str, Any]) -> None:
    write_json(WORKSPACE_PATH, data)


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _get_git_branch(root: Path) -> str | None:
    result = _run(["git", "branch", "--show-current"], root)
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def _get_git_dirty(root: Path) -> bool:
    result = _run(["git", "status", "--porcelain"], root)
    if result.returncode != 0:
        return False
    return any(line.strip() for line in result.stdout.splitlines())


def register(repo_root: Path, alias: str | None = None) -> str:
    """Register a repository in the workspace manifest. Returns the alias used."""
    workspace = load_workspace()
    repo_key = alias or repo_root.name
    repo_key = repo_key.strip()
    if not repo_key:
        repo_key = repo_root.name

    key = repo_key
    index = 2
    while key in workspace["repos"] and workspace["repos"][key]["path"] != str(repo_root.resolve()):
        key = f"{repo_key}-{index}"
        index += 1

    branch = _get_git_branch(repo_root)
    is_dirty = _get_git_dirty(repo_root)
    workspace["repos"][key] = {
        "path": str(repo_root.resolve()),
        "alias": key,
        "registered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "last_branch": branch,
        "last_dirty": is_dirty,
    }
    save_workspace(workspace)
    return key


def remove(identifier: str) -> bool:
    """Remove a repo by alias or path. Returns True if removed."""
    workspace = load_workspace()
    repos = workspace.get("repos", {})

    if identifier in repos:
        del repos[identifier]
        save_workspace(workspace)
        return True

    resolved = str(Path(identifier).resolve())
    for key, info in list(repos.items()):
        if str(Path(info["path"]).resolve()) == resolved:
            del repos[key]
            save_workspace(workspace)
            return True

    return False


def list_repos() -> list[dict[str, Any]]:
    """List all registered repos with their status."""
    workspace = load_workspace()
    repos = workspace.get("repos", {})
    result: list[dict[str, Any]] = []
    for key, info in sorted(repos.items()):
        result.append(dict(info, alias=key))
    return result


def update_status(identifier: str | None = None) -> list[dict[str, Any]]:
    """Update status for one repo or all repos. Returns updated list."""
    workspace = load_workspace()
    repos = workspace.get("repos", {})

    if identifier:
        items = {identifier: repos[identifier]} if identifier in repos else {}
    else:
        items = repos

    changed = False
    for key, info in items.items():
        repo_path = Path(info["path"])
        if not repo_path.exists():
            continue
        branch = _get_git_branch(repo_path)
        is_dirty = _get_git_dirty(repo_path)
        if branch != info.get("last_branch") or is_dirty != info.get("last_dirty"):
            info["last_branch"] = branch
            info["last_dirty"] = is_dirty
            info["last_checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            changed = True

    if changed:
        save_workspace(workspace)

    return list_repos()


def summarize_repos(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return repository, lifecycle, blocker, and deterministic next-action facts."""
    rows = []
    for info in repos:
        repo_path = Path(info["path"])
        row = {
            **info, "exists": repo_path.exists(), "change_id": None, "phase": None,
            "level": None, "blocking": [], "next_action": None,
        }
        if repo_path.exists():
            _, state = load_state(repo_path)
            active = state.get("active", {})
            row.update({
                "change_id": active.get("change_id"), "phase": active.get("phase"),
                "level": active.get("level"), "blocking": state.get("blocking", []),
                "next_action": active.get("next_action"),
            })
            try:
                change, _ = load_active_change(repo_path)
                row.update({"change_id": change["id"], "phase": change["phase"], "level": change["level"]})
                if change["phase"] == "verify":
                    from quality import verification_summary

                    row["next_action"] = verification_summary(repo_path, change["id"])["next_action"]
            except FileNotFoundError:
                pass
        rows.append(row)
    return rows


def status_lines(repos: list[dict[str, Any]]) -> None:
    """Print a human-readable status table."""
    if not repos:
        print("(no repos registered)")
        return

    max_alias = max(len(repo.get("alias", "?")) for repo in repos)
    header = f"{'Alias':<{max_alias}}  {'Branch':<20}  Dirty  Path"
    print(header)
    print("-" * len(header))
    for repo in repos:
        alias = repo.get("alias", "?")
        branch = repo.get("last_branch") or "n/a"
        dirty = "Y" if repo.get("last_dirty") else "N"
        path = repo.get("path", "?")
        print(f"{alias:<{max_alias}}  {branch:<20}  {dirty:<5}  {path}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Register a repository")
    add_parser.add_argument("path", help="Path to the repository")
    add_parser.add_argument("--alias", help="Optional alias for the workspace")

    remove_parser = subparsers.add_parser("remove", help="Remove a repository")
    remove_parser.add_argument("identifier", help="Alias or path to remove")

    subparsers.add_parser("list", help="List all registered repos")

    status_parser = subparsers.add_parser("status", help="Update and show repo status")
    status_parser.add_argument("identifier", nargs="?", help="Optional alias to update a single repo")

    args = parser.parse_args()

    if args.command == "add":
        alias = register(Path(args.path).resolve(), args.alias)
        print(f"Registered: {alias} -> {Path(args.path).resolve()}")

    elif args.command == "remove":
        ok = remove(args.identifier)
        if ok:
            print(f"Removed: {args.identifier}")
        else:
            print(f"Not found: {args.identifier}")

    elif args.command == "list":
        repos = list_repos()
        status_lines(repos)

    elif args.command == "status":
        repos = update_status(args.identifier)
        status_lines(repos)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
