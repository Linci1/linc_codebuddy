#!/usr/bin/env python3
"""Suggest the smallest trustworthy validation commands for the current repo."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
TS_SUFFIXES = {".ts", ".tsx"}
JS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs"}
PY_SUFFIXES = {".py"}


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def is_agent_metadata_path(path: str) -> bool:
    return path == ".codex" or path.startswith(".codex/")


def get_repo_root(path: Path) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], path)
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve()
    return path.resolve()


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


def detect_package_manager(root: Path) -> str:
    if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        return "bun"
    if (root / "pnpm-workspace.yaml").exists():
        return "pnpm"
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def node_command(manager: str, script: str) -> str:
    if manager == "bun":
        return f"bun run {script}"
    if manager == "pnpm":
        return f"pnpm {script}"
    if manager == "yarn":
        return f"yarn {script}"
    if script == "test":
        return "npm test"
    return f"npm run {script}"


def make_targets(root: Path) -> set[str]:
    targets: set[str] = set()
    makefile = root / "Makefile"
    if not makefile.exists():
        return targets
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if ":" not in line or line.startswith("\t") or line.startswith("#"):
            continue
        target = line.split(":", 1)[0].strip()
        if target and " " not in target and not target.startswith("."):
            targets.add(target)
    return targets


def load_package_json(root: Path) -> dict[str, Any]:
    package_json = root / "package.json"
    if not package_json.exists():
        return {}
    try:
        return json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def is_docs_only(files: list[str]) -> bool:
    return bool(files) and all(Path(path).suffix.lower() in DOC_SUFFIXES for path in files)


def has_ts_changes(files: list[str]) -> bool:
    return any(Path(path).suffix.lower() in TS_SUFFIXES for path in files)


def has_python_changes(files: list[str]) -> bool:
    return any(Path(path).suffix.lower() in PY_SUFFIXES for path in files)


def needs_build(files: list[str]) -> bool:
    build_sensitive_prefixes = (
        "src/",
        "app/",
        "pages/",
        "config/",
        "packages/",
        "apps/",
    )
    build_sensitive_names = {"package.json", "tsconfig.json", "vite.config.ts", "next.config.js", "turbo.json"}
    for path in files:
        if path in build_sensitive_names:
            return True
        if path.startswith(build_sensitive_prefixes) and Path(path).suffix.lower() in TS_SUFFIXES | JS_SUFFIXES | {".json"}:
            return True
    return False


def python_commands(root: Path, changed_files: list[str]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    pyproject = root / "pyproject.toml"
    pyproject_text = pyproject.read_text(encoding="utf-8", errors="ignore").lower() if pyproject.exists() else ""

    if (root / "uv.lock").exists():
        lint_cmd = "uv run ruff check ."
        test_cmd = "uv run pytest -q"
        type_cmd = "uv run mypy ."
    elif (root / "poetry.lock").exists():
        lint_cmd = "poetry run ruff check ."
        test_cmd = "poetry run pytest -q"
        type_cmd = "poetry run mypy ."
    else:
        lint_cmd = "ruff check ."
        test_cmd = "pytest -q"
        type_cmd = "mypy ."

    if (root / "ruff.toml").exists() or (root / "pyproject.toml").exists():
        suggestions.append({"command": lint_cmd, "reason": "Python lint configuration detected."})
    if has_python_changes(changed_files) or (root / "tests").exists() or (root / "pytest.ini").exists():
        suggestions.append({"command": test_cmd, "reason": "Python tests are likely relevant."})
    if (root / "mypy.ini").exists() or (root / ".mypy.ini").exists() or "mypy" in pyproject_text:
        suggestions.append({"command": type_cmd, "reason": "Mypy configuration detected."})
    return suggestions


def node_commands(root: Path, changed_files: list[str]) -> list[dict[str, Any]]:
    manager = detect_package_manager(root)
    package = load_package_json(root)
    scripts = package.get("scripts") or {}
    suggestions: list[dict[str, Any]] = []

    if is_docs_only(changed_files) and "lint" in scripts:
        return [{"command": node_command(manager, "lint"), "reason": "Docs-only change; lint is the lightest repo-native check."}]

    ordered_candidates = ["check", "lint"]
    if has_ts_changes(changed_files):
        ordered_candidates.append("typecheck")
    if "test:unit" in scripts:
        ordered_candidates.append("test:unit")
    ordered_candidates.append("test")
    if needs_build(changed_files):
        ordered_candidates.append("build")

    seen: set[str] = set()
    for script in ordered_candidates:
        if script in scripts and script not in seen:
            seen.add(script)
            suggestions.append(
                {
                    "command": node_command(manager, script),
                    "reason": f"package.json defines a {script} script.",
                }
            )
    return suggestions


def suggest_commands(root: Path, changed_files: list[str]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []

    if (root / "scripts" / "dev").exists():
        suggestions.append(
            {
                "command": "scripts/dev checklist",
                "reason": "Repo provides a first-party validation entrypoint.",
            }
        )
        return suggestions

    targets = make_targets(root)
    if "lint" in targets:
        suggestions.append({"command": "make lint", "reason": "Makefile exposes lint."})
    if "test" in targets:
        suggestions.append({"command": "make test", "reason": "Makefile exposes test."})
    if "build" in targets:
        suggestions.append({"command": "make build", "reason": "Makefile exposes build."})
    if suggestions:
        return suggestions

    if (root / "package.json").exists():
        return node_commands(root, changed_files)

    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        return python_commands(root, changed_files)

    if (root / "go.mod").exists():
        suggestions.append({"command": "go test ./...", "reason": "Go module detected."})
        return suggestions

    if (root / "Cargo.toml").exists():
        suggestions.append({"command": "cargo test", "reason": "Rust crate detected."})
        return suggestions

    if (root / "Dockerfile").exists() or (root / "docker-compose.yml").exists() or (root / "compose.yaml").exists():
        suggestions.append({"command": "docker compose config", "reason": "Docker configuration detected."})
        return suggestions

    return suggestions


def print_human(changed_files: list[str], suggestions: list[dict[str, Any]]) -> None:
    if changed_files:
        print("changed_files:")
        for path in changed_files:
            print(f"  - {path}")
    else:
        print("changed_files: []")

    if not suggestions:
        print("suggested_checks: []")
        return

    print("suggested_checks:")
    for item in suggestions:
        print(f"  - {item['command']}  # {item['reason']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of plain text")
    args = parser.parse_args()

    repo_root = get_repo_root(Path(args.repo))
    changed_files = get_changed_files(repo_root)
    suggestions = suggest_commands(repo_root, changed_files)
    payload = {
        "repo_root": str(repo_root),
        "changed_files": changed_files,
        "suggested_checks": suggestions,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(changed_files, suggestions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
