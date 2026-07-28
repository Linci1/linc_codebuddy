#!/usr/bin/env python3
"""GitLab reference synchronization with dry-run, idempotency, and conflict checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from lifecycle import find_change, update_change
from lib import now_iso


OBJECTS = ["project", "milestone", "issue", "merge_request", "pipeline", "release", "environment"]
ALLOWED_FIELDS = {
    "project": {"id", "path_with_namespace", "web_url"},
    "milestone": {"id", "iid", "title", "state", "updated_at", "web_url"},
    "issue": {"id", "iid", "title", "state", "updated_at", "web_url"},
    "merge_request": {"id", "iid", "title", "state", "updated_at", "web_url", "sha"},
    "pipeline": {"id", "status", "ref", "sha", "updated_at", "web_url"},
    "release": {"tag_name", "name", "released_at", "description_url", "web_url"},
    "environment": {"id", "name", "state", "external_url", "updated_at"},
}


def _normalized(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        key: {field: value for field, value in snapshot[key].items() if field in ALLOWED_FIELDS[key]}
        for key in OBJECTS if isinstance(snapshot.get(key), dict)
    }
    task_issues = snapshot.get("task_issues", {})
    if isinstance(task_issues, dict):
        normalized["task_issues"] = {
            task_id: {field: value for field, value in issue.items() if field in ALLOWED_FIELDS["issue"]}
            for task_id, issue in task_issues.items() if isinstance(issue, dict)
        }
    return normalized


def _fingerprint(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(_normalized(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity_conflicts(current: dict[str, Any], incoming: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for key in OBJECTS:
        old = current.get(key) or {}
        new = incoming.get(key) or {}
        if old.get("id") is not None and new.get("id") is not None and old["id"] != new["id"]:
            findings.append({
                "code": "REMOTE_BINDING_CONFLICT", "object": key,
                "current_id": old["id"], "incoming_id": new["id"],
                "message": f"{key} is already bound to a different GitLab object",
            })
    for task_id, new in incoming.get("task_issues", {}).items():
        old = current.get("task_issues", {}).get(task_id, {})
        if old.get("id") is not None and new.get("id") is not None and old["id"] != new["id"]:
            findings.append({
                "code": "TASK_ISSUE_BINDING_CONFLICT", "object": "task_issue", "task_id": task_id,
                "current_id": old["id"], "incoming_id": new["id"],
                "message": f"{task_id} is already bound to a different GitLab issue",
            })
    return findings


def plan_sync(repo_root: Path, change_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    change, _ = find_change(repo_root, change_id)
    incoming = _normalized(snapshot)
    current = change.get("external", {}).get("gitlab", {}).get("snapshot", {})
    conflicts = _identity_conflicts(current, incoming)
    incoming_fingerprint = _fingerprint(incoming)
    current_fingerprint = change.get("external", {}).get("gitlab", {}).get("fingerprint")
    if conflicts:
        status = "conflict"
    elif incoming_fingerprint == current_fingerprint:
        status = "noop"
    else:
        status = "planned"
    return {
        "schema_version": 1, "change_id": change_id, "provider": "gitlab", "mode": "read_only",
        "status": status, "can_apply": status == "planned", "mutated": False,
        "base_fingerprint": current_fingerprint,
        "fingerprint": incoming_fingerprint, "snapshot": incoming, "conflicts": conflicts,
        "planned_at": now_iso(),
    }


def apply_sync(repo_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("status") == "noop":
        return {**plan, "mutated": False, "applied_at": now_iso()}
    if plan.get("status") != "planned" or not plan.get("can_apply"):
        raise ValueError("only a conflict-free planned sync can be applied")
    change, _ = find_change(repo_root, plan["change_id"])
    current_gitlab = change.get("external", {}).get("gitlab", {})
    if current_gitlab.get("fingerprint") != plan.get("base_fingerprint"):
        raise ValueError("GitLab sync plan is stale; generate a new plan")
    conflicts = _identity_conflicts(current_gitlab.get("snapshot", {}), plan.get("snapshot", {}))
    if conflicts:
        raise ValueError("GitLab sync plan conflicts with current bindings; generate a new plan")
    external = dict(change.get("external", {}))
    history = list(external.get("sync_history", []))
    history.append({
        "provider": "gitlab", "fingerprint": plan["fingerprint"], "status": "applied",
        "at": now_iso(),
    })
    external["gitlab"] = {
        "snapshot": plan["snapshot"], "fingerprint": plan["fingerprint"],
        "synced_at": now_iso(), "authority": "reference_only",
    }
    external["sync_history"] = history[-50:]
    update_change(repo_root, plan["change_id"], external=external)
    return {**plan, "status": "applied", "mutated": True, "applied_at": now_iso()}


def write_external_action(
    repo_root: Path, change_id: str, action: str, payload: dict[str, Any], *, execute: bool = False,
    approval_ref: str | None = None, actor: str | None = None,
    executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    find_change(repo_root, change_id)
    preview = {
        "change_id": change_id, "provider": "gitlab", "action": action, "target": payload.get("target"),
        "payload": payload, "status": "dry_run", "executed": False, "approval_ref": approval_ref,
    }
    if not execute:
        return preview
    if not approval_ref or not actor:
        raise ValueError("external write requires approval_ref and actor")
    if executor is None:
        raise ValueError("external write requires an explicit executor")
    result = executor(action, payload)
    return {
        **preview, "status": "executed", "executed": True, "approval_ref": approval_ref,
        "actor": actor, "executed_at": now_iso(), "result": result,
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("GitLab snapshot must be a JSON object")
    return data
