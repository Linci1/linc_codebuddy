#!/usr/bin/env python3
"""Record real-project pilot observations and make an evidence-based V3 decision."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lifecycle import find_change
from lib import atomic_write_json, now_iso


def pilot_path(repo_root: Path, change_id: str) -> Path:
    _, change_path = find_change(repo_root, change_id)
    return change_path.parent / "pilot.json"


def load_pilot(repo_root: Path, change_id: str) -> dict[str, Any]:
    path = pilot_path(repo_root, change_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema_version": 1, "change_id": change_id, "observations": [], "created_at": now_iso()}


def record_observation(repo_root: Path, change_id: str, metric: str, value: float, note: str = "") -> dict[str, Any]:
    data = load_pilot(repo_root, change_id)
    data["observations"].append({"metric": metric, "value": value, "note": note, "at": now_iso()})
    data["updated_at"] = now_iso()
    atomic_write_json(pilot_path(repo_root, change_id), data)
    return data["observations"][-1]


def evaluate_pilot(repo_root: Path, change_id: str) -> dict[str, Any]:
    data = load_pilot(repo_root, change_id)
    totals: dict[str, float] = {}
    for item in data["observations"]:
        totals[item["metric"]] = totals.get(item["metric"], 0) + float(item["value"])
    reasons = []
    if totals.get("long_task_resume_failures", 0) >= 2:
        reasons.append("repeated long-task resume failures indicate durable orchestration may help")
    if totals.get("parallelizable_blocked_work", 0) >= 2:
        reasons.append("independent work repeatedly waited for serial execution")
    if totals.get("scheduled_patrol_need", 0) >= 2:
        reasons.append("repeated scheduled patrol demand indicates a resident runner may help")
    decision = "candidate" if reasons else "no-go"
    return {
        "change_id": change_id, "metrics": totals, "v3_decision": decision, "reasons": reasons or ["V2 workflow has no demonstrated orchestration bottleneck"],
        "next_action": "prepare a scoped V3 experiment" if decision == "candidate" else "continue V2 usage on real projects",
        "evaluated_at": now_iso(),
    }
