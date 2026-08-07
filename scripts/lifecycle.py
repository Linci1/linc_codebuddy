#!/usr/bin/env python3
"""Repository-backed project, change, phase, and gate management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_state import load_state, save_state
from identity import next_change_id
from lib import atomic_write_json, now_iso, slugify


ROOT = Path(".codex/linc_codebuddy")
PHASES = [
    "explore", "specify", "design", "plan", "implement", "verify",
    "release", "operate", "learn", "completed", "cancelled",
]
FORWARD = {
    "explore": {"specify"}, "specify": {"design", "plan", "implement"},
    "design": {"plan", "implement", "specify"},
    "plan": {"implement", "design", "specify"},
    "implement": {"verify", "design", "specify"},
    "verify": {"release", "implement"}, "release": {"operate", "verify"},
    "operate": {"learn", "implement"}, "learn": {"completed", "implement"},
    "completed": set(), "cancelled": set(),
}
PROTECTED_SIGNALS = {"production", "生产", "permission", "权限", "irreversible", "不可逆", "delete", "删除"}
PHASE_NEXT_ACTION = {
    "explore": "complete project exploration",
    "specify": "complete the change specification",
    "design": "complete the change design",
    "plan": "complete the implementation plan",
    "implement": "complete the active implementation tasks",
    "verify": "record acceptance evidence and evaluate release readiness",
    "release": "complete release records and deployment",
    "operate": "observe production behavior",
    "learn": "record lessons and close the change",
    "completed": "select the next change",
    "cancelled": "select the next change",
}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def project_path(repo_root: Path) -> Path:
    return repo_root / ROOT / "project.yaml"


def init_project(repo_root: Path, name: str, project_id: str | None = None) -> dict[str, Any]:
    path = project_path(repo_root)
    if path.exists():
        return _read(path)
    now = now_iso()
    project = {
        "schema_version": 1, "id": project_id or f"PRJ-{slugify(name)}", "name": name,
        "phase": "explore", "active_change_id": None, "created_at": now, "updated_at": now,
    }
    atomic_write_json(path, project)
    return project


def _change_paths(repo_root: Path) -> list[Path]:
    return list((repo_root / ROOT / "changes").glob("*/change.yaml"))


def find_change(repo_root: Path, change_id: str) -> tuple[dict[str, Any], Path]:
    for path in _change_paths(repo_root):
        data = _read(path)
        if data.get("id") == change_id:
            return data, path
    raise FileNotFoundError(f"change not found: {change_id}")


def create_change(
    repo_root: Path, title: str, level: str, *, problem: str = "", outcome: str = "",
    acceptance: list[str] | None = None, risks: list[str] | None = None,
) -> dict[str, Any]:
    if level == "L0":
        raise ValueError("L0 tasks do not create change directories")
    project = init_project(repo_root, repo_root.name)
    change_id = next_change_id(repo_root, slugify(title))
    now = now_iso()
    change = {
        "schema_version": 1, "id": change_id, "project_id": project["id"], "title": title,
        "level": level, "phase": "specify", "status": "active", "problem": problem,
        "outcome": outcome, "in_scope": [], "out_of_scope": [],
        "requirements": [],
        "acceptance": [{"id": f"ACC-{index:03d}", "scenario": item} for index, item in enumerate(acceptance or [], 1)],
        "risks": risks or [], "tasks": [], "approvals": [], "transitions": [],
        "created_at": now, "updated_at": now,
    }
    path = repo_root / ROOT / "changes" / change_id / "change.yaml"
    atomic_write_json(path, change)
    project["active_change_id"] = change_id
    project["phase"] = "specify"
    project["updated_at"] = now
    atomic_write_json(project_path(repo_root), project)
    state_path, state = load_state(repo_root)
    state.setdefault("active", {})["change_id"] = change_id
    state["active"]["phase"] = "specify"
    state["active"]["level"] = level
    state["active"]["next_action"] = "complete the change specification"
    save_state(state_path, state)
    return change


def update_change(repo_root: Path, change_id: str, **fields: Any) -> dict[str, Any]:
    change, path = find_change(repo_root, change_id)
    for key, value in fields.items():
        if key in {"id", "project_id", "created_at"}:
            raise ValueError(f"immutable change field: {key}")
        change[key] = value
    change["updated_at"] = now_iso()
    atomic_write_json(path, change)
    return change


def load_active_change(repo_root: Path) -> tuple[dict[str, Any], Path]:
    project = _read(project_path(repo_root))
    change_id = project.get("active_change_id")
    if not change_id:
        raise FileNotFoundError("no active change")
    return find_change(repo_root, change_id)


def _missing(repo_root: Path, change: dict[str, Any], target: str) -> list[dict[str, str]]:
    level = change.get("level", "L1")
    missing: list[dict[str, str]] = []
    if target in {"design", "plan", "implement"}:
        if not change.get("problem"):
            missing.append({"code": "PROBLEM_MISSING", "message": "problem is required"})
        if not change.get("outcome"):
            missing.append({"code": "OUTCOME_MISSING", "message": "outcome is required"})
        if level in {"L2", "L3"} and not change.get("acceptance"):
            missing.append({"code": "ACCEPTANCE_MISSING", "message": "acceptance scenarios are required"})
    if target == "verify" and not any(task.get("status") == "done" for task in change.get("tasks", [])):
        missing.append({"code": "IMPLEMENTATION_INCOMPLETE", "message": "at least one implementation task must be done"})
    if target == "release":
        from quality import verification_summary

        summary = verification_summary(repo_root, change["id"])
        if not summary["release_ready"]:
            missing.append({"code": "VERIFICATION_INCOMPLETE", "message": "acceptance evidence or review findings block release"})
    return missing


def evaluate_gate(
    repo_root: Path, change: dict[str, Any], target_phase: str, *, override: bool = False,
    actor: str = "unknown", reason: str | None = None, approval_ref: str | None = None,
) -> dict[str, Any]:
    missing = _missing(repo_root, change, target_phase)
    protected = target_phase in {"release", "operate"} and any(
        signal in str(change.get("risks", [])).lower() for signal in PROTECTED_SIGNALS
    )
    if protected and not approval_ref:
        missing.append({"code": "PROTECTED_APPROVAL_REQUIRED", "message": "protected action requires explicit approval"})
    can_override = bool(override and reason and not protected)
    effective_missing = [] if can_override else missing
    actions = {
        "PROBLEM_MISSING": "describe the problem to solve",
        "OUTCOME_MISSING": "describe the expected outcome",
        "ACCEPTANCE_MISSING": "add at least one acceptance scenario",
        "IMPLEMENTATION_INCOMPLETE": "complete and record an implementation task",
        "VERIFICATION_INCOMPLETE": "record acceptance evidence and resolve review findings",
        "PROTECTED_APPROVAL_REQUIRED": "record explicit approval for the protected action",
    }
    return {
        "allowed": not effective_missing, "from_phase": change.get("phase"), "target_phase": target_phase,
        "level": change.get("level"), "missing": effective_missing, "warnings": [],
        "next_action": actions[effective_missing[0]["code"]] if effective_missing else f"transition to {target_phase}",
        "requires_approval": protected and not approval_ref, "overridden": can_override,
        "override": {"actor": actor, "reason": reason, "at": now_iso()} if can_override else None,
    }


def transition_change(
    repo_root: Path, change_id: str, target_phase: str, *, actor: str, reason: str = "",
    override: bool = False, approval_ref: str | None = None,
) -> dict[str, Any]:
    if target_phase not in PHASES:
        raise ValueError(f"unknown phase: {target_phase}")
    change, path = find_change(repo_root, change_id)
    current = change["phase"]
    if target_phase not in FORWARD[current] and target_phase != "cancelled":
        raise ValueError(f"illegal phase transition: {current} -> {target_phase}")
    gate = evaluate_gate(repo_root, change, target_phase, override=override, actor=actor, reason=reason, approval_ref=approval_ref)
    if not gate["allowed"]:
        return {"transitioned": False, "change": change, "change_file": str(path), "gate": gate}

    # Generate lightweight docs on phase transitions (best-effort, never blocks)
    generated_docs: list[str] = []
    try:
        from doc_sync import generate_for_phase
        for doc_path in generate_for_phase(repo_root, change_id, target_phase):
            generated_docs.append(str(doc_path.relative_to(repo_root)))
    except Exception:
        pass

    record = {
        "from": current, "to": target_phase, "actor": actor, "reason": reason,
        "gate": gate, "approval_ref": approval_ref, "at": now_iso(),
    }
    change["phase"] = target_phase
    change["status"] = "completed" if target_phase == "completed" else ("cancelled" if target_phase == "cancelled" else "active")
    change.setdefault("transitions", []).append(record)
    if gate.get("override"):
        change.setdefault("approvals", []).append({"type": "override", **gate["override"]})
    change["updated_at"] = now_iso()
    atomic_write_json(path, change)
    project = _read(project_path(repo_root))
    project["phase"] = target_phase
    project["active_change_id"] = None if target_phase in {"completed", "cancelled"} else change_id
    project["updated_at"] = now_iso()
    atomic_write_json(project_path(repo_root), project)
    state_path, state = load_state(repo_root)
    active = state.setdefault("active", {})
    active["change_id"] = project["active_change_id"]
    active["phase"] = target_phase
    active["next_action"] = PHASE_NEXT_ACTION[target_phase]
    save_state(state_path, state)
    return {"transitioned": True, "change": change, "change_file": str(path), "gate": gate, "generated_docs": generated_docs}
