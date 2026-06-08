#!/usr/bin/env python3
"""Patrol the current repository and recommend the next route for linc_codebuddy."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from lib import choose_task_file, get_repo_root, read_json, run


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_PATH = Path.home() / ".linc_codebuddy" / "workspace.json"


def load_json_from_script(script_name: str, args: list[str], cwd: Path) -> dict[str, Any]:
    script = SCRIPT_DIR / script_name
    result = run(["python3", str(script), *args, "--json"], cwd)
    if result.returncode != 0:
        raise RuntimeError(f"{script_name} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def parse_task_sections(task_file: Path) -> dict[str, list[str]]:
    sections = {"Active": [], "Waiting On": [], "Someday": [], "Done": []}
    if not task_file.exists():
        return sections

    current: str | None = None
    for raw_line in task_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current = line[3:].strip()
            continue
        if current in sections and line.startswith("- ["):
            sections[current].append(line)
    return sections


def recent_worklogs(root: Path, limit: int = 3) -> list[str]:
    candidates = []
    for directory in [root / "docs" / "worklogs", root / ".codex" / "worklogs"]:
        if directory.exists():
            candidates.extend(sorted(directory.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True))
    return [str(path) for path in candidates[:limit]]


def recommend_route(bootstrap: dict[str, Any], sections: dict[str, list[str]]) -> tuple[str, list[str]]:
    git_info = bootstrap["git"]
    active_count = len(sections["Active"])
    dirty = bool(git_info["is_dirty"])
    tracked = int(git_info["tracked_changes"])
    untracked = int(git_info["untracked_files"])
    signals: list[str] = []

    if dirty and active_count > 0:
        signals.append("存在进行中的 Active 任务，且仓库有未提交改动。")
        return "continue", signals
    if dirty and active_count == 0:
        if tracked > 0:
            signals.append("仓库有改动但没有 Active 任务，优先进入交付整理。")
            return "ship", signals
        signals.append("仓库只有未跟踪文件，建议先 review 或判断是否纳入任务。")
        return "review", signals
    if not dirty and active_count > 0:
        signals.append("当前没有脏改动，但存在 Active 任务，适合继续推进。")
        return "continue", signals
    if sections["Waiting On"]:
        signals.append("当前主要是等待事项，没有直接实现信号。")
        return "review", signals
    signals.append("仓库干净且无 Active 任务，本轮可以保持 idle。")
    return "idle", signals


def human_summary(payload: dict[str, Any]) -> str:
    return (
        f"recommended_route={payload['recommended_route']}; "
        f"branch={payload['bootstrap']['git']['branch'] or 'n/a'}; "
        f"dirty={payload['bootstrap']['git']['is_dirty']}; "
        f"active_tasks={len(payload['tasks']['Active'])}; "
        f"checks={len(payload['suggested_checks'])}"
    )


def print_human(payload: dict[str, Any]) -> None:
    bootstrap = payload["bootstrap"]
    print(f"repo_root: {payload['repo_root']}")
    print(f"recommended_route: {payload['recommended_route']}")
    print(f"patrolled_at: {payload['patrolled_at']}")
    print(f"branch: {bootstrap['git']['branch'] or 'n/a'}")
    print(
        "dirty: "
        f"{bootstrap['git']['is_dirty']} "
        f"(tracked={bootstrap['git']['tracked_changes']}, untracked={bootstrap['git']['untracked_files']})"
    )
    print(f"active_tasks: {len(payload['tasks']['Active'])}")
    print(f"waiting_tasks: {len(payload['tasks']['Waiting On'])}")
    if payload["signals"]:
        print("signals:")
        for signal in payload["signals"]:
            print(f"  - {signal}")
    if payload["recent_worklogs"]:
        print("recent_worklogs:")
        for worklog in payload["recent_worklogs"]:
            print(f"  - {worklog}")
    if payload["suggested_checks"]:
        print("suggested_checks:")
        for item in payload["suggested_checks"]:
            print(f"  - {item['command']}  # {item['reason']}")
    print(f"summary: {payload['summary']}")


def _patrol_single(repo_root: Path, no_state_write: bool) -> dict[str, Any]:
    bootstrap = load_json_from_script("bootstrap_repo.py", [str(repo_root)], repo_root)
    checks_payload = load_json_from_script("suggest_checks.py", ["--repo", str(repo_root)], repo_root)
    task_file = choose_task_file(repo_root)
    sections = parse_task_sections(task_file)
    recommended_route, signals = recommend_route(bootstrap, sections)

    payload = {
        "repo_root": str(repo_root),
        "patrolled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "recommended_route": recommended_route,
        "signals": signals,
        "bootstrap": bootstrap,
        "task_file": str(task_file),
        "tasks": sections,
        "recent_worklogs": recent_worklogs(repo_root),
        "suggested_checks": checks_payload["suggested_checks"],
    }
    payload["summary"] = human_summary(payload)

    if not no_state_write:
        run(
            [
                "python3",
                str(SCRIPT_DIR / "agent_state.py"),
                "--repo",
                str(repo_root),
                "patrol",
                "--recommended-route",
                recommended_route,
                "--summary",
                payload["summary"],
            ],
            repo_root,
        )

    return payload


def _patrol_workspace(args: argparse.Namespace) -> int:
    workspace = read_json(WORKSPACE_PATH)
    repos = workspace.get("repos", {})
    if not repos:
        print("No repos registered. Use 'linc-codebuddy workspace add <path>' first.")
        return 1

    results: dict[str, dict[str, Any]] = {}
    for alias, info in repos.items():
        repo_path = Path(info["path"])
        if not repo_path.exists():
            results[alias] = {"error": f"path not found: {info['path']}"}
            continue
        try:
            results[alias] = _patrol_single(repo_path, args.no_state_write)
        except RuntimeError as exc:
            results[alias] = {"error": str(exc)}

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for alias, result in results.items():
            if "error" in result:
                print(f"{alias}: ERROR - {result['error']}")
            else:
                print(f"{alias}: {result['summary']}")
        print(f"\nTotal: {len(results)} repo(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument("--no-state-write", action="store_true", help="Do not update agent state")
    parser.add_argument("--workspace", action="store_true", help="Patrol all registered workspace repos")
    args = parser.parse_args()

    if args.workspace:
        return _patrol_workspace(args)

    repo_root, _ = get_repo_root(Path(args.repo))
    payload = _patrol_single(repo_root, args.no_state_write)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
