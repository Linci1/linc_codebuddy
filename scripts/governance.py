#!/usr/bin/env python3
"""Adaptive governance classification for CodeBuddy V2.1."""

from __future__ import annotations

from typing import Any


LEVELS = ["L0", "L1", "L2", "L3"]
DIMENSIONS = [
    "requirement_uncertainty",
    "change_scope",
    "data_impact",
    "security_auth_impact",
    "production_impact",
    "rollback_difficulty",
]

DEFAULT_POLICY: dict[str, Any] = {
    "score_thresholds": {"L0": 1, "L1": 5, "L2": 11, "L3": 18},
    "hard_minimums": {
        "L2": [
            "oidc", "oauth", "认证", "登录流程", "登录逻辑", "账号校验", "授权", "权限", "访问控制",
            "敏感数据", "隐私", "密钥", "token", "secret", "证书",
            "数据库迁移", "数据迁移", "删除数据", "生产", "部署", "回滚",
            "public api", "对外 api", "兼容性",
        ],
        "L3": ["从零开发", "新项目", "整体架构", "多系统", "多个里程碑", "平台重构"],
    },
    "lightweight_signals": [
        "文案", "错别字", "拼写", "按钮文字", "提示语", "颜色", "间距", "注释",
    ],
    "standard_signals": ["bug", "修复", "异常", "报错", "小功能", "局部", "回归"],
    "artifacts": {
        "L0": ["state_record", "verification_result"],
        "L1": ["work_item", "acceptance", "verification_result"],
        "L2": ["work_item", "requirements", "design", "verification", "rollback"],
        "L3": ["project_brief", "requirements", "architecture", "roadmap", "verification"],
    },
    "flows": {
        "L0": ["locate", "change", "minimal_verify"],
        "L1": ["brief", "implement", "targeted_test", "review"],
        "L2": ["requirements", "design", "tasks", "implement", "full_verify"],
        "L3": ["explore", "specify", "architecture", "roadmap", "incremental_delivery"],
    },
}


def level_rank(level: str) -> int:
    if level not in LEVELS:
        raise ValueError(f"unknown governance level: {level}")
    return LEVELS.index(level)


def max_level(first: str, second: str) -> str:
    return first if level_rank(first) >= level_rank(second) else second


def _policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    configured = (policy or {}).get("adaptive_governance", {})
    merged = dict(DEFAULT_POLICY)
    for key, value in configured.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _score_level(score: int, thresholds: dict[str, int]) -> str:
    selected = "L0"
    for level in LEVELS:
        if score >= int(thresholds.get(level, 0)):
            selected = level
    return selected


def classify(
    text: str,
    dimensions: dict[str, int] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = _policy(policy)
    normalized = text.strip().lower()
    values = {name: max(0, min(3, int((dimensions or {}).get(name, 0)))) for name in DIMENSIONS}
    reasons: list[str] = []
    hard_signals: list[dict[str, str]] = []

    for minimum in ["L2", "L3"]:
        for keyword in rules.get("hard_minimums", {}).get(minimum, []):
            if keyword.lower() in normalized:
                hard_signals.append({"keyword": keyword, "minimum_level": minimum})

    score = sum(values.values())
    level = _score_level(score, rules["score_thresholds"])

    lightweight = [item for item in rules.get("lightweight_signals", []) if item.lower() in normalized]
    standard = [item for item in rules.get("standard_signals", []) if item.lower() in normalized]
    if lightweight and not hard_signals and score <= int(rules["score_thresholds"]["L0"]):
        level = "L0"
        reasons.append(f"lightweight signal: {lightweight[0]}")
    elif standard and level == "L0":
        level = "L1"
        reasons.append(f"standard change signal: {standard[0]}")
    elif not normalized and level == "L0":
        level = "L1"
        reasons.append("empty task description defaults to standard governance")
    elif level != "L0":
        reasons.append(f"dimension score {score} maps to {level}")

    for signal in hard_signals:
        level = max_level(level, signal["minimum_level"])
    if hard_signals:
        reasons.extend(
            f"hard signal '{item['keyword']}' requires at least {item['minimum_level']}"
            for item in hard_signals
        )

    confidence = 0.95 if hard_signals else (0.9 if lightweight or standard else 0.65)
    return {
        "level": level,
        "confidence": confidence,
        "score": score,
        "dimensions": values,
        "hard_signals": hard_signals,
        "reasons": reasons or ["low-risk task with no elevated signals"],
        "required_artifacts": rules["artifacts"][level],
        "flow": rules["flows"][level],
        "create_work_item": level != "L0",
    }


def resolve_level_change(
    current_level: str | None,
    classification: dict[str, Any],
    requested_level: str | None = None,
    approve_downgrade: bool = False,
    downgrade_reason: str | None = None,
) -> dict[str, Any]:
    classified = classification["level"]
    baseline = max_level(current_level, classified) if current_level else classified
    selected = requested_level or baseline
    requested_downgrade = level_rank(selected) < level_rank(baseline)

    if requested_downgrade and (not approve_downgrade or not downgrade_reason):
        raise ValueError("governance downgrade requires explicit approval and a reason")

    hard_minimum = "L0"
    for signal in classification.get("hard_signals", []):
        hard_minimum = max_level(hard_minimum, signal["minimum_level"])
    if level_rank(selected) < level_rank(hard_minimum):
        raise ValueError(f"requested level {selected} violates hard minimum {hard_minimum}")

    return {
        "previous_level": current_level,
        "classified_level": classified,
        "level": selected,
        "upgraded": bool(current_level and level_rank(selected) > level_rank(current_level)),
        "downgraded": requested_downgrade,
        "downgrade_reason": downgrade_reason if requested_downgrade else None,
    }
