#!/usr/bin/env python3
"""Load and merge the default and repo-local linc_codebuddy policy files."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_POLICY_PATH = SKILL_ROOT / "assets" / "default-policy.json"
REPO_POLICY_RELATIVE = Path(".codex/linc_codebuddy/policy.json")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def repo_policy_path(repo_root: Path) -> Path:
    return repo_root / REPO_POLICY_RELATIVE


def load_default_policy() -> dict[str, Any]:
    return read_json(DEFAULT_POLICY_PATH)


def load_effective_policy(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    default_policy = load_default_policy()
    override_path = repo_policy_path(repo_root)
    override_policy: dict[str, Any] = {}
    if override_path.exists():
        override_policy = read_json(override_path)
    effective = deep_merge(default_policy, override_policy)
    meta = {
        "default_policy_path": str(DEFAULT_POLICY_PATH),
        "repo_policy_path": str(override_path),
        "has_repo_override": override_path.exists(),
    }
    return effective, meta


def write_repo_policy(repo_root: Path, policy: dict[str, Any], force: bool = False) -> Path:
    path = repo_policy_path(repo_root)
    if path.exists() and not force:
        raise FileExistsError(f"Policy already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
