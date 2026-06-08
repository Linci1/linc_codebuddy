#!/usr/bin/env python3
"""Inspect the current repository and print a compact development intake summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lib import detect_package_manager, get_repo_root, is_agent_metadata_path, read_json, run


STACK_MARKERS = {
    "node": ["package.json"],
    "python": ["pyproject.toml", "requirements.txt", "setup.py"],
    "go": ["go.mod"],
    "rust": ["Cargo.toml"],
    "docker": ["Dockerfile", "docker-compose.yml", "compose.yaml"],
}

REPO_SHAPE_MARKERS = ["pnpm-workspace.yaml", "turbo.json", "nx.json", "lerna.json"]


def extract_status_path(line: str) -> str:
    path = line[3:]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip()


def detect_stack(root: Path) -> list[str]:
    detected: list[str] = []
    for name, markers in STACK_MARKERS.items():
        if any((root / marker).exists() for marker in markers):
            detected.append(name)
    return detected


def detect_repo_shape(root: Path) -> str:
    if any((root / marker).exists() for marker in REPO_SHAPE_MARKERS):
        return "monorepo"
    if (root / "apps").exists() and (root / "packages").exists():
        return "monorepo"
    return "single-package"


def detect_node_details(root: Path) -> dict[str, Any]:
    package_json = read_json(root / "package.json") or {}
    dependencies: dict[str, str] = {}
    for key in ["dependencies", "devDependencies", "peerDependencies"]:
        dependencies.update(package_json.get(key, {}))

    dep_names = set(dependencies)
    frameworks: list[str] = []
    for name, label in [
        ("next", "nextjs"),
        ("react", "react"),
        ("vue", "vue"),
        ("svelte", "svelte"),
        ("astro", "astro"),
        ("vite", "vite"),
        ("express", "express"),
        ("playwright", "playwright"),
    ]:
        if name in dep_names or f"@{name}" in dep_names:
            frameworks.append(label)
    if any(name.startswith("@nestjs/") for name in dep_names):
        frameworks.append("nestjs")

    if (root / "tsconfig.json").exists() or "typescript" in dep_names:
        frameworks.append("typescript")

    scripts = sorted((package_json.get("scripts") or {}).keys())
    return {
        "frameworks": frameworks,
        "scripts": scripts,
    }


def detect_python_details(root: Path) -> dict[str, Any]:
    frameworks: list[str] = []
    manager: str | None = None
    sources: list[Path] = []

    if (root / "uv.lock").exists():
        manager = "uv"
    elif (root / "poetry.lock").exists():
        manager = "poetry"
    elif (root / "requirements.txt").exists() or (root / "pyproject.toml").exists():
        manager = "pip"

    for path in [root / "pyproject.toml", root / "requirements.txt", root / "requirements-dev.txt"]:
        if path.exists():
            sources.append(path)

    content = "\n".join(path.read_text(encoding="utf-8", errors="ignore").lower() for path in sources)
    for needle, label in [
        ("fastapi", "fastapi"),
        ("django", "django"),
        ("flask", "flask"),
        ("pytest", "pytest"),
        ("pydantic", "pydantic"),
    ]:
        if needle in content:
            frameworks.append(label)

    return {
        "frameworks": frameworks,
        "manager": manager,
    }


def detect_go_details(root: Path) -> dict[str, Any]:
    go_mod = root / "go.mod"
    if not go_mod.exists():
        return {"frameworks": []}
    content = go_mod.read_text(encoding="utf-8", errors="ignore").lower()
    frameworks: list[str] = []
    for needle, label in [("gin-gonic/gin", "gin"), ("gofiber/fiber", "fiber"), ("grpc", "grpc")]:
        if needle in content:
            frameworks.append(label)
    return {"frameworks": frameworks}


def detect_rust_details(root: Path) -> dict[str, Any]:
    cargo_toml = root / "Cargo.toml"
    if not cargo_toml.exists():
        return {"frameworks": []}
    content = cargo_toml.read_text(encoding="utf-8", errors="ignore").lower()
    frameworks: list[str] = []
    for needle, label in [("axum", "axum"), ("actix-web", "actix-web"), ("tokio", "tokio")]:
        if needle in content:
            frameworks.append(label)
    return {"frameworks": frameworks}


def detect_test_markers(root: Path) -> list[str]:
    markers: list[str] = []
    for path, label in [
        (root / "tests", "tests-dir"),
        (root / "__tests__", "__tests__"),
        (root / "playwright.config.ts", "playwright"),
        (root / "pytest.ini", "pytest"),
        (root / "cypress.config.ts", "cypress"),
    ]:
        if path.exists():
            markers.append(label)
    return markers


def detect_task_file(root: Path) -> Path:
    if (root / "TASKS.md").exists():
        return root / "TASKS.md"
    if (root / ".codex" / "TASKS.md").exists():
        return root / ".codex" / "TASKS.md"
    return root / ".codex" / "TASKS.md"


def detect_worklog_dir(root: Path) -> Path:
    if (root / "docs" / "worklogs").exists():
        return root / "docs" / "worklogs"
    if (root / ".codex" / "worklogs").exists():
        return root / ".codex" / "worklogs"
    return root / ".codex" / "worklogs"


def get_git_status(root: Path, is_git_repo: bool) -> dict[str, Any]:
    if not is_git_repo:
        return {
            "branch": None,
            "is_dirty": False,
            "tracked_changes": 0,
            "untracked_files": 0,
            "status_lines": [],
        }

    branch_result = run(["git", "branch", "--show-current"], root)
    status_result = run(["git", "status", "--short", "--branch"], root)
    raw_status_lines = [line for line in status_result.stdout.splitlines() if line.strip()]
    ignored_status_lines = [
        line for line in raw_status_lines if not line.startswith("##") and is_agent_metadata_path(extract_status_path(line))
    ]
    status_lines = [
        line for line in raw_status_lines if line.startswith("##") or not is_agent_metadata_path(extract_status_path(line))
    ]
    tracked_changes = sum(1 for line in status_lines if not line.startswith("##") and not line.startswith("??"))
    untracked_files = sum(1 for line in status_lines if line.startswith("??"))

    return {
        "branch": branch_result.stdout.strip() or None,
        "is_dirty": tracked_changes > 0 or untracked_files > 0,
        "tracked_changes": tracked_changes,
        "untracked_files": untracked_files,
        "status_lines": status_lines,
        "ignored_status_lines": ignored_status_lines,
    }


def get_available_commands(root: Path) -> list[str]:
    commands: list[str] = []
    if (root / "scripts" / "dev").exists():
        commands.extend(
            [
                "scripts/dev remind",
                "scripts/dev new \"<task-title>\"",
                "scripts/dev plan <work-item-file>",
                "scripts/dev review",
                "scripts/dev checklist",
            ]
        )
    if (root / "Makefile").exists():
        commands.append("make <target>")
    if (root / "justfile").exists():
        commands.append("just <target>")
    package_json = read_json(root / "package.json") or {}
    scripts = package_json.get("scripts") or {}
    manager = detect_package_manager(root)
    for script_name in ["dev", "lint", "test", "test:unit", "build", "typecheck", "check"]:
        if script_name in scripts and manager:
            if manager == "bun":
                commands.append(f"bun run {script_name}")
            elif manager == "pnpm":
                commands.append(f"pnpm {script_name}")
            elif manager == "yarn":
                commands.append(f"yarn {script_name}")
            elif script_name == "test":
                commands.append("npm test")
            else:
                commands.append(f"npm run {script_name}")
    return commands


def detect_validation_hints(root: Path, stack: list[str], repo_shape: str) -> list[str]:
    hints: list[str] = []
    if (root / "scripts" / "dev").exists():
        hints.append("Prefer scripts/dev checklist or repo-native targets first.")
    if "node" in stack:
        hints.append("For TS or frontend changes, consider lint -> typecheck/test -> build.")
    if "python" in stack:
        hints.append("For Python changes, consider lint -> pytest -> mypy when configured.")
    if "go" in stack:
        hints.append("For Go changes, prefer go test ./... before broader checks.")
    if "rust" in stack:
        hints.append("For Rust changes, prefer cargo test and clippy when available.")
    if repo_shape == "monorepo":
        hints.append("This looks like a monorepo; prefer package-scoped checks before workspace-wide runs.")
    return hints


def build_summary(target: Path) -> dict[str, Any]:
    repo_root, is_git_repo = get_repo_root(target)
    stack = detect_stack(repo_root)
    repo_shape = detect_repo_shape(repo_root)
    return {
        "input_path": str(target.resolve()),
        "repo_root": str(repo_root),
        "is_git_repo": is_git_repo,
        "repo_shape": repo_shape,
        "stack": stack,
        "stack_details": {
            "node": detect_node_details(repo_root) if "node" in stack else None,
            "python": detect_python_details(repo_root) if "python" in stack else None,
            "go": detect_go_details(repo_root) if "go" in stack else None,
            "rust": detect_rust_details(repo_root) if "rust" in stack else None,
            "test_markers": detect_test_markers(repo_root),
        },
        "package_manager": detect_package_manager(repo_root),
        "git": get_git_status(repo_root, is_git_repo),
        "tooling": {
            "scripts_dev": (repo_root / "scripts" / "dev").exists(),
            "makefile": (repo_root / "Makefile").exists(),
            "justfile": (repo_root / "justfile").exists(),
        },
        "task_state": {
            "task_file": str(detect_task_file(repo_root)),
            "worklog_dir": str(detect_worklog_dir(repo_root)),
        },
        "available_commands": get_available_commands(repo_root),
        "validation_hints": detect_validation_hints(repo_root, stack, repo_shape),
    }


def print_human(summary: dict[str, Any]) -> None:
    stack = ", ".join(summary["stack"]) if summary["stack"] else "unknown"
    git_info = summary["git"]
    print(f"repo_root: {summary['repo_root']}")
    print(f"is_git_repo: {summary['is_git_repo']}")
    print(f"repo_shape: {summary['repo_shape']}")
    print(f"stack: {stack}")
    print(f"package_manager: {summary['package_manager'] or 'unknown'}")
    print(f"branch: {git_info['branch'] or 'n/a'}")
    print(
        "dirty: "
        f"{git_info['is_dirty']} "
        f"(tracked={git_info['tracked_changes']}, untracked={git_info['untracked_files']})"
    )
    print(f"task_file: {summary['task_state']['task_file']}")
    print(f"worklog_dir: {summary['task_state']['worklog_dir']}")
    test_markers = summary["stack_details"]["test_markers"]
    if test_markers:
        print(f"test_markers: {', '.join(test_markers)}")
    for key in ["node", "python", "go", "rust"]:
        details = summary["stack_details"].get(key)
        if not details:
            continue
        frameworks = details.get("frameworks") or []
        if frameworks:
            print(f"{key}_frameworks: {', '.join(frameworks)}")
        if key == "node" and details.get("scripts"):
            print(f"node_scripts: {', '.join(details['scripts'])}")
        if key == "python" and details.get("manager"):
            print(f"python_manager: {details['manager']}")
    if summary["available_commands"]:
        print("available_commands:")
        for command in summary["available_commands"]:
            print(f"  - {command}")
    if summary["validation_hints"]:
        print("validation_hints:")
        for hint in summary["validation_hints"]:
            print(f"  - {hint}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Directory to inspect")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    summary = build_summary(Path(args.path))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_human(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
