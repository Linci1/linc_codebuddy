#!/usr/bin/env python3
"""Run a quick validation suite for the linc_codebuddy skill."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from lib import run
from policy_loader import load_default_policy


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
ROUTES = ["new", "continue", "review", "hotfix", "ship"]


def required_files() -> list[Path]:
    files = [
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "agents/openai.yaml",
        SKILL_ROOT / "assets/default-policy.json",
        SKILL_ROOT / "assets/linc-codebuddy-small.svg",
        SKILL_ROOT / "assets/linc-codebuddy-large.svg",
        SCRIPT_DIR / "run_agent.py",
        SCRIPT_DIR / "quick_validate.py",
    ]
    files.extend(SKILL_ROOT.glob("assets/work-item-templates/*.md"))
    return files


def validate_files() -> dict[str, Any]:
    missing = [str(path) for path in required_files() if not path.exists()]
    return {"ok": not missing, "missing": missing}


def validate_icons() -> dict[str, Any]:
    icons = [
        SKILL_ROOT / "assets/linc-codebuddy-small.svg",
        SKILL_ROOT / "assets/linc-codebuddy-large.svg",
    ]
    parsed: list[str] = []
    for icon in icons:
        ET.parse(icon)
        parsed.append(str(icon))
    return {"ok": True, "parsed": parsed}


def validate_openai_yaml() -> dict[str, Any]:
    content = (SKILL_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
    required_keys = ["display_name", "short_description", "icon_small", "icon_large", "brand_color", "default_prompt"]
    missing = [key for key in required_keys if key not in content]
    return {"ok": not missing, "missing_keys": missing}


def validate_policy() -> dict[str, Any]:
    policy = load_default_policy()
    required_top_level = ["branch_prefix", "default_mode", "route_defaults", "patrol_presets", "work_item"]
    missing = [key for key in required_top_level if key not in policy]
    missing_routes = [route for route in ROUTES if route not in policy.get("route_defaults", {})]
    missing_presets = [preset for preset in ["morning", "end-of-day", "pre-ship", "resume"] if preset not in policy.get("patrol_presets", {})]
    return {
        "ok": not missing and not missing_routes and not missing_presets,
        "missing_keys": missing,
        "missing_routes": missing_routes,
        "missing_presets": missing_presets,
    }


def validate_py_compile() -> dict[str, Any]:
    scripts = sorted(str(path) for path in SCRIPT_DIR.glob("*.py"))
    result = run(["python3", "-B", "-m", "py_compile", *scripts], SKILL_ROOT)
    return {"ok": result.returncode == 0, "stderr": result.stderr.strip(), "scripts": scripts}


def validate_routes_and_agent_entry() -> dict[str, Any]:
    tmpdir = Path(tempfile.mkdtemp(prefix="linc-codebuddy-validate."))
    details: dict[str, Any] = {"repo_root": str(tmpdir)}
    try:
        run(["git", "init", "-q"], tmpdir)
        (tmpdir / "package.json").write_text(
            json.dumps({"name": "demo-app", "scripts": {"lint": "echo lint", "test": "echo test"}}, indent=2) + "\n",
            encoding="utf-8",
        )
        (tmpdir / "src").mkdir()
        (tmpdir / "src/app.ts").write_text("export const value = 1;\n", encoding="utf-8")
        run(["git", "add", "package.json", "src/app.ts"], tmpdir)
        run(["git", "commit", "-qm", "init"], tmpdir)
        (tmpdir / "src/app.ts").write_text("export const value = 2;\n", encoding="utf-8")

        route_outputs: dict[str, str] = {}
        for route in ROUTES:
            result = run(
                ["python3", "-B", str(SCRIPT_DIR / "create_work_item.py"), f"{route} validate", "--repo", str(tmpdir), "--route", route],
                tmpdir,
            )
            if result.returncode != 0:
                return {"ok": False, "error": result.stderr.strip(), "details": details}
            work_item = Path(result.stdout.strip())
            route_outputs[route] = work_item.read_text(encoding="utf-8").splitlines()[0]

        policy_init = run(["python3", "-B", str(SCRIPT_DIR / "run_agent.py"), "--repo", str(tmpdir), "--json", "policy-init"], tmpdir)
        kickoff = run(
            ["python3", "-B", str(SCRIPT_DIR / "run_agent.py"), "--repo", str(tmpdir), "--json", "kickoff", "Validate kickoff", "--route", "continue"],
            tmpdir,
        )
        patrol = run(
            ["python3", "-B", str(SCRIPT_DIR / "run_agent.py"), "--repo", str(tmpdir), "--json", "patrol", "--preset", "morning"],
            tmpdir,
        )
        ship = run(
            ["python3", "-B", str(SCRIPT_DIR / "run_agent.py"), "--repo", str(tmpdir), "--json", "ship", "--title", "Validate ship"],
            tmpdir,
        )
        intake = run(["python3", "-B", str(SCRIPT_DIR / "run_agent.py"), "--repo", str(tmpdir), "--json", "intake"], tmpdir)

        ok = all(result.returncode == 0 for result in [policy_init, kickoff, patrol, ship, intake])
        if not ok:
            return {
                "ok": False,
                "details": {
                    "policy_init": policy_init.stderr.strip(),
                    "kickoff": kickoff.stderr.strip(),
                    "patrol": patrol.stderr.strip(),
                    "ship": ship.stderr.strip(),
                    "intake": intake.stderr.strip(),
                },
            }

        return {
            "ok": True,
            "details": {
                "route_outputs": route_outputs,
                "policy_init": json.loads(policy_init.stdout),
                "kickoff": json.loads(kickoff.stdout),
                "patrol": json.loads(patrol.stdout),
                "ship": json.loads(ship.stdout),
                "intake": json.loads(intake.stdout),
            },
        }
    finally:
        shutil.rmtree(tmpdir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    checks = {
        "files": validate_files(),
        "icons": validate_icons(),
        "openai_yaml": validate_openai_yaml(),
        "policy": validate_policy(),
        "py_compile": validate_py_compile(),
        "agent_flow": validate_routes_and_agent_entry(),
    }
    success = all(item.get("ok") for item in checks.values())
    payload = {"ok": success, "checks": checks}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ok: {payload['ok']}")
        for name, result in checks.items():
            print(f"{name}: {'ok' if result.get('ok') else 'fail'}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
