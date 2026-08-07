#!/usr/bin/env python3
"""Lightweight document generation and configurable storage sync.

Documents are generated from existing structured state (change.yaml, evidence
JSON, verification summaries) — no parallel authoring required.

Two config parameters are collected at intake time, never hardcoded:
  - local_path:  relative directory inside the repo for Markdown docs
  - remote_target: optional external destination (gitlab:<repo>, dingtalk:<space_id>, or empty)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib import atomic_write_json, now_iso

ROOT = Path(".codex/linc_codebuddy")
DEFAULT_LOCAL_PATH = "docs/changes"


# ── Config management ──────────────────────────────────────────────


def get_doc_config(repo_root: Path) -> dict[str, Any]:
    project_path = repo_root / ROOT / "project.yaml"
    if project_path.exists():
        project = json.loads(project_path.read_text(encoding="utf-8"))
        return project.get("doc_config") or {}
    return {}


def set_doc_config(
    repo_root: Path, *, local_path: str | None = None, remote_target: str | None = None,
) -> dict[str, Any]:
    """Persist doc config into project.yaml. Only updates provided fields."""
    project_path = repo_root / ROOT / "project.yaml"
    if not project_path.exists():
        raise FileNotFoundError("project not initialized — run project-init first")
    project = json.loads(project_path.read_text(encoding="utf-8"))
    config = project.get("doc_config") or {}
    if local_path is not None:
        config["local_path"] = local_path
    if remote_target is not None:
        config["remote_target"] = remote_target
    config["updated_at"] = now_iso()
    project["doc_config"] = config
    project["updated_at"] = now_iso()
    atomic_write_json(project_path, project)
    return config


def check_doc_config(repo_root: Path) -> dict[str, Any]:
    """Return config status and a user-facing prompt if config is missing."""
    config = get_doc_config(repo_root)
    if config.get("local_path"):
        return {"configured": True, "config": config, "prompt": None}
    prompt = (
        "请配置文档存储参数（两个）：\n"
        "1. local_path — 文档在项目内的存储目录（默认 docs/changes）\n"
        "2. remote_target — 远程同步目标（如 gitlab:400/pandawiki-eco-partner，"
        "dingtalk:<space_id>，或留空表示仅本地存储）\n"
        "使用 lcb_doc_config 或 `linc-codebuddy doc-config` 设置。"
    )
    return {"configured": False, "config": config, "prompt": prompt}


# ── Document generation ────────────────────────────────────────────


def _change_dir(repo_root: Path, change_id: str) -> Path:
    return repo_root / ROOT / "changes" / change_id


def _doc_dir(repo_root: Path, config: dict[str, Any]) -> Path:
    return repo_root / config.get("local_path", DEFAULT_LOCAL_PATH)


def generate_requirements_doc(repo_root: Path, change_id: str) -> Path | None:
    """Generate a readable requirements document from change.yaml."""
    config = get_doc_config(repo_root)
    change_path = _change_dir(repo_root, change_id) / "change.yaml"
    if not change_path.exists():
        return None
    change = json.loads(change_path.read_text(encoding="utf-8"))
    lines = [
        f"# 需求文档: {change.get('title', change_id)}", "",
        f"- **变更 ID**: `{change_id}`",
        f"- **治理等级**: {change.get('level', '?')}",
        f"- **创建时间**: {change.get('created_at', '?')}",
        "",
        "## 问题描述", "",
        change.get("problem") or "_(待补充)_",
        "",
        "## 预期结果", "",
        change.get("outcome") or "_(待补充)_",
        "",
    ]
    requirements = change.get("requirements", [])
    if requirements:
        lines += ["## 需求清单", "", "| ID | 描述 |", "|---|---|"]
        lines += [f"| {r['id']} | {r.get('statement', '')} |" for r in requirements]
        lines.append("")
    acceptance = change.get("acceptance", [])
    if acceptance:
        lines += ["## 验收条件", "", "| ID | 场景 |", "|---|---|"]
        lines += [f"| {a['id']} | {a.get('scenario', '')} |" for a in acceptance]
        lines.append("")
    in_scope = change.get("in_scope", [])
    out_scope = change.get("out_of_scope", [])
    if in_scope or out_scope:
        lines += ["## 范围", ""]
        if in_scope:
            lines += ["**包含:**"]
            lines += [f"- {item}" for item in in_scope]
            lines.append("")
        if out_scope:
            lines += ["**不包含:**"]
            lines += [f"- {item}" for item in out_scope]
            lines.append("")
    risks = change.get("risks", [])
    if risks:
        lines += ["## 风险", ""]
        lines += [f"- {r}" for r in risks]
        lines.append("")
    return _write_doc(repo_root, config, change_id, "requirements.md", lines)


def generate_test_report(repo_root: Path, change_id: str) -> Path | None:
    """Generate a test report from evidence records and verification summary."""
    from quality import list_evidence, verification_summary
    config = get_doc_config(repo_root)
    change_path = _change_dir(repo_root, change_id) / "change.yaml"
    if not change_path.exists():
        return None
    change = json.loads(change_path.read_text(encoding="utf-8"))
    summary = verification_summary(repo_root, change_id)
    evidence = list_evidence(repo_root, change_id)
    lines = [
        f"# 测试报告: {change.get('title', change_id)}", "",
        f"- **变更 ID**: `{change_id}`",
        f"- **Release Ready**: {'yes' if summary['release_ready'] else 'no'}",
        f"- **生成时间**: {now_iso()}",
        "",
        "## 验收矩阵", "",
        "| 验收 ID | 场景 | 状态 | 证据 |",
        "|---|---|---|---|",
    ]
    for row in summary["acceptance"]:
        scenario = str(row.get("scenario", "")).replace("|", "\\|")
        lines.append(f"| {row['acceptance_id']} | {scenario} | {row['status']} | {', '.join(row['evidence_ids']) or '-'} |")
    if summary["requirements"]:
        lines += ["", "## 需求验证", "", "| 需求 ID | 描述 | 状态 | 证据 |", "|---|---|---|---|"]
        for row in summary["requirements"]:
            stmt = str(row.get("statement", "")).replace("|", "\\|")
            lines.append(f"| {row['requirement_id']} | {stmt} | {row['status']} | {', '.join(row['evidence_ids']) or '-'} |")
    lines += ["", "## 验证记录", ""]
    if evidence:
        for ev in evidence:
            lines += [
                f"### {ev['id']}",
                f"- 类型: {ev.get('type', '?')}",
                f"- 状态: {ev.get('status', '?')}",
                f"- 摘要: {ev.get('summary', '')}",
            ]
            if ev.get("command"):
                lines.append(f"- 命令: `{ev['command']}`")
            if ev.get("exit_code") is not None:
                lines.append(f"- 退出码: {ev['exit_code']}")
            lines.append("")
    else:
        lines.append("_(暂无验证记录)_")
        lines.append("")
    if summary["blocking_findings"]:
        lines += ["## 阻塞项", ""]
        lines += [f"- {f['id']}: {f['summary']}" for f in summary["blocking_findings"]]
        lines.append("")
    return _write_doc(repo_root, config, change_id, "test-report.md", lines)


def generate_release_note(repo_root: Path, change_id: str) -> Path | None:
    """Generate a release note from change data and verification results."""
    from quality import verification_summary
    config = get_doc_config(repo_root)
    change_path = _change_dir(repo_root, change_id) / "change.yaml"
    if not change_path.exists():
        return None
    change = json.loads(change_path.read_text(encoding="utf-8"))
    summary = verification_summary(repo_root, change_id)
    title = change.get("title", change_id)
    lines = [
        f"# Release Note: {title}", "",
        f"- **变更 ID**: `{change_id}`",
        f"- **发布时间**: {now_iso()}",
        f"- **治理等级**: {change.get('level', '?')}",
        "",
        "## 变更内容", "",
        f"**问题**: {change.get('problem', '_(未描述)_')}",
        "",
        f"**结果**: {change.get('outcome', '_(未描述)_')}",
        "",
    ]
    requirements = change.get("requirements", [])
    if requirements:
        delivered = summary.get("requirements", [])
        status_map = {r["requirement_id"]: r["status"] for r in delivered}
        lines += ["## 需求实现", "", "| ID | 描述 | 状态 |", "|---|---|---|"]
        for r in requirements:
            status = status_map.get(r["id"], "unknown")
            lines.append(f"| {r['id']} | {r.get('statement', '')} | {status} |")
        lines.append("")
    lines += [
        "## 验证结果", "",
        f"- Release Ready: {'yes' if summary['release_ready'] else 'no'}",
        f"- 验收通过: {sum(1 for a in summary['acceptance'] if a['status'] == 'passed')}/{len(summary['acceptance'])}",
        f"- 阻塞项: {len(summary['blocking_findings'])}",
        "",
    ]
    risks = change.get("risks", [])
    if risks:
        lines += ["## 风险与回滚", ""]
        lines += [f"- {r}" for r in risks]
        lines.append("")
    else:
        lines += ["## 风险与回滚", "", "_(无已知风险)_", ""]
    transitions = change.get("transitions", [])
    release_transition = next((t for t in transitions if t.get("to") == "release"), None)
    if release_transition:
        lines += [
            "## 发布记录", "",
            f"- 操作人: {release_transition.get('actor', '?')}",
            f"- 时间: {release_transition.get('at', '?')}",
            f"- 理由: {release_transition.get('reason', '')}",
            "",
        ]
    return _write_doc(repo_root, config, change_id, "release-note.md", lines)


# ── Internal helpers ───────────────────────────────────────────────


def _write_doc(
    repo_root: Path, config: dict[str, Any], change_id: str, filename: str, lines: list[str],
) -> Path:
    doc_dir = _doc_dir(repo_root, config) / change_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    path = doc_dir / filename
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── Phase-triggered generation ─────────────────────────────────────


def generate_for_phase(repo_root: Path, change_id: str, target_phase: str) -> list[Path]:
    """Generate the appropriate document(s) for a lifecycle phase transition."""
    config = get_doc_config(repo_root)
    if not config.get("local_path"):
        return []
    generated: list[Path] = []
    if target_phase in {"design", "plan", "implement"}:
        path = generate_requirements_doc(repo_root, change_id)
        if path:
            generated.append(path)
    if target_phase == "verify":
        path = generate_test_report(repo_root, change_id)
        if path:
            generated.append(path)
    if target_phase in {"release", "operate"}:
        path = generate_release_note(repo_root, change_id)
        if path:
            generated.append(path)
    return generated


# ── Remote sync (pluggable, reference-only by default) ─────────────


def sync_docs(repo_root: Path, change_id: str) -> dict[str, Any]:
    """Sync generated docs to the configured remote target.

    This is a pluggable hook — it inspects the remote_target prefix and
    delegates to the appropriate adapter. Currently returns a reference
    plan only; real API calls require explicit credentials and authorization.
    """
    config = get_doc_config(repo_root)
    remote = config.get("remote_target", "")
    if not remote:
        return {"synced": False, "reason": "no remote_target configured"}
    doc_dir = _doc_dir(repo_root, config) / change_id
    docs = sorted(doc_dir.glob("*.md")) if doc_dir.exists() else []
    if not docs:
        return {"synced": False, "reason": "no documents to sync"}
    if remote.startswith("gitlab:"):
        repo_ref = remote.removeprefix("gitlab:")
        return {
            "synced": False,
            "reason": "reference-only: requires GitLab API credentials",
            "would_push_to": repo_ref,
            "files": [str(p.relative_to(repo_root)) for p in docs],
            "adapter": "gitlab",
        }
    if remote.startswith("dingtalk:"):
        space_id = remote.removeprefix("dingtalk:")
        return {
            "synced": False,
            "reason": "reference-only: requires DingTalk API credentials",
            "would_push_to": space_id,
            "files": [str(p.relative_to(repo_root)) for p in docs],
            "adapter": "dingtalk",
        }
    return {"synced": False, "reason": f"unknown remote_target: {remote}"}
