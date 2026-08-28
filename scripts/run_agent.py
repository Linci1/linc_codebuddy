#!/usr/bin/env python3
"""Unified entrypoint for linc_codebuddy intake, patrol, kickoff, and ship flows."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from identity import extract_id
from governance import DIMENSIONS, classify, resolve_level_change
from lifecycle import (
    create_change, evaluate_gate, find_change, init_project, load_active_change,
    transition_change, update_change,
)
from quality import detect_drift, list_evidence, record_evidence, verification_summary, write_verification_report
from gitlab_sync import apply_sync, load_snapshot, plan_sync
from pilot import evaluate_pilot, record_observation
from lib import get_repo_root, is_agent_metadata_path, run
from policy_loader import load_default_policy, load_effective_policy, write_repo_policy


SCRIPT_DIR = Path(__file__).resolve().parent
ROUTES = ["new", "continue", "review", "hotfix", "ship"]
PATROL_PRESETS = ["morning", "end-of-day", "pre-ship", "resume"]


def run_script_json(script_name: str, args: list[str], repo_root: Path) -> dict[str, Any]:
    result = run(["python3", str(SCRIPT_DIR / script_name), *args, "--json"], repo_root)
    if result.returncode != 0:
        raise RuntimeError(f"{script_name} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def maybe_preset_route(base_route: str, preset: str | None, tasks: dict[str, list[str]]) -> tuple[str, str | None]:
    if preset is None:
        return base_route, None

    active_count = len(tasks.get("Active", []))
    if preset == "pre-ship" and base_route in {"continue", "review", "idle"}:
        return "ship", "pre-ship preset biases the patrol toward ship readiness."
    if preset == "end-of-day" and base_route == "continue":
        return "ship", "end-of-day preset biases the patrol toward deciding whether to ship or park."
    if preset == "resume" and active_count > 0:
        return "continue", "resume preset prioritizes continuing active work."
    if preset == "morning" and base_route == "idle" and active_count > 0:
        return "continue", "morning preset nudges active tasks back into focus."
    return base_route, None


def print_human(payload: dict[str, Any]) -> None:
    print(f"command: {payload['command']}")
    if "repo_root" in payload and payload["repo_root"]:
        print(f"repo_root: {payload['repo_root']}")
    if "route" in payload:
        print(f"route: {payload['route']}")
    if "detected_route" in payload:
        print(f"detected_route: {payload['detected_route']}")
    if "action" in payload:
        action = payload["action"]
        print(f"action: {action.get('type')} - {action.get('label')}")
        if action.get("executable"):
            print(f"  executable: yes")
    if "mode" in payload:
        print(f"mode: {payload['mode']}")
    if "summary" in payload and payload["summary"]:
        print(f"summary: {payload['summary']}")
    if "recommended_route" in payload:
        print(f"recommended_route: {payload['recommended_route']}")
    if "reasoning" in payload and payload["reasoning"]:
        print(f"reasoning: {'; '.join(payload['reasoning'])}")
    if "work_item" in payload and payload["work_item"]:
        print(f"work_item: {payload['work_item']}")
    if "task_file" in payload and payload["task_file"]:
        print(f"task_file: {payload['task_file']}")
    if "branch_plan" in payload:
        print(f"branch_plan: {payload['branch_plan']['suggested_branch']}")
    if "commit_plan" in payload:
        print(f"commit_plan: {payload['commit_plan']['message']}")
    if "execution" in payload:
        ex = payload["execution"]
        print(f"execution: {'completed' if ex.get('completed') else 'failed'}")
        if "steps" in ex:
            for step_name, step in ex["steps"].items():
                if isinstance(step, dict):
                    status = "ok" if step.get("ok", False) else "FAIL"
                    print(f"  {step_name}: {status}")
    if payload.get("notes"):
        print("notes:")
        for item in payload["notes"]:
            print(f"  - {item}")


def command_intake(repo_root: Path) -> dict[str, Any]:
    policy, policy_meta = load_effective_policy(repo_root)
    bootstrap = run_script_json("bootstrap_repo.py", [str(repo_root)], repo_root)
    state = run_script_json("agent_state.py", ["--repo", str(repo_root), "show"], repo_root)

    # Check doc config and surface prompt if missing
    from doc_sync import check_doc_config
    doc_config_status = check_doc_config(repo_root)

    return {
        "command": "intake",
        "repo_root": str(repo_root),
        "bootstrap": bootstrap,
        "state": state["state"],
        "policy": policy,
        "policy_meta": policy_meta,
        "doc_config": doc_config_status,
        "summary": (
            f"repo_shape={bootstrap['repo_shape']}; "
            f"stack={','.join(bootstrap['stack']) or 'unknown'}; "
            f"branch={bootstrap['git']['branch'] or 'n/a'}"
        ),
    }


def command_patrol(repo_root: Path, preset: str | None, no_state_write: bool) -> dict[str, Any]:
    policy, policy_meta = load_effective_policy(repo_root)
    args = ["--repo", str(repo_root)]
    if no_state_write or not policy.get("write_patrol_to_state", True):
        args.append("--no-state-write")
    patrol = run_script_json("patrol_repo.py", args, repo_root)
    state = run_script_json("agent_state.py", ["--repo", str(repo_root), "show"], repo_root)
    recommended_route, preset_reason = maybe_preset_route(patrol["recommended_route"], preset, patrol["tasks"])
    notes = []
    if preset_reason:
        notes.append(preset_reason)
    if preset is not None:
        focus = policy.get("patrol_presets", {}).get(preset, {}).get("focus", [])
        notes.extend(focus)
    return {
        "command": "patrol",
        "repo_root": str(repo_root),
        "preset": preset,
        "recommended_route": recommended_route,
        "base_recommended_route": patrol["recommended_route"],
        "policy_meta": policy_meta,
        "policy": policy,
        "patrol": patrol,
        "state": state["state"],
        "notes": notes,
        "summary": patrol["summary"],
    }


def command_classify(
    repo_root: Path,
    description: str,
    dimensions: dict[str, int] | None = None,
    requested_level: str | None = None,
    approve_downgrade: bool = False,
    downgrade_reason: str | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    policy, policy_meta = load_effective_policy(repo_root)
    result = classify(description, dimensions, policy)
    state = run_script_json("agent_state.py", ["--repo", str(repo_root), "show"], repo_root)["state"]
    active_state = state.get("active", {})
    task_id = active_state.get("task_id")
    task_file = repo_root / ".codex" / "TASKS.md"
    task_is_active = False
    if task_id and task_file.exists():
        task_is_active = any(
            line.startswith("- [ ]") and extract_id(line) == task_id
            for line in task_file.read_text(encoding="utf-8").splitlines()
        )
    current_level = active_state.get("level") if persist and task_is_active else None
    change = resolve_level_change(
        current_level,
        result,
        requested_level=requested_level,
        approve_downgrade=approve_downgrade,
        downgrade_reason=downgrade_reason,
    )
    result["level_change"] = change
    result["level"] = change["level"]
    result["policy_meta"] = policy_meta

    if persist:
        record = {
            "description": description,
            "level": result["level"],
            "classified_level": change["classified_level"],
            "previous_level": change["previous_level"],
            "upgraded": change["upgraded"],
            "downgraded": change["downgraded"],
            "downgrade_reason": change["downgrade_reason"],
            "reasons": result["reasons"],
        }
        saved = run(
            [
                "python3", str(SCRIPT_DIR / "agent_state.py"), "--repo", str(repo_root), "set",
                "--level", result["level"], "--classification", json.dumps(record, ensure_ascii=False),
            ],
            repo_root,
        )
        if saved.returncode != 0:
            raise RuntimeError(f"agent_state.py failed: {saved.stderr.strip()}")

    return {
        "command": "classify",
        "repo_root": str(repo_root),
        "description": description,
        **result,
        "summary": f"{result['level']}: {' -> '.join(result['flow'])}",
    }


def command_kickoff(
    repo_root: Path,
    title: str,
    route: str | None,
    mode: str | None,
    dimensions: dict[str, int] | None = None,
    requested_level: str | None = None,
    approve_downgrade: bool = False,
    downgrade_reason: str | None = None,
) -> dict[str, Any]:
    policy, policy_meta = load_effective_policy(repo_root)
    patrol = run_script_json("patrol_repo.py", ["--repo", str(repo_root), "--no-state-write"], repo_root)
    resolved_route = route or patrol["recommended_route"]
    if resolved_route == "idle":
        resolved_route = "new"

    route_defaults = policy.get("route_defaults", {}).get(resolved_route, {})
    resolved_mode = mode or route_defaults.get("mode") or policy.get("default_mode", "normal")
    classification = command_classify(
        repo_root,
        title,
        dimensions,
        requested_level,
        approve_downgrade,
        downgrade_reason,
        persist=True,
    )
    create_work_item = classification["create_work_item"]
    if create_work_item is None:
        create_work_item = route_defaults.get("create_work_item")
    if create_work_item is None:
        create_work_item = resolved_route in policy.get("work_item", {}).get("create_on_routes", [])

    work_item_path = None
    if create_work_item:
        created = run(
            [
                "python3",
                str(SCRIPT_DIR / "create_work_item.py"),
                title,
                "--repo",
                str(repo_root),
                "--route",
                resolved_route,
                "--mode",
                resolved_mode,
            ],
            repo_root,
        )
        if created.returncode != 0:
            raise RuntimeError(f"create_work_item.py failed: {created.stderr.strip()}")
        work_item_path = created.stdout.strip()

    work_item_id = extract_id(work_item_path or "")

    task_status = policy.get("work_item", {}).get("task_status_on_kickoff", "active")
    add_task = run(
        [
            "python3",
            str(SCRIPT_DIR / "sync_tasks.py"),
            "--repo",
            str(repo_root),
            "add",
            title,
            "--status",
            task_status,
            "--context",
            f"route={resolved_route}, mode={resolved_mode}",
        ],
        repo_root,
    )
    if add_task.returncode != 0:
        raise RuntimeError(f"sync_tasks.py failed: {add_task.stderr.strip()}")
    task_output = add_task.stdout.strip().split("\t")
    task_file = task_output[0]
    task_id = task_output[1] if len(task_output) > 1 else None

    state = run(
        [
            "python3",
            str(SCRIPT_DIR / "agent_state.py"),
            "--repo",
            str(repo_root),
            "set",
            "--route",
            resolved_route,
            "--mode",
            resolved_mode,
            "--summary",
            f"kickoff {title}",
            "--work-item",
            work_item_path or title,
            *(["--work-item-id", work_item_id] if work_item_id else []),
            *(["--task-id", task_id] if task_id else []),
            "--next-action",
            f"continue {task_id or title}",
            "--level",
            classification["level"],
        ],
        repo_root,
    )
    if state.returncode != 0:
        raise RuntimeError(f"agent_state.py failed: {state.stderr.strip()}")

    return {
        "command": "kickoff",
        "repo_root": str(repo_root),
        "route": resolved_route,
        "mode": resolved_mode,
        "title": title,
        "work_item": work_item_path,
        "work_item_id": work_item_id,
        "task_id": task_id,
        "task_file": task_file,
        "level": classification["level"],
        "classification": classification,
        "flow": classification["flow"],
        "required_artifacts": classification["required_artifacts"],
        "policy_meta": policy_meta,
        "summary": f"kickoff route={resolved_route}; mode={resolved_mode}; work_item={'yes' if work_item_path else 'no'}",
    }


def _execute_ship(repo_root: Path, plan: dict[str, Any], force: bool = False) -> dict[str, Any]:
    """Execute the ship plan: branch, validate, stage, commit, sync tasks, update state."""
    steps: dict[str, Any] = {}
    completed = True

    branch_name = plan["branch_plan"]["suggested_branch"]
    commit_msg = plan["commit_plan"]["message"]
    task_id = plan.get("task_id")
    if not task_id:
        return {
            "steps": {"error": "task_id is required for executable ship"},
            "completed": False,
        }

    # Step 1: Create/switch branch
    branch_result = run(
        ["python3", str(SCRIPT_DIR / "prepare_branch.py"), "--repo", str(repo_root),
         "--route", "ship", "--prefix", plan.get("policy_meta", {}).get("branch_prefix", "codex"),
         "--create", branch_name],
        repo_root,
    )
    steps["branch"] = {
        "branch": branch_name,
        "ok": branch_result.returncode == 0,
        "output": (branch_result.stdout + branch_result.stderr).strip()[-500:],
    }
    if not steps["branch"]["ok"]:
        steps["error"] = "branch creation failed, aborting ship"
        return {"steps": steps, "completed": False}

    # Step 2: Run validation checks
    checks_results = []
    checks_passed = True
    for check in plan.get("suggested_checks", []):
        cmd = check.get("command", "")
        if not cmd:
            continue
        result = run(["bash", "-c", cmd], repo_root)
        ok = result.returncode == 0
        checks_results.append({
            "command": cmd,
            "reason": check.get("reason", ""),
            "ok": ok,
            "exit_code": result.returncode,
            "stdout": result.stdout.strip()[-500:],
            "stderr": result.stderr.strip()[-500:],
        })
        if not ok:
            checks_passed = False
            if not force:
                break
    steps["validation"] = {"checks": checks_results, "all_passed": checks_passed}
    if not checks_passed and not force:
        steps["error"] = "validation failed (use --force to skip)"
        return {"steps": steps, "completed": False}

    # Step 3: Stage files (exclude .codex/)
    status_result = run(["git", "status", "--porcelain"], repo_root)
    staged_files = []
    for line in status_result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        filepath = parts[1]
        if is_agent_metadata_path(filepath):
            continue
        add_result = run(["git", "add", filepath], repo_root)
        if add_result.returncode == 0:
            staged_files.append(filepath)
    steps["stage"] = {"files": staged_files, "count": len(staged_files)}

    if not staged_files:
        steps["error"] = "no files to commit after filtering .codex/"
        return {"steps": steps, "completed": False}

    # Step 4: Commit
    commit_result = run(["git", "commit", "-m", commit_msg], repo_root)
    steps["commit"] = {
        "message": commit_msg,
        "ok": commit_result.returncode == 0,
        "output": (commit_result.stdout + commit_result.stderr).strip()[-500:],
    }
    if not steps["commit"]["ok"]:
        steps["error"] = "commit failed"
        completed = False
        return {"steps": steps, "completed": False}

    # Step 5: Sync exactly the task associated with this ship.
    sync_result = run(
        ["python3", str(SCRIPT_DIR / "sync_tasks.py"), "--repo", str(repo_root), "done", task_id],
        repo_root,
    )
    steps["sync_tasks"] = {
        "task_id": task_id,
        "ok": sync_result.returncode == 0,
        "output": (sync_result.stdout + sync_result.stderr).strip()[-500:],
    }
    if sync_result.returncode != 0:
        steps["error"] = f"commit created but task sync failed for {task_id}"
        return {"steps": steps, "completed": False}

    # Step 6: Update agent state
    state_result = run(
        ["python3", str(SCRIPT_DIR / "agent_state.py"), "--repo", str(repo_root),
         "set", "--route", "ship", "--mode",
         plan.get("mode", "normal"), "--summary", f"shipped: {commit_msg}",
         "--task-id", task_id, "--next-action", "review remaining work"],
        repo_root,
    )
    steps["state"] = {"ok": state_result.returncode == 0}

    return {"steps": steps, "completed": completed}


def command_ship(
    repo_root: Path,
    title: str,
    execute: bool = False,
    force: bool = False,
    task_id: str | None = None,
) -> dict[str, Any]:
    policy, policy_meta = load_effective_policy(repo_root)
    patrol = command_patrol(repo_root, preset="pre-ship", no_state_write=True)
    branch_prefix = policy.get("branch_prefix", "codex")
    branch_plan = run_script_json(
        "prepare_branch.py",
        ["--repo", str(repo_root), "--route", "ship", "--prefix", branch_prefix, title],
        repo_root,
    )
    commit_plan = run_script_json(
        "draft_commit.py",
        ["--repo", str(repo_root), "--route", "ship", "--title", title],
        repo_root,
    )
    checks = run_script_json("suggest_checks.py", ["--repo", str(repo_root)], repo_root)
    ship_mode = policy.get("route_defaults", {}).get("ship", {}).get("mode", policy.get("default_mode", "normal"))
    state = run(
        [
            "python3",
            str(SCRIPT_DIR / "agent_state.py"),
            "--repo",
            str(repo_root),
            "set",
            "--route",
            "ship",
            "--mode",
            ship_mode,
            "--summary",
            f"ship plan for {title}",
        ],
        repo_root,
    )
    if state.returncode != 0:
        raise RuntimeError(f"agent_state.py failed: {state.stderr.strip()}")

    result: dict[str, Any] = {
        "command": "ship",
        "repo_root": str(repo_root),
        "route": "ship",
        "mode": ship_mode,
        "title": title,
        "task_id": task_id,
        "policy_meta": policy_meta,
        "recommended_route": patrol["recommended_route"],
        "branch_plan": branch_plan,
        "commit_plan": commit_plan,
        "suggested_checks": checks["suggested_checks"],
        "notes": patrol.get("notes", []),
        "summary": f"ship branch={branch_plan['suggested_branch']}; commit={commit_plan['message']}",
    }

    if execute:
        result["execution"] = _execute_ship(repo_root, result, force)

    return result


def command_auto(repo_root: Path, execute: bool = False, force: bool = False) -> dict[str, Any]:
    """Auto-detect repo state and recommend/execute the appropriate action."""
    patrol = command_patrol(repo_root, preset=None, no_state_write=True)
    route = patrol["recommended_route"]
    patrol_tasks = patrol.get("patrol", {}).get("tasks", {})
    state = patrol.get("state", {})

    # Determine action
    if route == "ship":
        # Extract title from first active task or use fallback
        active_tasks = patrol_tasks.get("Active", [])
        title = "ship current changes"
        if active_tasks:
            title_match = re.search(r"\*\*(.+?)\*\*", active_tasks[0])
            if title_match:
                title = title_match.group(1)

        task_id = extract_id(active_tasks[0]) if len(active_tasks) == 1 else None
        ship_plan = command_ship(repo_root, title, execute=False, task_id=task_id)
        action: dict[str, Any] = {
            "type": "ship",
            "label": "Ship current changes",
            "ready": True,
            "executable": True,
            "plan": ship_plan,
            "task_id": task_id,
        }

        if execute:
            action["execution"] = _execute_ship(repo_root, ship_plan, force)
            if action["execution"]["completed"]:
                action["label"] = "Shipped successfully"
    elif route == "continue":
        action = {
            "type": "continue",
            "label": "Continue active work",
            "ready": True,
            "executable": False,
            "active_tasks": patrol_tasks.get("Active", []),
            "last_work_item": state.get("last_work_item"),
            "last_summary": state.get("last_summary"),
        }
    elif route == "review":
        action = {
            "type": "review",
            "label": "Review current state",
            "ready": True,
            "executable": False,
            "active_tasks": patrol_tasks.get("Active", []),
            "waiting_on": patrol_tasks.get("Waiting On", []),
            "suggested_checks": patrol.get("patrol", {}).get("suggested_checks", []),
        }
    else:
        action = {
            "type": route,
            "label": f"Route: {route}",
            "ready": route != "idle",
            "executable": False,
            "bootstrap": patrol.get("patrol", {}),
        }

    return {
        "command": "auto",
        "repo_root": str(repo_root),
        "detected_route": route,
        "reasoning": patrol.get("notes", [f"patrol recommends: {route}"]),
        "action": action,
        "state": state,
        "level": state.get("active", {}).get("level"),
        "summary": f"auto → {route}: {action['label']}",
    }


def command_state(repo_root: Path) -> dict[str, Any]:
    state = run_script_json("agent_state.py", ["--repo", str(repo_root), "show"], repo_root)
    return {
        "command": "state",
        "repo_root": str(repo_root),
        "state": state["state"],
        "summary": state["state"].get("last_summary"),
    }


def command_project_init(repo_root: Path, name: str, project_id: str | None = None) -> dict[str, Any]:
    project = init_project(repo_root, name, project_id)
    return {"command": "project-init", "repo_root": str(repo_root), "project": project, "summary": project["id"]}


def command_change_create(
    repo_root: Path, title: str, level: str, problem: str = "", outcome: str = "",
    acceptance: list[str] | None = None, risks: list[str] | None = None,
) -> dict[str, Any]:
    change = create_change(repo_root, title, level, problem=problem, outcome=outcome, acceptance=acceptance, risks=risks)
    _, path = find_change(repo_root, change["id"])
    return {"command": "change", "action": "create", "repo_root": str(repo_root), "change": change, "change_file": str(path), "summary": change["id"]}


def command_change_show(repo_root: Path, change_id: str | None = None) -> dict[str, Any]:
    change, path = find_change(repo_root, change_id) if change_id else load_active_change(repo_root)
    return {"command": "change", "action": "show", "repo_root": str(repo_root), "change": change, "change_file": str(path), "summary": f"{change['id']} {change['phase']}"}


def command_change_update(repo_root: Path, change_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    change = update_change(repo_root, change_id, **fields)
    _, path = find_change(repo_root, change_id)
    return {"command": "change", "action": "update", "repo_root": str(repo_root), "change": change, "change_file": str(path), "summary": change_id}


def command_gate(repo_root: Path, target_phase: str, change_id: str | None = None) -> dict[str, Any]:
    change, _ = find_change(repo_root, change_id) if change_id else load_active_change(repo_root)
    gate = evaluate_gate(repo_root, change, target_phase)
    return {"command": "gate", "repo_root": str(repo_root), "change_id": change["id"], "phase": change["phase"], "gate": gate, **gate, "summary": gate["next_action"]}


def command_phase_transition(
    repo_root: Path, target_phase: str, actor: str, change_id: str | None = None,
    reason: str = "", override: bool = False, approval_ref: str | None = None,
) -> dict[str, Any]:
    if not change_id:
        change_id = load_active_change(repo_root)[0]["id"]
    result = transition_change(repo_root, change_id, target_phase, actor=actor, reason=reason, override=override, approval_ref=approval_ref)
    return {"command": "change", "action": "transition", "repo_root": str(repo_root), **result, "summary": result["gate"]["next_action"]}


def command_evidence_record(repo_root: Path, change_id: str, evidence_type: str, summary: str, **fields: Any) -> dict[str, Any]:
    evidence = record_evidence(repo_root, change_id, evidence_type, summary, **fields)
    return {"command": "evidence", "action": "record", "repo_root": str(repo_root), "evidence": evidence, "summary": evidence["id"]}


def command_evidence_list(repo_root: Path, change_id: str) -> dict[str, Any]:
    records = list_evidence(repo_root, change_id)
    return {"command": "evidence", "action": "list", "repo_root": str(repo_root), "change_id": change_id, "evidence": records, "summary": f"{len(records)} evidence record(s)"}


def command_verify(repo_root: Path, change_id: str | None = None) -> dict[str, Any]:
    if not change_id:
        change_id = load_active_change(repo_root)[0]["id"]
    result, report_path = write_verification_report(repo_root, change_id)
    return {"command": "verify", "repo_root": str(repo_root), **result, "verification_file": str(report_path), "summary": result["next_action"]}


def command_drift(repo_root: Path, change_id: str | None = None) -> dict[str, Any]:
    if not change_id:
        change_id = load_active_change(repo_root)[0]["id"]
    result = detect_drift(repo_root, change_id)
    return {"command": "drift", "repo_root": str(repo_root), **result, "summary": result["next_action"]}


def command_gitlab_sync(repo_root: Path, snapshot_path: Path, change_id: str | None = None, apply: bool = False) -> dict[str, Any]:
    if not change_id:
        change_id = load_active_change(repo_root)[0]["id"]
    plan = plan_sync(repo_root, change_id, load_snapshot(snapshot_path))
    result = apply_sync(repo_root, plan) if apply and plan["status"] in {"planned", "noop"} else plan
    return {
        "command": "gitlab", "action": "sync", "repo_root": str(repo_root),
        "snapshot_file": str(snapshot_path), **result,
        "summary": f"gitlab sync {result['status']}",
    }


def command_pilot_record(repo_root: Path, metric: str, value: float, note: str, change_id: str | None = None) -> dict[str, Any]:
    if not change_id:
        change_id = load_active_change(repo_root)[0]["id"]
    observation = record_observation(repo_root, change_id, metric, value, note)
    return {"command": "pilot", "action": "record", "repo_root": str(repo_root), "change_id": change_id, "observation": observation, "summary": metric}


def command_pilot_evaluate(repo_root: Path, change_id: str | None = None) -> dict[str, Any]:
    if not change_id:
        change_id = load_active_change(repo_root)[0]["id"]
    result = evaluate_pilot(repo_root, change_id)
    return {"command": "pilot", "action": "evaluate", "repo_root": str(repo_root), **result, "summary": result["next_action"]}


def command_next(repo_root: Path) -> dict[str, Any]:
    patrol = command_patrol(repo_root, preset=None, no_state_write=True)
    state = patrol.get("state", {})
    active_state = state.get("active", {})
    blocking = state.get("blocking", [])
    active_tasks = patrol.get("patrol", {}).get("tasks", {}).get("Active", [])
    waiting_tasks = patrol.get("patrol", {}).get("tasks", {}).get("Waiting On", [])
    git_dirty = patrol.get("patrol", {}).get("bootstrap", {}).get("git", {}).get("is_dirty", False)

    task_id = active_state.get("task_id")
    if task_id and not any(extract_id(line) == task_id for line in active_tasks):
        task_id = None
    if not task_id and len(active_tasks) == 1:
        task_id = extract_id(active_tasks[0])

    change = None
    gate = None
    try:
        change, _ = load_active_change(repo_root)
        target_by_phase = {
            "explore": "specify", "specify": "implement" if change.get("level") == "L1" else "design",
            "design": "plan", "plan": "implement", "implement": "verify", "verify": "release",
            "release": "operate", "operate": "learn", "learn": "completed",
        }
        target = target_by_phase.get(change.get("phase"))
        if target:
            gate = evaluate_gate(repo_root, change, target)
    except FileNotFoundError:
        pass

    verification = verification_summary(repo_root, change["id"]) if change and change.get("phase") == "verify" else None
    if blocking:
        action = str(blocking[0])
        reason = "project state has an explicit blocker"
        can_modify_code = False
    elif verification and not verification["release_ready"]:
        action = verification["next_action"]
        reason = "verification evidence does not yet satisfy release readiness"
        can_modify_code = False
    elif verification and verification["release_ready"]:
        action = "transition to release"
        reason = "active change verification is release ready"
        can_modify_code = False
    elif gate and not gate["allowed"]:
        action = gate["next_action"]
        reason = "active change phase gate has missing facts"
        can_modify_code = change.get("phase") == "implement"
    elif task_id:
        action = active_state.get("next_action") or f"continue {task_id}"
        reason = "one active task is selected"
        can_modify_code = True
    elif len(active_tasks) > 1:
        action = "select one active task by ID"
        reason = "multiple active tasks exist and no active task ID is selected"
        can_modify_code = False
    elif waiting_tasks:
        action = "resolve or review waiting tasks"
        reason = "work is waiting on an external condition"
        can_modify_code = False
    elif git_dirty:
        action = "review unassociated changes before shipping"
        reason = "the repository is dirty but no active task is selected"
        can_modify_code = False
    else:
        action = "create or select the next work item"
        reason = "the repository is idle"
        can_modify_code = False

    return {
        "command": "next",
        "repo_root": str(repo_root),
        "task_id": task_id,
        "change_id": change.get("id") if change else active_state.get("change_id"),
        "phase": change.get("phase") if change else active_state.get("phase"),
        "level": change.get("level") if change else active_state.get("level"),
        "next_action": action,
        "reason": reason,
        "can_modify_code": can_modify_code,
        "requires_approval": bool(gate and gate.get("requires_approval")),
        "gate": gate,
        "verification": verification,
        "summary": action,
    }


def command_policy_init(repo_root: Path, force: bool) -> dict[str, Any]:
    policy = load_default_policy()
    path = write_repo_policy(repo_root, policy, force=force)
    return {
        "command": "policy-init",
        "repo_root": str(repo_root),
        "policy_file": str(path),
        "summary": "initialized repo-local policy override",
    }


def command_onboard() -> dict[str, Any]:
    from onboard import main as onboard_main

    onboard_main()
    return {
        "command": "onboard",
        "repo_root": "",
        "summary": "onboarding completed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("intake", help="Run unified repo intake")

    patrol_parser = subparsers.add_parser("patrol", help="Run repo patrol with an optional preset")
    patrol_parser.add_argument("--preset", choices=PATROL_PRESETS, help="Patrol preset")
    patrol_parser.add_argument("--no-state-write", action="store_true", help="Do not update state during patrol")

    kickoff_parser = subparsers.add_parser("kickoff", help="Create the next task kickoff state")
    kickoff_parser.add_argument("title", help="Task title")
    kickoff_parser.add_argument("--route", choices=ROUTES, help="Optional explicit route")
    kickoff_parser.add_argument("--mode", choices=["normal", "fast"], help="Optional explicit mode")
    kickoff_parser.add_argument("--level", choices=["L0", "L1", "L2", "L3"], help="Requested governance level")
    kickoff_parser.add_argument("--approve-downgrade", action="store_true", help="Approve a lower non-hard-risk level")
    kickoff_parser.add_argument("--downgrade-reason", help="Required reason for governance downgrade")
    for dimension in DIMENSIONS:
        kickoff_parser.add_argument(f"--{dimension.replace('_', '-')}", type=int, choices=range(4), default=0)

    classify_parser = subparsers.add_parser("classify", help="Classify task governance depth")
    classify_parser.add_argument("description", help="Task or change description")
    classify_parser.add_argument("--level", choices=["L0", "L1", "L2", "L3"], help="Requested governance level")
    classify_parser.add_argument("--approve-downgrade", action="store_true")
    classify_parser.add_argument("--downgrade-reason")
    classify_parser.add_argument("--persist", action="store_true", help="Persist level and classification history")
    for dimension in DIMENSIONS:
        classify_parser.add_argument(f"--{dimension.replace('_', '-')}", type=int, choices=range(4), default=0)

    ship_parser = subparsers.add_parser("ship", help="Generate or execute a ship plan")
    ship_parser.add_argument("--title", required=True, help="Title used for branch and commit planning")
    ship_parser.add_argument("--execute", action="store_true", help="Execute the full ship flow (branch, validate, stage, commit, sync)")
    ship_parser.add_argument("--force", action="store_true", help="Continue past validation failures (only with --execute)")
    ship_parser.add_argument("--task-id", help="Stable task ID to close after a successful ship")

    auto_parser = subparsers.add_parser("auto", help="Auto-detect repo state and recommend/execute the next action")
    auto_parser.add_argument("--execute", action="store_true", help="Execute the recommended action automatically")
    auto_parser.add_argument("--force", action="store_true", help="Continue past validation failures (only with --execute)")

    subparsers.add_parser("state", help="Show current state")
    subparsers.add_parser("next", help="Show the deterministic next action")

    project_parser = subparsers.add_parser("project", help="Manage the repository project model")
    project_sub = project_parser.add_subparsers(dest="project_command", required=True)
    project_init = project_sub.add_parser("init", help="Initialize project metadata")
    project_init.add_argument("name")
    project_init.add_argument("--id", dest="project_id")

    change_parser = subparsers.add_parser("change", help="Manage specification-driven changes")
    change_sub = change_parser.add_subparsers(dest="change_command", required=True)
    change_create = change_sub.add_parser("create")
    change_create.add_argument("title")
    change_create.add_argument("--level", choices=["L1", "L2", "L3"], required=True)
    change_create.add_argument("--problem", default="")
    change_create.add_argument("--outcome", default="")
    change_create.add_argument("--acceptance", action="append", default=[])
    change_create.add_argument("--risk", action="append", default=[])
    change_show = change_sub.add_parser("show")
    change_show.add_argument("--id", dest="change_id")
    change_update = change_sub.add_parser("update")
    change_update.add_argument("--id", dest="change_id", required=True)
    change_update.add_argument("--problem")
    change_update.add_argument("--outcome")
    change_update.add_argument("--acceptance", action="append")
    change_update.add_argument("--risk", action="append")
    change_update.add_argument("--requirement", action="append")
    change_update.add_argument("--in-scope", action="append")
    change_update.add_argument("--out-of-scope", action="append")
    change_transition = change_sub.add_parser("transition")
    change_transition.add_argument("target_phase")
    change_transition.add_argument("--id", dest="change_id")
    change_transition.add_argument("--actor", required=True)
    change_transition.add_argument("--reason", default="")
    change_transition.add_argument("--override", action="store_true")
    change_transition.add_argument("--approval-ref")

    gate_parser = subparsers.add_parser("gate", help="Evaluate a phase transition gate")
    gate_parser.add_argument("target_phase")
    gate_parser.add_argument("--change-id")

    evidence_parser = subparsers.add_parser("evidence", help="Record or list executed verification evidence")
    evidence_sub = evidence_parser.add_subparsers(dest="evidence_command", required=True)
    evidence_record = evidence_sub.add_parser("record")
    evidence_record.add_argument("--change-id", required=True)
    evidence_record.add_argument("--type", dest="evidence_type", choices=["command", "api", "ui", "manual", "ci", "review"], required=True)
    evidence_record.add_argument("--status", choices=["passed", "failed", "observed"], required=True)
    evidence_record.add_argument("--summary", required=True)
    evidence_record.add_argument("--acceptance-id", action="append", default=[])
    evidence_record.add_argument("--requirement-id", action="append", default=[])
    evidence_record.add_argument("--task-id", action="append", default=[])
    evidence_record.add_argument("--command", dest="executed_command")
    evidence_record.add_argument("--exit-code", type=int)
    evidence_record.add_argument("--environment", default="local")
    evidence_record.add_argument("--reference")
    evidence_record.add_argument("--severity", choices=["low", "medium", "high", "critical"])
    evidence_list = evidence_sub.add_parser("list")
    evidence_list.add_argument("--change-id", required=True)

    verify_parser = subparsers.add_parser("verify", help="Summarize acceptance evidence and release readiness")
    verify_parser.add_argument("--change-id")
    drift_parser = subparsers.add_parser("drift", help="Report explainable scope and evidence drift")
    drift_parser.add_argument("--change-id")

    gitlab_parser = subparsers.add_parser("gitlab", help="Synchronize GitLab reference snapshots")
    gitlab_sub = gitlab_parser.add_subparsers(dest="gitlab_command", required=True)
    gitlab_sync = gitlab_sub.add_parser("sync", help="Plan or apply a read-only GitLab snapshot")
    gitlab_sync.add_argument("--snapshot", type=Path, required=True)
    gitlab_sync.add_argument("--change-id")
    gitlab_sync.add_argument("--apply", action="store_true", help="Apply the snapshot to local reference metadata")

    pilot_parser = subparsers.add_parser("pilot", help="Record real-project observations and evaluate V3 need")
    pilot_sub = pilot_parser.add_subparsers(dest="pilot_command", required=True)
    pilot_record = pilot_sub.add_parser("record")
    pilot_record.add_argument("metric")
    pilot_record.add_argument("value", type=float)
    pilot_record.add_argument("--note", default="")
    pilot_record.add_argument("--change-id")
    pilot_evaluate = pilot_sub.add_parser("evaluate")
    pilot_evaluate.add_argument("--change-id")

    policy_parser = subparsers.add_parser("policy-init", help="Initialize a repo-local policy override")
    policy_parser.add_argument("--force", action="store_true", help="Overwrite an existing repo-local policy")

    subparsers.add_parser("onboard", help="Run first-time setup and profile configuration")

    doc_parser = subparsers.add_parser("doc-config", help="Configure document storage and remote sync target")
    doc_parser.add_argument("--local-path", help="Local directory for generated docs (default: docs/changes)")
    doc_parser.add_argument("--remote-target", help="Remote sync target (e.g. gitlab:group/repo, dingtalk:space_id, or empty)")
    doc_parser.add_argument("--show", action="store_true", help="Show current doc config without modifying")

    gen_doc_parser = subparsers.add_parser("generate-docs", help="Generate documents for a change")
    gen_doc_parser.add_argument("change_id", nargs="?", help="Change ID (defaults to active)")
    gen_doc_parser.add_argument("--type", choices=["requirements", "test-report", "release-note", "all"], default="all")

    # workspace subcommands
    ws_parser = subparsers.add_parser("workspace", help="Manage cross-repo workspace")
    ws_sub = ws_parser.add_subparsers(dest="workspace_command", required=True)
    ws_add = ws_sub.add_parser("add", help="Register a repo")
    ws_add.add_argument("path", help="Path to repository")
    ws_add.add_argument("--alias", help="Optional alias")
    ws_remove = ws_sub.add_parser("remove", help="Remove a repo")
    ws_remove.add_argument("identifier", help="Alias or path")
    ws_sub.add_parser("list", help="List all repos")
    ws_status = ws_sub.add_parser("status", help="Update and show repo status")
    ws_status.add_argument("identifier", nargs="?", help="Optional alias")

    args = parser.parse_args()

    if args.command == "onboard":
        payload = command_onboard()
    elif args.command == "doc-config":
        from doc_sync import check_doc_config, get_doc_config, set_doc_config
        repo_root, _ = get_repo_root(Path(args.repo).resolve())
        if args.show:
            config = get_doc_config(repo_root)
            payload = {"command": "doc-config", "action": "show", "config": config, "summary": str(config) or "not configured"}
        elif args.local_path is None and args.remote_target is None:
            status = check_doc_config(repo_root)
            payload = {"command": "doc-config", "action": "status", **status, "summary": "configured" if status["configured"] else "not configured"}
        else:
            config = set_doc_config(repo_root, local_path=args.local_path, remote_target=args.remote_target)
            payload = {"command": "doc-config", "action": "set", "config": config, "summary": f"local={config.get('local_path')}, remote={config.get('remote_target', '')}"}
    elif args.command == "generate-docs":
        from doc_sync import (
            generate_requirements_doc, generate_test_report, generate_release_note,
        )
        repo_root, _ = get_repo_root(Path(args.repo).resolve())
        change, _ = find_change(repo_root, args.change_id) if args.change_id else load_active_change(repo_root)
        cid = change["id"]
        paths = []
        if args.type in ("requirements", "all"):
            p = generate_requirements_doc(repo_root, cid)
            if p:
                paths.append(str(p))
        if args.type in ("test-report", "all"):
            p = generate_test_report(repo_root, cid)
            if p:
                paths.append(str(p))
        if args.type in ("release-note", "all"):
            p = generate_release_note(repo_root, cid)
            if p:
                paths.append(str(p))
        payload = {"command": "generate-docs", "change_id": cid, "type": args.type, "docs": paths, "summary": f"{len(paths)} doc(s) generated"}
    elif args.command == "workspace":
        from workspace import list_repos, register, remove, summarize_repos, update_status

        if args.workspace_command == "add":
            alias = register(Path(args.path).resolve(), args.alias)
            payload = {
                "command": "workspace",
                "subcommand": "add",
                "alias": alias,
                "path": str(Path(args.path).resolve()),
                "summary": f"registered {alias}",
            }
        elif args.workspace_command == "remove":
            ok = remove(args.identifier)
            payload = {
                "command": "workspace",
                "subcommand": "remove",
                "identifier": args.identifier,
                "removed": ok,
                "summary": "removed" if ok else "not found",
            }
        elif args.workspace_command == "list":
            repos = list_repos()
            payload = {
                "command": "workspace",
                "subcommand": "list",
                "repos": repos,
                "summary": f"{len(repos)} repo(s)",
            }
        elif args.workspace_command == "status":
            repos = update_status(args.identifier)
            repos = summarize_repos(repos)
            payload = {
                "command": "workspace",
                "subcommand": "status",
                "identifier": args.identifier,
                "repos": repos,
                "summary": f"{len(repos)} repo(s)",
            }
    else:
        repo_root, _ = get_repo_root(Path(args.repo))

        if args.command == "intake":
            payload = command_intake(repo_root)
        elif args.command == "patrol":
            payload = command_patrol(repo_root, args.preset, args.no_state_write)
        elif args.command == "kickoff":
            dimensions = {name: getattr(args, name) for name in DIMENSIONS}
            payload = command_kickoff(
                repo_root, args.title, args.route, args.mode, dimensions, args.level,
                args.approve_downgrade, args.downgrade_reason,
            )
        elif args.command == "classify":
            dimensions = {name: getattr(args, name) for name in DIMENSIONS}
            payload = command_classify(
                repo_root, args.description, dimensions, args.level,
                args.approve_downgrade, args.downgrade_reason, args.persist,
            )
        elif args.command == "ship":
            payload = command_ship(repo_root, args.title, args.execute, args.force, args.task_id)
        elif args.command == "auto":
            payload = command_auto(repo_root, args.execute, args.force)
        elif args.command == "state":
            payload = command_state(repo_root)
        elif args.command == "next":
            payload = command_next(repo_root)
        elif args.command == "project":
            payload = command_project_init(repo_root, args.name, args.project_id)
        elif args.command == "change":
            if args.change_command == "create":
                payload = command_change_create(repo_root, args.title, args.level, args.problem, args.outcome, args.acceptance, args.risk)
            elif args.change_command == "show":
                payload = command_change_show(repo_root, args.change_id)
            elif args.change_command == "update":
                fields = {key: value for key, value in {
                    "problem": args.problem, "outcome": args.outcome,
                    "acceptance": ([{"id": f"ACC-{index:03d}", "scenario": item} for index, item in enumerate(args.acceptance, 1)] if args.acceptance is not None else None),
                    "risks": args.risk,
                    "requirements": ([{"id": f"REQ-{index:03d}", "statement": item} for index, item in enumerate(args.requirement, 1)] if args.requirement is not None else None),
                    "in_scope": args.in_scope, "out_of_scope": args.out_of_scope,
                }.items() if value is not None}
                payload = command_change_update(repo_root, args.change_id, fields)
            else:
                payload = command_phase_transition(repo_root, args.target_phase, args.actor, args.change_id, args.reason, args.override, args.approval_ref)
        elif args.command == "gate":
            payload = command_gate(repo_root, args.target_phase, args.change_id)
        elif args.command == "evidence":
            if args.evidence_command == "record":
                payload = command_evidence_record(
                    repo_root, args.change_id, args.evidence_type, args.summary, status=args.status,
                    acceptance_ids=args.acceptance_id, requirement_ids=args.requirement_id,
                    task_ids=args.task_id, command=args.executed_command, exit_code=args.exit_code,
                    environment=args.environment, reference=args.reference, severity=args.severity,
                )
            else:
                payload = command_evidence_list(repo_root, args.change_id)
        elif args.command == "verify":
            payload = command_verify(repo_root, args.change_id)
        elif args.command == "drift":
            payload = command_drift(repo_root, args.change_id)
        elif args.command == "gitlab":
            payload = command_gitlab_sync(repo_root, args.snapshot, args.change_id, args.apply)
        elif args.command == "pilot":
            if args.pilot_command == "record":
                payload = command_pilot_record(repo_root, args.metric, args.value, args.note, args.change_id)
            else:
                payload = command_pilot_evaluate(repo_root, args.change_id)
        elif args.command == "policy-init":
            payload = command_policy_init(repo_root, args.force)
        else:
            raise RuntimeError(f"Unknown command: {args.command}")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
