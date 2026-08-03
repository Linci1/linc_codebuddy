#!/usr/bin/env python3
"""Install the CodeBuddy skill link and register its Codex MCP server."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


BLOCK_PATTERN = re.compile(
    r"\n?\[mcp_servers\.linc_codebuddy\]\n"
    r"(?:[^\n]*\n)*?"
    r"(?=\n\[|\Z)",
    re.MULTILINE,
)


def install_skill_link(skill_root: Path, codex_home: Path) -> Path:
    skills_dir = codex_home / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    link = skills_dir / "linc_codebuddy"
    if link.is_symlink() and link.resolve() == skill_root:
        return link
    if link.exists() or link.is_symlink():
        raise FileExistsError(f"refusing to replace existing skill path: {link}")
    link.symlink_to(skill_root, target_is_directory=True)
    return link


def register_mcp(skill_root: Path, codex_home: Path) -> Path:
    config_path = codex_home / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    python_path = skill_root / ".venv-mcp" / "bin" / "python"
    server_path = skill_root / "scripts" / "mcp_server.py"
    block = (
        "[mcp_servers.linc_codebuddy]\n"
        f'command = "{python_path}"\n'
        f'args = ["{server_path}"]\n'
        f'cwd = "{skill_root}"\n'
        "startup_timeout_sec = 30\n"
    )
    updated = BLOCK_PATTERN.sub("\n", content).rstrip()
    updated = f"{updated}\n\n{block}" if updated else block
    config_path.write_text(updated, encoding="utf-8")
    os.chmod(config_path, 0o600)
    return config_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    args = parser.parse_args()
    skill_root = Path(args.repo).expanduser().resolve()
    codex_home = Path(args.codex_home).expanduser().resolve()
    link = install_skill_link(skill_root, codex_home)
    config = register_mcp(skill_root, codex_home)
    print(f"Codex skill: {link} -> {skill_root}")
    print(f"Codex MCP: {config} [mcp_servers.linc_codebuddy]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
