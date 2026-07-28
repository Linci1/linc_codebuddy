#!/usr/bin/env python3
"""Sync a lightweight TASKS.md file for ongoing development work."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from identity import extract_id, next_id
from lib import choose_task_file, get_repo_root


SECTION_ORDER = ["Active", "Waiting On", "Someday", "Done"]
TASK_RE = re.compile(r"^- \[(?: |x)\] ")


@dataclass
class Block:
    kind: str
    lines: list[str]


def init_task_file(task_file: Path) -> None:
    if task_file.exists():
        return
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(
        "# Tasks\n\n## Active\n\n## Waiting On\n\n## Someday\n\n## Done\n",
        encoding="utf-8",
    )


def parse_sections(text: str) -> tuple[str, dict[str, list[str]]]:
    preamble: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current is None:
            preamble.append(line)
        else:
            sections.setdefault(current, []).append(line)

    if not preamble:
        preamble = ["# Tasks"]
    for section in SECTION_ORDER:
        section_lines = sections.setdefault(section, [])
        while section_lines and not section_lines[0].strip():
            section_lines.pop(0)
        while section_lines and not section_lines[-1].strip():
            section_lines.pop()
    return "\n".join(preamble).strip() or "# Tasks", sections


def build_blocks(lines: list[str]) -> list[Block]:
    blocks: list[Block] = []
    current: Block | None = None

    for line in lines:
        if TASK_RE.match(line):
            if current is not None:
                blocks.append(current)
            current = Block(kind="task", lines=[line])
            continue

        if current is not None and (line.startswith("  ") or not line.strip()):
            current.lines.append(line)
            continue

        if current is not None:
            blocks.append(current)
            current = None

        if blocks and blocks[-1].kind == "raw":
            blocks[-1].lines.append(line)
        else:
            blocks.append(Block(kind="raw", lines=[line]))

    if current is not None:
        blocks.append(current)
    return blocks


def render_blocks(blocks: list[Block]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        lines.extend(block.lines)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def normalize_title(title: str) -> str:
    cleaned = title
    cleaned = cleaned.replace("**", "").replace("~~", "")
    cleaned = re.sub(r"^- \[(?: |x)\]\s*", "", cleaned)
    cleaned = re.sub(r"^\[TASK-\d{8}-\d{3}\]\s*", "", cleaned)
    cleaned = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", cleaned)
    if " - " in cleaned:
        cleaned = cleaned.split(" - ", 1)[0]
    return " ".join(cleaned.strip().lower().split())


def extract_title(line: str) -> str:
    match = re.match(r"^- \[(?: |x)\]\s+(.*)$", line)
    if not match:
        return ""
    content = match.group(1).strip()
    content = re.sub(r"^\[TASK-\d{8}-\d{3}\]\s*", "", content)
    content = content.replace("**", "").replace("~~", "")
    content = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", content)
    if " - " in content:
        content = content.split(" - ", 1)[0]
    return content.strip()


def find_task(sections: dict[str, list[str]], identifier: str) -> tuple[str | None, Block | None]:
    wanted_id = extract_id(identifier)
    wanted = normalize_title(identifier)
    for section_name in SECTION_ORDER:
        blocks = build_blocks(sections[section_name])
        for block in blocks:
            if block.kind != "task":
                continue
            block_id = extract_id(block.lines[0])
            if (wanted_id and block_id == wanted_id) or (not wanted_id and normalize_title(extract_title(block.lines[0])) == wanted):
                return section_name, block
    return None, None


def remove_task(sections: dict[str, list[str]], identifier: str) -> tuple[str | None, Block | None]:
    wanted_id = extract_id(identifier)
    wanted = normalize_title(identifier)
    for section_name in SECTION_ORDER:
        blocks = build_blocks(sections[section_name])
        next_blocks: list[Block] = []
        removed: Block | None = None
        for block in blocks:
            block_id = extract_id(block.lines[0]) if block.kind == "task" else None
            matches = (wanted_id and block_id == wanted_id) or (
                not wanted_id and block.kind == "task" and normalize_title(extract_title(block.lines[0])) == wanted
            )
            if matches and removed is None:
                removed = block
                continue
            next_blocks.append(block)
        if removed is not None:
            sections[section_name] = render_blocks(next_blocks)
            return section_name, removed
    return None, None


def format_open_task(task_id: str, title: str, context: str | None) -> Block:
    line = f"- [ ] [{task_id}] **{title}**"
    if context:
        line += f" - {context}"
    return Block(kind="task", lines=[line])


def format_done_task(existing: Block | None, task_id: str, title: str) -> Block:
    context = ""
    if existing is not None:
        line = existing.lines[0]
        if " - " in line:
            context = line.split(" - ", 1)[1].strip()
    done_line = f"- [x] [{task_id}] ~~{title}~~"
    if context:
        done_line += f" - {context}"
    done_line += f" ({date.today().isoformat()})"
    return Block(kind="task", lines=[done_line])


def append_task(sections: dict[str, list[str]], section_name: str, block: Block) -> None:
    blocks = build_blocks(sections[section_name])
    blocks = [item for item in blocks if not (item.kind == "raw" and not "".join(item.lines).strip())]
    if blocks:
        blocks.append(Block(kind="raw", lines=[""]))
    blocks.append(block)
    sections[section_name] = render_blocks(blocks)


def write_task_file(task_file: Path, preamble: str, sections: dict[str, list[str]]) -> None:
    lines = [preamble.strip(), ""]
    for section in SECTION_ORDER:
        lines.append(f"## {section}")
        section_lines = sections[section]
        if section_lines:
            lines.extend(section_lines)
        lines.append("")
    task_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def add_task(task_file: Path, title: str, status: str, context: str | None, task_id: str | None = None) -> str:
    init_task_file(task_file)
    preamble, sections = parse_sections(task_file.read_text(encoding="utf-8"))
    existing_section, existing = find_task(sections, task_id or title)
    resolved_id = extract_id(existing.lines[0]) if existing else None
    resolved_id = resolved_id or task_id or next_id("TASK", [task_file])
    remove_task(sections, resolved_id if existing_section else title)
    target = {
        "active": "Active",
        "waiting": "Waiting On",
        "someday": "Someday",
    }[status]
    append_task(sections, target, format_open_task(resolved_id, title, context))
    write_task_file(task_file, preamble, sections)
    return resolved_id


def done_task(task_file: Path, identifier: str) -> str:
    init_task_file(task_file)
    preamble, sections = parse_sections(task_file.read_text(encoding="utf-8"))
    _, removed = remove_task(sections, identifier)
    if removed is None:
        raise ValueError(f"task not found: {identifier}")
    task_id = extract_id(removed.lines[0])
    if task_id is None:
        task_id = next_id("TASK", [task_file])
    title = extract_title(removed.lines[0])
    append_task(sections, "Done", format_done_task(removed, task_id, title))
    write_task_file(task_file, preamble, sections)
    return task_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add or move a task into a non-done section")
    add_parser.add_argument("title", help="Task title")
    add_parser.add_argument("--status", default="active", choices=["active", "waiting", "someday"])
    add_parser.add_argument("--context", help="Optional task context")
    add_parser.add_argument("--task-id", help="Stable task ID to preserve")

    done_parser = subparsers.add_parser("done", help="Mark a task as done")
    done_parser.add_argument("title", help="Task title")

    args = parser.parse_args()
    repo_root, _ = get_repo_root(Path(args.repo))
    task_file = choose_task_file(repo_root)

    if args.command == "add":
        task_id = add_task(task_file, args.title, args.status, args.context, args.task_id)
    elif args.command == "done":
        task_id = done_task(task_file, args.title)

    print(f"{task_file}\t{task_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
