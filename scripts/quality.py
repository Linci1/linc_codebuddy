#!/usr/bin/env python3
"""Verification evidence, traceability summaries, and explainable drift checks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from lifecycle import ROOT, find_change
from lib import atomic_write_json, now_iso, run


SECRET_PATTERNS = [
    re.compile(r"(?i)\b(token|secret|password|passwd|api[_-]?key)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\bauthorization:\s*bearer\s+[^\s]+"),
]
BLOCKING_SEVERITIES = {"high", "critical"}


def _redact(text: str, limit: int = 2000) -> str:
    cleaned = text
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.lower().startswith("(?i)\\bauthorization"):
            cleaned = pattern.sub("Authorization: Bearer [REDACTED]", cleaned)
        else:
            cleaned = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", cleaned)
    return cleaned[:limit]


def _acceptance_fingerprints(change: dict[str, Any]) -> dict[str, str]:
    return {
        item["id"]: hashlib.sha256(item.get("scenario", "").encode("utf-8")).hexdigest()[:16]
        for item in change.get("acceptance", []) if item.get("id")
    }


def _requirement_fingerprints(change: dict[str, Any]) -> dict[str, str]:
    return {
        item["id"]: hashlib.sha256(item.get("statement", "").encode("utf-8")).hexdigest()[:16]
        for item in change.get("requirements", []) if item.get("id")
    }


def evidence_dir(repo_root: Path, change_id: str) -> Path:
    return repo_root / ROOT / "evidence" / change_id


def list_evidence(repo_root: Path, change_id: str) -> list[dict[str, Any]]:
    directory = evidence_dir(repo_root, change_id)
    if not directory.exists():
        return []
    records = []
    for path in sorted(directory.glob("EVD-*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return records


def _next_evidence_id(repo_root: Path, change_id: str) -> str:
    highest = 0
    for item in list_evidence(repo_root, change_id):
        match = re.fullmatch(r"EVD-(\d{3})", item.get("id", ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"EVD-{highest + 1:03d}"


def record_evidence(
    repo_root: Path, change_id: str, evidence_type: str, summary: str, *, status: str,
    acceptance_ids: list[str] | None = None, requirement_ids: list[str] | None = None,
    task_ids: list[str] | None = None, command: str | None = None, exit_code: int | None = None,
    environment: str = "local", reference: str | None = None, severity: str | None = None,
) -> dict[str, Any]:
    if status not in {"passed", "failed", "observed"}:
        raise ValueError("evidence status must be passed, failed, or observed")
    change, _ = find_change(repo_root, change_id)
    fingerprints = _acceptance_fingerprints(change)
    requirement_fingerprints = _requirement_fingerprints(change)
    linked_acceptance = acceptance_ids or []
    unknown = sorted(set(linked_acceptance) - set(fingerprints))
    if unknown:
        raise ValueError(f"unknown acceptance IDs: {', '.join(unknown)}")
    unknown_requirements = sorted(set(requirement_ids or []) - set(requirement_fingerprints))
    if unknown_requirements:
        raise ValueError(f"unknown requirement IDs: {', '.join(unknown_requirements)}")
    evidence_id = _next_evidence_id(repo_root, change_id)
    record = {
        "schema_version": 1, "id": evidence_id, "change_id": change_id, "type": evidence_type,
        "status": status, "summary": _redact(summary), "acceptance_ids": linked_acceptance,
        "acceptance_fingerprints": {item: fingerprints[item] for item in linked_acceptance},
        "requirement_ids": requirement_ids or [], "task_ids": task_ids or [],
        "requirement_fingerprints": {item: requirement_fingerprints[item] for item in requirement_ids or []},
        "command": _redact(command) if command else None, "exit_code": exit_code,
        "environment": environment, "reference": reference, "severity": severity,
        "executed_at": now_iso(),
    }
    path = evidence_dir(repo_root, change_id) / f"{evidence_id}.json"
    atomic_write_json(path, record)
    return record


def verification_summary(repo_root: Path, change_id: str) -> dict[str, Any]:
    change, _ = find_change(repo_root, change_id)
    evidence = list_evidence(repo_root, change_id)
    current = _acceptance_fingerprints(change)
    current_requirements = _requirement_fingerprints(change)
    rows = []
    for acceptance in change.get("acceptance", []):
        acc_id = acceptance["id"]
        linked = [item for item in evidence if acc_id in item.get("acceptance_ids", [])]
        passing = [item for item in linked if item.get("status") == "passed"]
        current_passing = [
            item for item in passing
            if item.get("acceptance_fingerprints", {}).get(acc_id) == current.get(acc_id)
        ]
        status = "passed" if current_passing else ("stale" if passing else "missing")
        rows.append({
            "acceptance_id": acc_id, "scenario": acceptance.get("scenario"), "status": status,
            "evidence_ids": [item["id"] for item in current_passing],
        })
    requirement_rows = []
    for requirement in change.get("requirements", []):
        req_id = requirement["id"]
        linked = [item for item in evidence if req_id in item.get("requirement_ids", []) and item.get("status") == "passed"]
        current_linked = [item for item in linked if item.get("requirement_fingerprints", {}).get(req_id) == current_requirements.get(req_id)]
        requirement_rows.append({
            "requirement_id": req_id, "statement": requirement.get("statement"),
            "status": "passed" if current_linked else ("stale" if linked else "missing"),
            "evidence_ids": [item["id"] for item in current_linked],
        })
    blockers = [
        item for item in evidence
        if item.get("type") == "review" and item.get("status") == "failed"
        and str(item.get("severity", "")).lower() in BLOCKING_SEVERITIES
    ]
    gitlab = change.get("external", {}).get("gitlab", {}).get("snapshot", {})
    external_references = {
        key: gitlab[key] for key in ["merge_request", "pipeline", "release", "environment"]
        if isinstance(gitlab.get(key), dict)
    }
    passed = bool(rows) and all(item["status"] == "passed" for item in rows) and all(item["status"] == "passed" for item in requirement_rows)
    return {
        "change_id": change_id, "phase": change.get("phase"), "passed": passed,
        "release_ready": passed and not blockers, "acceptance": rows, "requirements": requirement_rows,
        "evidence_count": len(evidence), "blocking_findings": blockers,
        "external_references": external_references,
        "next_action": (
            "resolve blocking review findings" if blockers else
            "record passing evidence for missing or stale acceptance" if not passed else
            "transition to release"
        ),
    }


def write_verification_report(repo_root: Path, change_id: str) -> tuple[dict[str, Any], Path]:
    summary = verification_summary(repo_root, change_id)
    _, change_path = find_change(repo_root, change_id)
    lines = [
        f"# Verification: {change_id}", "", f"Release ready: {'yes' if summary['release_ready'] else 'no'}", "",
        "| Requirement | Status | Evidence |", "|---|---|---|",
    ]
    for row in summary["requirements"]:
        lines.append(f"| {row['requirement_id']} | {row['status']} | {', '.join(row['evidence_ids']) or '-'} |")
    lines.extend(["", "| Acceptance | Scenario | Status | Evidence |", "|---|---|---|---|"])
    for row in summary["acceptance"]:
        scenario = str(row.get("scenario", "")).replace("|", "\\|")
        lines.append(f"| {row['acceptance_id']} | {scenario} | {row['status']} | {', '.join(row['evidence_ids']) or '-'} |")
    lines.extend(["", "## Blocking Review Findings", ""])
    if summary["blocking_findings"]:
        lines.extend(f"- {item['id']}: {item['summary']}" for item in summary["blocking_findings"])
    else:
        lines.append("- None")
    lines.extend(["", f"Next action: {summary['next_action']}", ""])
    path = change_path.parent / "verification.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return summary, path


def _changed_files(repo_root: Path) -> list[str]:
    result = run(["git", "status", "--porcelain"], repo_root)
    files = []
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path and not path.startswith(".codex/"):
            files.append(path)
    return files


def detect_drift(repo_root: Path, change_id: str) -> dict[str, Any]:
    change, _ = find_change(repo_root, change_id)
    scope = change.get("in_scope", [])
    changed = _changed_files(repo_root)
    findings: list[dict[str, Any]] = []
    if scope:
        outside = [path for path in changed if not any(path == item.rstrip("/") or path.startswith(item.rstrip("/") + "/") for item in scope)]
        if outside:
            findings.append({
                "code": "OUT_OF_SCOPE_FILE", "severity": "warning", "files": outside,
                "message": "changed files are outside declared change scope",
                "next_action": "confirm scope or remove unrelated changes",
            })
    verification = verification_summary(repo_root, change_id)
    stale = [item["acceptance_id"] for item in verification["acceptance"] if item["status"] == "stale"]
    stale_requirements = [item["requirement_id"] for item in verification["requirements"] if item["status"] == "stale"]
    if stale:
        findings.append({
            "code": "STALE_EVIDENCE", "severity": "blocking", "acceptance_ids": stale,
            "message": "acceptance changed after its evidence was recorded",
            "next_action": "re-run verification for changed acceptance",
        })
    if stale_requirements:
        findings.append({
            "code": "STALE_REQUIREMENT_EVIDENCE", "severity": "blocking", "requirement_ids": stale_requirements,
            "message": "requirement changed after its evidence was recorded",
            "next_action": "re-confirm implementation and verification for changed requirement",
        })
    return {
        "change_id": change_id, "findings": findings, "has_blocking": any(item["severity"] == "blocking" for item in findings),
        "changed_files": changed, "next_action": findings[0]["next_action"] if findings else "no drift action required",
    }
