#!/usr/bin/env python3
"""Stable identifiers for CodeBuddy work items and tasks."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


ID_RE = re.compile(r"\b((?:WI|TASK)-\d{8}-\d{3})\b")


def extract_id(text: str) -> str | None:
    match = ID_RE.search(text)
    return match.group(1) if match else None


def next_id(prefix: str, search_paths: list[Path], now: datetime | None = None) -> str:
    day = (now or datetime.now()).strftime("%Y%m%d")
    marker = f"{prefix}-{day}-"
    highest = 0
    for path in search_paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in re.finditer(rf"\b{re.escape(marker)}(\d{{3}})\b", content):
            highest = max(highest, int(match.group(1)))
    return f"{marker}{highest + 1:03d}"


def work_item_sources(repo_root: Path) -> list[Path]:
    sources: list[Path] = []
    for directory in [repo_root / "docs" / "worklogs", repo_root / ".codex" / "worklogs"]:
        if directory.exists():
            sources.extend(directory.glob("*.md"))
    return sources


def next_change_id(repo_root: Path, slug: str, now: datetime | None = None) -> str:
    changes_dir = repo_root / ".codex" / "linc_codebuddy" / "changes"
    day = (now or datetime.now()).strftime("%Y%m%d")
    marker = f"CHG-{day}-"
    highest = 0
    if changes_dir.exists():
        for path in changes_dir.iterdir():
            match = re.match(rf"{re.escape(marker)}(\d{{3}})(?:-|$)", path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"{marker}{highest + 1:03d}-{slug}"
