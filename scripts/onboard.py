#!/usr/bin/env python3
"""Interactive onboarding for linc_codebuddy — collect user preferences."""

from __future__ import annotations

import json
import os
from pathlib import Path

PROFILE_PATH = Path.home() / ".linc_codebuddy" / "profile.json"

QUESTIONS = [
    {
        "key": "name",
        "prompt": "你的名字/昵称",
        "default": os.environ.get("USER", ""),
    },
    {
        "key": "language",
        "prompt": "默认语言 (zh-CN / en)",
        "default": "zh-CN",
    },
    {
        "key": "branch_prefix",
        "prompt": "默认分支前缀",
        "default": "codex",
    },
    {
        "key": "default_mode",
        "prompt": "默认模式 (normal / fast)",
        "default": "normal",
    },
    {
        "key": "workspace_dir",
        "prompt": "默认工作区目录 (存放多个仓库的父目录)",
        "default": str(Path.home() / "projects"),
    },
    {
        "key": "editor",
        "prompt": "默认编辑器 (code / vim / nano)",
        "default": os.environ.get("EDITOR", "code"),
    },
]


def ask(question: dict[str, str]) -> str:
    prompt = question["prompt"]
    default = question["default"]
    if default:
        answer = input(f"{prompt} [{default}]: ").strip()
        return answer or default
    answer = ""
    while not answer:
        answer = input(f"{prompt}: ").strip()
    return answer


def main() -> int:
    print("linc_codebuddy - 首次配置")
    print("=" * 40)
    print()

    profile: dict[str, str] = {}
    for q in QUESTIONS:
        profile[q["key"]] = ask(q)

    profile_path = PROFILE_PATH
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"配置已保存到: {profile_path}")
    print()
    print("接下来你可以:")
    print("  linc-codebuddy intake           # 侦测当前仓库")
    print("  linc-codebuddy patrol --preset morning  # 晨检")
    print("  linc-codebuddy kickoff \"任务标题\"  # 启动新任务")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
