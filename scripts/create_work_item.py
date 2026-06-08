#!/usr/bin/env python3
"""Create a work item in repo-native worklogs or .codex/worklogs."""

from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = SKILL_ROOT / "assets" / "work-item-templates"

ROUTE_DEFAULTS: dict[str, dict[str, Any]] = {
    "new": {
        "goal": "交付一个可演示、可验证的最小闭环。",
        "scope": "待补充：本次新增能力覆盖的模块、入口和明确不做的内容。",
        "acceptance": ["主路径可运行或可验证", "关键边界条件有基本处理", "任务记录与验证结果已同步"],
        "risks": ["需求边界待确认", "依赖、配置或迁移影响待确认"],
        "plan": ["做 repo intake 并确认范围", "实现最小闭环", "运行最小可信验证", "同步任务状态与交付结论"],
        "notes": ["依赖与影响面：待补充", "是否需要后续拆分：待补充"],
    },
    "continue": {
        "goal": "在已有上下文基础上完成下一段可交付闭环。",
        "scope": "待补充：本轮接续的 work item、模块和不继续处理的部分。",
        "acceptance": ["明确承接上轮上下文", "本轮闭环完成并可验证", "剩余事项已更新到任务记录"],
        "risks": ["上轮改动的潜在回归待确认", "已有 diff 或脏工作区需谨慎兼容"],
        "plan": ["读取 diff、任务文件和 worklog", "确认本轮焦点", "完成本轮最小闭环", "补验证并同步状态"],
        "resume_context": ["上轮任务文件：待补充", "当前 branch / diff：待补充"],
        "done_so_far": ["已完成内容：待补充"],
        "this_round_focus": ["本轮目标：待补充"],
        "notes": ["需要延续的约束：待补充", "剩余 backlog：待补充"],
    },
    "review": {
        "goal": "识别明确缺陷、回归风险、测试缺口和开放问题。",
        "scope": "待补充：本次 review 的 diff、文件或模块范围。",
        "acceptance": ["按严重度输出 findings", "指出风险来源和影响范围", "补充测试缺口或验证盲区"],
        "risks": ["上下文不足导致判断偏差", "未运行验证时结论可信度有限"],
        "plan": ["读取 diff 与上下文", "锁定高风险区域", "整理 findings 与剩余风险"],
        "review_scope": ["目标 diff / 文件：待补充", "重点模块：待补充"],
        "findings_capture": ["功能正确性", "边界条件与错误处理", "测试覆盖与回归风险"],
        "validation_evidence": ["已运行验证：待补充", "未运行验证及原因：待补充"],
        "notes": ["如果无明确缺陷，也要记录剩余风险", "必要时给出建议修复方向"],
    },
    "hotfix": {
        "goal": "尽快完成最小可逆修复，并把影响面控制在必要范围内。",
        "scope": "待补充：本次热修涉及的错误场景、文件和明确不动的区域。",
        "acceptance": ["症状被最小修复", "关键回归点已做必要验证", "后续清理项已记录"],
        "risks": ["可能存在根因未彻底处理", "为速度牺牲的重构或补测需后补"],
        "plan": ["确认症状和最小边界", "实施最小修复", "运行必要验证", "记录后续清理项"],
        "symptoms": ["现象：待补充", "复现条件：待补充"],
        "fix_boundary": ["允许改动：待补充", "明确不改：待补充"],
        "rollback_followup": ["需要回滚时的切换点：待补充", "后续补测 / 重构：待补充"],
        "notes": ["默认极速模式，但仍保留任务记录", "优先最小可逆方案"],
    },
    "ship": {
        "goal": "把当前改动整理到可提交、可推送或可发版准备状态。",
        "scope": "待补充：本次要纳入交付的文件、模块和排除项。",
        "acceptance": ["变更边界清晰", "最小可信验证已完成或已说明缺口", "branch / commit 方案明确"],
        "risks": ["可能混入无关变更", "验证不足会影响交付置信度"],
        "plan": ["清点 diff 与任务状态", "补最小可信验证", "整理 branch / commit 方案", "输出交付建议"],
        "ship_scope": ["本次交付范围：待补充", "排除项：待补充"],
        "verification_before_ship": ["已完成验证：待补充", "未完成验证与原因：待补充"],
        "git_plan": ["建议 branch：待补充", "建议 commit：待补充"],
        "open_questions": ["是否需要 push / 发版：待补充", "是否还需补文档或迁移说明：待补充"],
        "notes": ["未获明确要求时，做到可提交状态即可", "提交说明优先写业务价值"],
    },
}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug or "work-item"


def get_repo_root(path: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve()
    return path.resolve()


def choose_worklog_dir(root: Path) -> Path:
    docs_dir = root / "docs" / "worklogs"
    codex_dir = root / ".codex" / "worklogs"
    if docs_dir.exists():
        return docs_dir
    if codex_dir.exists():
        return codex_dir
    return codex_dir


def unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        next_candidate = directory / f"{stem}-{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def render_bullets(items: list[str], checked: bool = False) -> str:
    prefix = "- [ ] " if checked else "- "
    return "\n".join(f"{prefix}{item}" for item in items)


def load_template(route: str) -> str:
    template_path = TEMPLATE_DIR / f"{route}.md"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return """# {{title}}

- Created: {{created_at}}
- Route: {{route}}
- Mode: {{mode}}
- Repo Root: {{repo_root}}

## Goal

{{goal}}

## Scope

{{scope}}

## Acceptance

{{acceptance}}

## Risks

{{risks}}

## Plan

{{plan_checklist}}

## Notes

{{notes}}
"""


def replace_tokens(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def build_content(
    title: str,
    route: str,
    mode: str,
    repo_root: Path,
    goal: str | None,
    acceptance: list[str],
    risks: list[str],
    plan: list[str],
    scope: str | None,
    notes: list[str],
) -> str:
    now = datetime.now().astimezone()
    defaults = ROUTE_DEFAULTS[route]
    template = load_template(route)
    values = {
        "title": title,
        "created_at": now.strftime("%Y-%m-%d %H:%M %Z"),
        "route": route,
        "mode": mode,
        "repo_root": str(repo_root),
        "goal": goal or defaults["goal"],
        "scope": scope or defaults["scope"],
        "acceptance": render_bullets(acceptance or defaults["acceptance"]),
        "risks": render_bullets(risks or defaults["risks"]),
        "plan_checklist": render_bullets(plan or defaults["plan"], checked=True),
        "notes": render_bullets(notes or defaults["notes"]),
        "resume_context": render_bullets(defaults.get("resume_context", ["待补充"])),
        "done_so_far": render_bullets(defaults.get("done_so_far", ["待补充"])),
        "this_round_focus": render_bullets(defaults.get("this_round_focus", ["待补充"])),
        "review_scope": render_bullets(defaults.get("review_scope", ["待补充"])),
        "findings_capture": render_bullets(defaults.get("findings_capture", ["待补充"])),
        "validation_evidence": render_bullets(defaults.get("validation_evidence", ["待补充"])),
        "symptoms": render_bullets(defaults.get("symptoms", ["待补充"])),
        "fix_boundary": render_bullets(defaults.get("fix_boundary", ["待补充"])),
        "rollback_followup": render_bullets(defaults.get("rollback_followup", ["待补充"])),
        "ship_scope": render_bullets(defaults.get("ship_scope", ["待补充"])),
        "verification_before_ship": render_bullets(defaults.get("verification_before_ship", ["待补充"])),
        "git_plan": render_bullets(defaults.get("git_plan", ["待补充"])),
        "open_questions": render_bullets(defaults.get("open_questions", ["待补充"])),
    }
    return replace_tokens(template, values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("title", help="Work item title")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--route", default="new", choices=["new", "continue", "review", "hotfix", "ship"])
    parser.add_argument("--mode", default="normal", choices=["normal", "fast"])
    parser.add_argument("--goal", help="Short goal statement")
    parser.add_argument("--scope", help="Short scope statement")
    parser.add_argument("--acceptance", action="append", default=[], help="Acceptance criteria")
    parser.add_argument("--risk", action="append", default=[], help="Known risks")
    parser.add_argument("--plan", action="append", default=[], help="Planned steps")
    parser.add_argument("--note", action="append", default=[], help="Additional notes")
    args = parser.parse_args()

    repo_root = get_repo_root(Path(args.repo))
    worklog_dir = choose_worklog_dir(repo_root)
    worklog_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    filename = f"{timestamp}-{slugify(args.title)}.md"
    output_path = unique_path(worklog_dir, filename)
    content = build_content(
        title=args.title,
        route=args.route,
        mode=args.mode,
        repo_root=repo_root,
        goal=args.goal,
        acceptance=args.acceptance,
        risks=args.risk,
        plan=args.plan,
        scope=args.scope,
        notes=args.note,
    )
    output_path.write_text(content, encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
