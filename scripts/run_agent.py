#!/usr/bin/env python3
"""Unified entrypoint for linc_codebuddy intake, patrol, kickoff, and ship flows."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from policy_loader import load_default_policy, load_effective_policy, write_repo_policy


SCRIPT_DIR = Path(__file__).resolve().parent
ROUTES = ["new", "continue", "review", "hotfix", "ship"]
PATROL_PRESETS = ["morning", "end-of-day", "pre-ship", "resume"]


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def get_repo_root(path: Path) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], path)
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve()
    return path.resolve()


def run_script_json(script_name: str, args: list[str], repo_root: Path) -> dict[str, Any]:
    result = run(["python3", str(SCRIPT_DIR / script_name), *args, "--json"], repo_root)
    if result.returncode != 0:
        raise RuntimeError(f"{script_name} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def maybe_preset_route(base_route: str, preset: str | None, tasks: dict[str, list[str]]) -> tuple[str, str | None]:
    if preset is None:
        return base_route, None

    active_count = len(tasks.get("Active", []))
    if preset == "pre-ship" and base_route in {"continue", "review", "idle"}:
        return "ship", "pre-ship preset biases the patrol toward ship readiness."
    if preset == "end-of-day" and base_route == "continue":
        return "ship", "end-of-day preset biases the patrol toward deciding whether to ship or park."
    if preset == "resume" and active_count > 0:
        return "continue", "resume preset prioritizes continuing active work."
    if preset == "morning" and base_route == "idle" and active_count > 0:
        return "continue", "morning preset nudges active tasks back into focus."
    return base_route, None


def print_human(payload: dict[str, Any]) -> None:
    print(f"command: {payload['command']}")
    print(f"repo_root: {payload['repo_root']}")
    if "route" in payload:
        print(f"route: {payload['route']}")
    if "mode" in payload:
        print(f"mode: {payload['mode']}")
    if "summary" in payload and payload["summary"]:
        print(f"summary: {payload['summary']}")
    if "recommended_route" in payload:
        print(f"recommended_route: {payload['recommended_route']}")
    if "work_item" in payload and payload["work_item"]:
        print(f"work_item: {payload['work_item']}")
    if "task_file" in payload and payload["task_file"]:
        print(f"task_file: {payload['task_file']}")
    if "branch_plan" in payload:
        print(f"branch_plan: {payload['branch_plan']['suggested_branch']}")
    if "commit_plan" in payload:
        print(f"commit_plan: {payload['commit_plan']['message']}")
    if payload.get("notes"):
        print("notes:")
        for item in payload["notes"]:
            print(f"  - {item}")


def command_intake(repo_root: Path) -> dict[str, Any]:
    policy, policy_meta = load_effective_policy(repo_root)
    bootstrap = run_script_json("bootstrap_repo.py", [str(repo_root)], repo_root)
    state = run_script_json("agent_state.py", ["--repo", str(repo_root), "show"], repo_root)
    return {
        "command": "intake",
        "repo_root": str(repo_root),
        "bootstrap": bootstrap,
        "state": state["state"],
        "policy": policy,
        "policy_meta": policy_meta,
        "summary": (
            f"repo_shape={bootstrap['repo_shape']}; "
            f"stack={','.join(bootstrap['stack']) or 'unknown'}; "
            f"branch={bootstrap['git']['branch'] or 'n/a'}"
        ),
    }


def command_patrol(repo_root: Path, preset: str | None, no_state_write: bool) -> dict[str, Any]:
    policy, policy_meta = load_effective_policy(repo_root)
    args = ["--repo", str(repo_root)]
    if no_state_write or not policy.get("write_patrol_to_state", True):
        args.append("--no-state-write")
    patrol = run_script_json("patrol_repo.py", args, repo_root)
    state = run_script_json("agent_state.py", ["--repo", str(repo_root), "show"], repo_root)
    recommended_route, preset_reason = maybe_preset_route(patrol["recommended_route"], preset, patrol["tasks"])
    notes = []
    if preset_reason:
        notes.append(preset_reason)
    if preset is not None:
        focus = policy.get("patrol_presets", {}).get(preset, {}).get("focus", [])
        notes.extend(focus)
    return {
        "command": "patrol",
        "repo_root": str(repo_root),
        "preset": preset,
        "recommended_route": recommended_route,
        "base_recommended_route": patrol["recommended_route"],
        "policy_meta": policy_meta,
        "policy": policy,
        "patrol": patrol,
        "state": state["state"],
        "notes": notes,
        "summary": patrol["summary"],
    }


def command_kickoff(repo_root: Path, title: str, route: str | None, mode: str | None) -> dict[str, Any]:
    policy, policy_meta = load_effective_policy(repo_root)
    patrol = run_script_json("patrol_repo.py", ["--repo", str(repo_root), "--no-state-write"], repo_root)
    resolved_route = route or patrol["recommended_route"]
    if resolved_route == "idle":
        resolved_route = "new"

    route_defaults = policy.get("route_defaults", {}).get(resolved_route, {})
    resolved_mode = mode or route_defaults.get("mode") or policy.get("default_mode", "normal")
    create_work_item = route_defaults.get("create_work_item")
    if create_work_item is None:
        create_work_item = resolved_route in policy.get("work_item", {}).get("create_on_routes", [])

    work_item_path = None
    if create_work_item:
        created = run(
            [
                "python3",
                str(SCRIPT_DIR / "create_work_item.py"),
                title,
                "--repo",
                str(repo_root),
                "--route",
                resolved_route,
                "--mode",
                resolved_mode,
            ],
            repo_root,
        )
        if created.returncode != 0:
            raise RuntimeError(f"create_work_item.py failed: {created.stderr.strip()}")
        work_item_path = created.stdout.strip()

    task_status = policy.get("work_item", {}).get("task_status_on_kickoff", "active")
    add_task = run(
        [
            "python3",
            str(SCRIPT_DIR / "sync_tasks.py"),
            "--repo",
            str(repo_root),
            "add",
            title,
            "--status",
            task_status,
            "--context",
            f"route={resolved_route}, mode={resolved_mode}",
        ],
        repo_root,
    )
    if add_task.returncode != 0:
        raise RuntimeError(f"sync_tasks.py failed: {add_task.stderr.strip()}")

    state = run(
        [
            "python3",
            str(SCRIPT_DIR / "agent_state.py"),
            "--repo",
            str(repo_root),
            "set",
            "--route",
            resolved_route,
            "--mode",
            resolved_mode,
            "--summary",
            f"kickoff {title}",
            "--work-item",
            work_item_path or title,
        ],
        repo_root,
    )
    if state.returncode != 0:
        raise RuntimeError(f"agent_state.py failed: {state.stderr.strip()}")

    return {
        "command": "kickoff",
        "repo_root": str(repo_root),
        "route": resolved_route,
        "mode": resolved_mode,
        "title": title,
        "work_item": work_item_path,
        "task_file": add_task.stdout.strip(),
        "policy_meta": policy_meta,
        "summary": f"kickoff route={resolved_route}; mode={resolved_mode}; work_item={'yes' if work_item_path else 'no'}",
    }


def command_ship(repo_root: Path, title: str) -> dict[str, Any]:
    policy, policy_meta = load_effective_policy(repo_root)
    patrol = command_patrol(repo_root, preset="pre-ship", no_state_write=True)
    branch_prefix = policy.get("branch_prefix", "codex")
    branch_plan = run_script_json(
        "prepare_branch.py",
        ["--repo", str(repo_root), "--route", "ship", "--prefix", branch_prefix, title],
        repo_root,
    )
    commit_plan = run_script_json(
        "draft_commit.py",
        ["--repo", str(repo_root), "--route", "ship", "--title", title],
        repo_root,
    )
    checks = run_script_json("suggest_checks.py", ["--repo", str(repo_root)], repo_root)
    state = run(
        [
            "python3",
            str(SCRIPT_DIR / "agent_state.py"),
            "--repo",
            str(repo_root),
            "set",
            "--route",
            "ship",
            "--mode",
            policy.get("route_defaults", {}).get("ship", {}).get("mode", policy.get("default_mode", "normal")),
            "--summary",
            f"ship plan for {title}",
        ],
        repo_root,
    )
    if state.returncode != 0:
        raise RuntimeError(f"agent_state.py failed: {state.stderr.strip()}")

    return {
        "command": "ship",
        "repo_root": str(repo_root),
        "route": "ship",
        "mode": policy.get("route_defaults", {}).get("ship", {}).get("mode", policy.get("default_mode", "normal")),
        "title": title,
        "policy_meta": policy_meta,
        "recommended_route": patrol["recommended_route"],
        "branch_plan": branch_plan,
        "commit_plan": commit_plan,
        "suggested_checks": checks["suggested_checks"],
        "notes": patrol.get("notes", []),
        "summary": f"ship branch={branch_plan['suggested_branch']}; commit={commit_plan['message']}",
    }


def command_state(repo_root: Path) -> dict[str, Any]:
    state = run_script_json("agent_state.py", ["--repo", str(repo_root), "show"], repo_root)
    return {
        "command": "state",
        "repo_root": str(repo_root),
        "state": state["state"],
        "summary": state["state"].get("last_summary"),
    }


def command_policy_init(repo_root: Path, force: bool) -> dict[str, Any]:
    policy = load_default_policy()
    path = write_repo_policy(repo_root, policy, force=force)
    return {
        "command": "policy-init",
        "repo_root": str(repo_root),
        "policy_file": str(path),
        "summary": "initialized repo-local policy override",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("intake", help="Run unified repo intake")

    patrol_parser = subparsers.add_parser("patrol", help="Run repo patrol with an optional preset")
    patrol_parser.add_argument("--preset", choices=PATROL_PRESETS, help="Patrol preset")
    patrol_parser.add_argument("--no-state-write", action="store_true", help="Do not update state during patrol")

    kickoff_parser = subparsers.add_parser("kickoff", help="Create the next task kickoff state")
    kickoff_parser.add_argument("title", help="Task title")
    kickoff_parser.add_argument("--route", choices=ROUTES, help="Optional explicit route")
    kickoff_parser.add_argument("--mode", choices=["normal", "fast"], help="Optional explicit mode")

    ship_parser = subparsers.add_parser("ship", help="Generate ship suggestions")
    ship_parser.add_argument("--title", required=True, help="Title used for branch and commit planning")

    subparsers.add_parser("state", help="Show current state")

    policy_parser = subparsers.add_parser("policy-init", help="Initialize a repo-local policy override")
    policy_parser.add_argument("--force", action="store_true", help="Overwrite an existing repo-local policy")

    args = parser.parse_args()
    repo_root = get_repo_root(Path(args.repo))

    if args.command == "intake":
        payload = command_intake(repo_root)
    elif args.command == "patrol":
        payload = command_patrol(repo_root, args.preset, args.no_state_write)
    elif args.command == "kickoff":
        payload = command_kickoff(repo_root, args.title, args.route, args.mode)
    elif args.command == "ship":
        payload = command_ship(repo_root, args.title)
    elif args.command == "state":
        payload = command_state(repo_root)
    elif args.command == "policy-init":
        payload = command_policy_init(repo_root, args.force)
    else:
        raise RuntimeError(f"Unknown command: {args.command}")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
