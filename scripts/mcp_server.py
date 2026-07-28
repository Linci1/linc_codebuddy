#!/usr/bin/env python3
"""MCP server for linc_codebuddy dev toolkit.

Other agents discover these tools automatically via Claude Code's MCP integration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure sibling scripts are importable
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib import get_repo_root
from run_agent import (
    command_auto,
    command_ship,
    command_patrol,
    command_intake,
    command_state,
    command_kickoff,
    command_next,
    command_classify,
    command_project_init,
    command_change_create,
    command_change_show,
    command_change_update,
    command_phase_transition,
    command_gate,
    command_evidence_record,
    command_evidence_list,
    command_verify,
    command_drift,
    command_gitlab_sync,
    command_pilot_record,
    command_pilot_evaluate,
)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("linc_codebuddy")


@mcp.tool()
def lcb_auto(repo_path: str = ".", execute: bool = False, force: bool = False) -> str:
    """自动检测仓库状态并推荐下一步开发动作。

    不需要知道该调 ship 还是 continue —— 自动检测 repo 状态（git 改动、
    active tasks 等）并返回 detected_route + action。
    当 execute=True 时自动执行推荐的行动。
    """
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    result = command_auto(repo_root, execute, force)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_ship(
    repo_path: str = ".",
    title: str = "",
    task_id: str = "",
    execute: bool = False,
    force: bool = False,
) -> str:
    """端到端提交流程。

    生成或执行 ship plan：分支创建 → 验证 → stage → commit → 同步任务 → 更新状态。
    必须提供 title（commit 用途）。execute=True 时实际执行所有步骤。
    """
    if not title:
        return json.dumps({"error": "title is required for ship"}, ensure_ascii=False, indent=2)
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    result = command_ship(repo_root, title, execute, force, task_id or None)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_patrol(repo_path: str = ".", preset: str = "", no_state_write: bool = False) -> str:
    """仓库巡检。

    检查 git 状态、active tasks、建议路由和验证命令。
    preset 可选: morning / end-of-day / pre-ship / resume。
    """
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    p = preset if preset else None
    result = command_patrol(repo_root, p, no_state_write)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_intake(repo_path: str = ".") -> str:
    """仓库环境侦测。

    返回技术栈、目录结构、git 状态、任务文件位置等。
    适合作为首次接触仓库时的 intake。
    """
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    result = command_intake(repo_root)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_state(repo_path: str = ".") -> str:
    """查看 agent 当前状态。

    返回上次的 route、mode、work item、patrol 记录等。
    """
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    result = command_state(repo_root)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_next(repo_path: str = ".") -> str:
    """返回当前唯一推荐动作，以及是否可以继续修改代码。"""
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    result = command_next(repo_root)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_classify(
    repo_path: str = ".",
    description: str = "",
    requirement_uncertainty: int = 0,
    change_scope: int = 0,
    data_impact: int = 0,
    security_auth_impact: int = 0,
    production_impact: int = 0,
    rollback_difficulty: int = 0,
    requested_level: str = "",
    approve_downgrade: bool = False,
    downgrade_reason: str = "",
    persist: bool = False,
) -> str:
    """按风险将任务分为 L0-L3，并返回最小必要流程和产物。"""
    if not description:
        return json.dumps({"error": "description is required"}, ensure_ascii=False, indent=2)
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    dimensions = {
        "requirement_uncertainty": requirement_uncertainty,
        "change_scope": change_scope,
        "data_impact": data_impact,
        "security_auth_impact": security_auth_impact,
        "production_impact": production_impact,
        "rollback_difficulty": rollback_difficulty,
    }
    result = command_classify(
        repo_root,
        description,
        dimensions,
        requested_level or None,
        approve_downgrade,
        downgrade_reason or None,
        persist,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_project_init(repo_path: str = ".", name: str = "", project_id: str = "") -> str:
    """初始化仓库级项目模型；重复调用会返回已有项目。"""
    if not name:
        return json.dumps({"error": "name is required"}, ensure_ascii=False, indent=2)
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    return json.dumps(command_project_init(repo_root, name, project_id or None), ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_change(
    repo_path: str = ".", action: str = "show", change_id: str = "", title: str = "",
    level: str = "L1", problem: str = "", outcome: str = "", acceptance: list[str] | None = None,
    risks: list[str] | None = None, requirements: list[str] | None = None,
    in_scope: list[str] | None = None, out_of_scope: list[str] | None = None,
    target_phase: str = "", actor: str = "agent", reason: str = "",
    override: bool = False, approval_ref: str = "",
) -> str:
    """聚合管理 change：create/show/update/transition。"""
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    acceptance = acceptance or []
    risks = risks or []
    requirements = requirements or []
    in_scope = in_scope or []
    out_of_scope = out_of_scope or []
    if action == "create":
        result = command_change_create(repo_root, title, level, problem, outcome, acceptance, risks)
    elif action == "show":
        result = command_change_show(repo_root, change_id or None)
    elif action == "update":
        fields = {key: value for key, value in {"problem": problem or None, "outcome": outcome or None, "risks": risks or None}.items() if value is not None}
        if acceptance:
            fields["acceptance"] = [{"id": f"ACC-{index:03d}", "scenario": item} for index, item in enumerate(acceptance, 1)]
        if requirements:
            fields["requirements"] = [{"id": f"REQ-{index:03d}", "statement": item} for index, item in enumerate(requirements, 1)]
        if in_scope:
            fields["in_scope"] = in_scope
        if out_of_scope:
            fields["out_of_scope"] = out_of_scope
        result = command_change_update(repo_root, change_id, fields)
    elif action == "transition":
        result = command_phase_transition(repo_root, target_phase, actor, change_id or None, reason, override, approval_ref or None)
    else:
        result = {"error": f"unknown action: {action}"}
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_gate(repo_path: str = ".", target_phase: str = "", change_id: str = "") -> str:
    """评估 active change 或指定 change 进入目标阶段所缺少的事实。"""
    if not target_phase:
        return json.dumps({"error": "target_phase is required"}, ensure_ascii=False, indent=2)
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    return json.dumps(command_gate(repo_root, target_phase, change_id or None), ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_evidence(
    repo_path: str = ".", action: str = "list", change_id: str = "", evidence_type: str = "manual",
    status: str = "observed", summary: str = "", acceptance_ids: list[str] | None = None,
    requirement_ids: list[str] | None = None, task_ids: list[str] | None = None, command: str = "",
    exit_code: int = 0, environment: str = "local", reference: str = "", severity: str = "",
) -> str:
    """记录实际执行的证据，或列出已有证据；建议命令不能通过此工具自动变成证据。"""
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    acceptance_ids = acceptance_ids or []
    requirement_ids = requirement_ids or []
    task_ids = task_ids or []
    if action == "record":
        result = command_evidence_record(
            repo_root, change_id, evidence_type, summary, status=status,
            acceptance_ids=acceptance_ids, requirement_ids=requirement_ids, task_ids=task_ids,
            command=command or None, exit_code=exit_code, environment=environment,
            reference=reference or None, severity=severity or None,
        )
    else:
        result = command_evidence_list(repo_root, change_id)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_verify(repo_path: str = ".", change_id: str = "") -> str:
    """汇总 acceptance 证据、review finding 和 release readiness。"""
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    return json.dumps(command_verify(repo_root, change_id or None), ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_drift(repo_path: str = ".", change_id: str = "") -> str:
    """只读报告 scope 和 evidence 漂移，不自动修改或回滚代码。"""
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    return json.dumps(command_drift(repo_root, change_id or None), ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_gitlab_sync(
    repo_path: str = ".", snapshot_path: str = "", change_id: str = "", apply: bool = False,
) -> str:
    """从已获取的 GitLab JSON 快照生成同步计划；apply 只更新本地引用，不写 GitLab。"""
    if not snapshot_path:
        return json.dumps({"error": "snapshot_path is required"}, ensure_ascii=False, indent=2)
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    return json.dumps(
        command_gitlab_sync(repo_root, Path(snapshot_path).resolve(), change_id or None, apply),
        ensure_ascii=False, indent=2,
    )


@mcp.tool()
def lcb_workspace_status() -> str:
    """汇总所有已注册仓库的 branch、dirty、phase、blocking 和 next action。"""
    from workspace import list_repos, summarize_repos, update_status

    repos = summarize_repos(update_status())
    return json.dumps({"command": "workspace", "subcommand": "status", "repos": repos}, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_pilot(
    repo_path: str = ".", action: str = "evaluate", metric: str = "", value: float = 0,
    note: str = "", change_id: str = "",
) -> str:
    """记录真实项目试点指标，或基于观测判断是否值得进入 V3。"""
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    if action == "record":
        result = command_pilot_record(repo_root, metric, value, note, change_id or None)
    else:
        result = command_pilot_evaluate(repo_root, change_id or None)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def lcb_kickoff(
    repo_path: str = ".",
    title: str = "",
    route: str = "",
    mode: str = "",
    requested_level: str = "",
    approve_downgrade: bool = False,
    downgrade_reason: str = "",
) -> str:
    """创建 work item 并同步任务状态。

    title 必填。route 可选 (new/continue/review/hotfix/ship)，不指定时自动检测。
    mode 可选 (normal/fast)。
    """
    if not title:
        return json.dumps({"error": "title is required for kickoff"}, ensure_ascii=False, indent=2)
    repo_root, _ = get_repo_root(Path(repo_path).resolve())
    r = route if route else None
    m = mode if mode else None
    result = command_kickoff(
        repo_root, title, r, m, requested_level=requested_level or None,
        approve_downgrade=approve_downgrade, downgrade_reason=downgrade_reason or None,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
