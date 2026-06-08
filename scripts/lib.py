#!/usr/bin/env python3
"""Shared utilities for linc_codebuddy scripts."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent


# ── Subprocess ──

def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


# ── Git / Repo ──

def get_repo_root(path: Path) -> tuple[Path, bool]:
    """Return (repo_root, is_git_repo)."""
    result = run(["git", "rev-parse", "--show-toplevel"], path)
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve(), True
    return path.resolve(), False


def is_agent_metadata_path(path: str) -> bool:
    return path == ".codex" or path.startswith(".codex/")


# ── File / JSON ──

def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file. Returns empty dict when missing or malformed."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def choose_task_file(root: Path) -> Path:
    if (root / "TASKS.md").exists():
        return root / "TASKS.md"
    if (root / ".codex" / "TASKS.md").exists():
        return root / ".codex" / "TASKS.md"
    return root / ".codex" / "TASKS.md"


# ── Text ──

def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug or "work-item"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ── Package Manager ──

def detect_package_manager(root: Path) -> str | None:
    if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        return "bun"
    if (root / "pnpm-workspace.yaml").exists():
        return "pnpm"
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "package-lock.json").exists():
        return "npm"
    if (root / "package.json").exists():
        return "npm"
    return None
