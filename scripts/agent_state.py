#!/usr/bin/env python3
"""Manage lightweight persistent state for the linc_codebuddy agent."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from lib import atomic_write_json, get_repo_root, now_iso


DEFAULT_STATE_RELATIVE = Path(".codex/linc_codebuddy/state.json")
SCHEMA_VERSION = 2


def state_path_for_repo(repo_root: Path) -> Path:
    return repo_root / DEFAULT_STATE_RELATIVE


def default_state(repo_root: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "repo_root": str(repo_root),
        "last_route": None,
        "last_mode": None,
        "last_work_item": None,
        "last_summary": None,
        "last_patrol": None,
        "work_item_history": [],
        "notes": [],
        "active": {
            "change_id": None,
            "work_item_id": None,
            "task_id": None,
            "phase": None,
            "next_action": None,
            "level": None,
        },
        "blocking": [],
        "migration_history": [],
        "classification_history": [],
        "updated_at": now_iso(),
    }


def ensure_state(repo_root: Path) -> Path:
    path = state_path_for_repo(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write_json(path, default_state(repo_root))
    return path


def load_state(repo_root: Path) -> tuple[Path, dict[str, Any]]:
    path = ensure_state(repo_root)
    recovered = False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = default_state(repo_root)
            recovered = True
    except (json.JSONDecodeError, OSError):
        data = default_state(repo_root)
        recovered = True
    original_version = int(data.get("schema_version", 1))
    before_normalization = json.dumps(data, ensure_ascii=False, sort_keys=True)
    data = migrate_state(data, repo_root)
    if "repo_root" not in data:
        data["repo_root"] = str(repo_root)
    if "notes" not in data or not isinstance(data["notes"], list):
        data["notes"] = []
    if "work_item_history" not in data or not isinstance(data["work_item_history"], list):
        data["work_item_history"] = []
    normalized = json.dumps(data, ensure_ascii=False, sort_keys=True) != before_normalization
    if original_version < SCHEMA_VERSION:
        backup_path = path.with_suffix(f".v{original_version}.bak")
        if path.exists() and not backup_path.exists():
            shutil.copy2(path, backup_path)
        atomic_write_json(path, data)
    elif normalized or recovered:
        atomic_write_json(path, data)
    return path, data


def migrate_state(data: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    version = int(data.get("schema_version", 1))
    if version >= SCHEMA_VERSION:
        data["repo_root"] = str(repo_root)
        active = data.setdefault("active", {})
        active.setdefault("change_id", None)
        active.setdefault("work_item_id", None)
        active.setdefault("task_id", None)
        active.setdefault("phase", None)
        active.setdefault("next_action", None)
        active.setdefault("level", None)
        data.setdefault("blocking", [])
        data.setdefault("migration_history", [])
        data.setdefault("classification_history", [])
        return data

    migrated = dict(data)
    migrated["schema_version"] = SCHEMA_VERSION
    migrated["repo_root"] = str(repo_root)
    migrated.setdefault(
        "active",
        {"change_id": None, "work_item_id": None, "task_id": None, "phase": None, "next_action": None, "level": None},
    )
    migrated.setdefault("blocking", [])
    migrated.setdefault("classification_history", [])
    history = migrated.setdefault("migration_history", [])
    history.append({"from": version, "to": SCHEMA_VERSION, "at": now_iso()})
    return migrated


def save_state(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = now_iso()
    atomic_write_json(path, data)


def print_human(data: dict[str, Any], path: Path) -> None:
    print(f"state_file: {path}")
    print(f"repo_root: {data.get('repo_root')}")
    print(f"last_route: {data.get('last_route') or 'n/a'}")
    print(f"last_mode: {data.get('last_mode') or 'n/a'}")
    print(f"last_work_item: {data.get('last_work_item') or 'n/a'}")
    print(f"last_summary: {data.get('last_summary') or 'n/a'}")
    print(f"updated_at: {data.get('updated_at') or 'n/a'}")
    patrol = data.get("last_patrol") or {}
    if patrol:
        print(f"last_patrol.recommended_route: {patrol.get('recommended_route') or 'n/a'}")
        print(f"last_patrol.patrolled_at: {patrol.get('patrolled_at') or 'n/a'}")
    if data.get("notes"):
        print("notes:")
        for item in data["notes"]:
            print(f"  - {item}")
    history = data.get("work_item_history") or []
    if history:
        print("work_item_history:")
        for entry in history[-5:]:
            print(f"  - [{entry.get('route', '?')}] {entry.get('work_item', '?')} ({entry.get('timestamp', '?')})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_command_json(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--json", action="store_true", dest="command_json", help="Print JSON output")

    show_parser = subparsers.add_parser("show", help="Show current agent state")
    add_command_json(show_parser)

    set_parser = subparsers.add_parser("set", help="Update current agent state")
    add_command_json(set_parser)
    set_parser.add_argument("--route", choices=["new", "continue", "review", "hotfix", "ship"])
    set_parser.add_argument("--mode", choices=["normal", "fast"])
    set_parser.add_argument("--work-item", help="Work item path or title")
    set_parser.add_argument("--summary", help="Short summary")
    set_parser.add_argument("--work-item-id", help="Stable work item ID")
    set_parser.add_argument("--task-id", help="Stable active task ID")
    set_parser.add_argument("--next-action", help="Deterministic next action")
    set_parser.add_argument("--level", choices=["L0", "L1", "L2", "L3"])
    set_parser.add_argument("--classification", help="JSON classification record")

    note_parser = subparsers.add_parser("note", help="Append a note")
    add_command_json(note_parser)
    note_parser.add_argument("text", help="Note text to append")

    patrol_parser = subparsers.add_parser("patrol", help="Write the last patrol snapshot")
    add_command_json(patrol_parser)
    patrol_parser.add_argument("--recommended-route", help="Recommended route from patrol")
    patrol_parser.add_argument("--summary", help="Patrol summary")

    clear_parser = subparsers.add_parser("clear", help="Clear selected fields")
    add_command_json(clear_parser)
    clear_parser.add_argument("--notes", action="store_true", help="Clear notes")
    clear_parser.add_argument("--patrol", action="store_true", help="Clear patrol snapshot")

    args = parser.parse_args()
    repo_root, _ = get_repo_root(Path(args.repo))
    path, data = load_state(repo_root)

    if args.command == "set":
        if args.route is not None:
            data["last_route"] = args.route
        if args.mode is not None:
            data["last_mode"] = args.mode
        if args.work_item is not None:
            data["last_work_item"] = args.work_item
            data["work_item_history"].append(
                {
                    "work_item": args.work_item,
                    "route": args.route or data.get("last_route"),
                    "timestamp": now_iso(),
                }
            )
        if args.summary is not None:
            data["last_summary"] = args.summary
        active = data.setdefault("active", {})
        if args.work_item_id is not None:
            active["work_item_id"] = args.work_item_id
        if args.task_id is not None:
            active["task_id"] = args.task_id
        if args.next_action is not None:
            active["next_action"] = args.next_action
        if args.level is not None:
            active["level"] = args.level
        if args.classification is not None:
            record = json.loads(args.classification)
            record.setdefault("at", now_iso())
            data.setdefault("classification_history", []).append(record)
        save_state(path, data)
    elif args.command == "note":
        data["notes"].append(args.text)
        save_state(path, data)
    elif args.command == "patrol":
        data["last_patrol"] = {
            "patrolled_at": now_iso(),
            "recommended_route": args.recommended_route,
            "summary": args.summary,
        }
        save_state(path, data)
    elif args.command == "clear":
        if args.notes:
            data["notes"] = []
        if args.patrol:
            data["last_patrol"] = None
        save_state(path, data)

    output_json = args.json or getattr(args, "command_json", False)
    if output_json:
        payload = {"state_file": str(path), "state": data}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(data, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
