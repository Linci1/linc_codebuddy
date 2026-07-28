from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from agent_state import SCHEMA_VERSION, load_state  # noqa: E402
from governance import classify, resolve_level_change  # noqa: E402
from identity import extract_id  # noqa: E402
from lifecycle import (  # noqa: E402
    create_change,
    evaluate_gate,
    find_change,
    init_project,
    load_active_change,
    transition_change,
    update_change,
)
from quality import detect_drift, record_evidence, verification_summary, write_verification_report  # noqa: E402
from gitlab_sync import apply_sync, plan_sync, write_external_action  # noqa: E402
from workspace import summarize_repos  # noqa: E402
from pilot import evaluate_pilot, record_observation  # noqa: E402
from run_agent import command_classify, command_kickoff, command_next, command_ship  # noqa: E402
from sync_tasks import add_task  # noqa: E402


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


class TempRepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="lcb-v2-test.")
        self.repo = Path(self.temp.name)
        self.assertEqual(git(self.repo, "init", "-q").returncode, 0)
        git(self.repo, "config", "user.name", "CodeBuddy Test")
        git(self.repo, "config", "user.email", "codebuddy@example.invalid")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def commit_file(self, name: str = "app.txt", content: str = "baseline\n") -> None:
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(content, encoding="utf-8")
        self.assertEqual(git(self.repo, "add", name).returncode, 0)
        self.assertEqual(git(self.repo, "commit", "-qm", "baseline").returncode, 0)


class StateMigrationTests(TempRepoTestCase):
    def test_v1_state_is_backed_up_and_migrated(self) -> None:
        state_dir = self.repo / ".codex" / "linc_codebuddy"
        state_dir.mkdir(parents=True)
        state_path = state_dir / "state.json"
        state_path.write_text(
            json.dumps({"repo_root": "/old/path", "last_route": "continue"}),
            encoding="utf-8",
        )

        path, state = load_state(self.repo)

        self.assertEqual(path, state_path)
        self.assertEqual(state["schema_version"], SCHEMA_VERSION)
        self.assertEqual(state["repo_root"], str(self.repo))
        self.assertEqual(state["active"]["task_id"], None)
        self.assertTrue(state_path.with_suffix(".v1.bak").exists())
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["schema_version"], SCHEMA_VERSION)

    def test_incomplete_current_schema_state_is_normalized_on_disk(self) -> None:
        state_dir = self.repo / ".codex" / "linc_codebuddy"
        state_dir.mkdir(parents=True)
        state_path = state_dir / "state.json"
        state_path.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "active": {}}), encoding="utf-8")

        load_state(self.repo)

        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIn("change_id", persisted["active"])
        self.assertIn("phase", persisted["active"])
        self.assertIn("level", persisted["active"])
        self.assertIn("classification_history", persisted)

    def test_non_object_json_state_is_recovered(self) -> None:
        state_dir = self.repo / ".codex" / "linc_codebuddy"
        state_dir.mkdir(parents=True)
        state_path = state_dir / "state.json"
        state_path.write_text("[]", encoding="utf-8")

        _, state = load_state(self.repo)

        self.assertEqual(state["schema_version"], SCHEMA_VERSION)
        self.assertEqual(state["repo_root"], str(self.repo))
        self.assertIsInstance(json.loads(state_path.read_text(encoding="utf-8")), dict)


class GovernanceClassificationTests(unittest.TestCase):
    def test_copy_change_is_l0(self) -> None:
        result = classify("修改登录按钮文案")
        self.assertEqual(result["level"], "L0")
        self.assertFalse(result["create_work_item"])

    def test_clear_bug_fix_is_l1(self) -> None:
        result = classify("修复列表页空值报错 bug")
        self.assertEqual(result["level"], "L1")
        self.assertTrue(result["create_work_item"])

    def test_oidc_and_permissions_are_at_least_l2(self) -> None:
        result = classify("调整 OIDC 登录和公司访问权限")
        self.assertEqual(result["level"], "L2")
        self.assertTrue(result["hard_signals"])

    def test_new_project_is_l3(self) -> None:
        result = classify("从零开发一个新的工程治理平台")
        self.assertEqual(result["level"], "L3")

    def test_runtime_discovery_upgrades_l0_to_l2(self) -> None:
        initial = classify("修改按钮文案")
        discovered = classify("发现这个按钮会改变 OAuth 授权行为")
        change = resolve_level_change(initial["level"], discovered)
        self.assertEqual(change["level"], "L2")
        self.assertTrue(change["upgraded"])

    def test_high_risk_level_cannot_be_downgraded(self) -> None:
        result = classify("修改生产 OIDC 登录权限")
        with self.assertRaises(ValueError):
            resolve_level_change(
                "L2",
                result,
                requested_level="L1",
                approve_downgrade=True,
                downgrade_reason="赶时间",
            )

    def test_low_risk_downgrade_requires_approval_and_reason(self) -> None:
        result = classify(
            "局部功能调整",
            {"requirement_uncertainty": 2, "change_scope": 2, "rollback_difficulty": 1},
        )
        self.assertEqual(result["level"], "L1")
        with self.assertRaises(ValueError):
            resolve_level_change("L2", result, requested_level="L1")
        change = resolve_level_change(
            "L2",
            result,
            requested_level="L1",
            approve_downgrade=True,
            downgrade_reason="scope was validated as local and reversible",
        )
        self.assertTrue(change["downgraded"])


class AdaptiveKickoffTests(TempRepoTestCase):
    def test_l0_kickoff_skips_worklog_but_keeps_task_and_state(self) -> None:
        self.commit_file()
        result = command_kickoff(self.repo, "修改按钮文案", "new", None)

        self.assertEqual(result["level"], "L0")
        self.assertIsNone(result["work_item"])
        self.assertIsNotNone(result["task_id"])
        self.assertFalse((self.repo / ".codex" / "worklogs").exists())
        state = json.loads((self.repo / ".codex" / "linc_codebuddy" / "state.json").read_text())
        self.assertEqual(state["active"]["level"], "L0")

    def test_l2_kickoff_creates_full_work_item(self) -> None:
        self.commit_file()
        result = command_kickoff(self.repo, "调整 OIDC 登录权限", "new", None)

        self.assertEqual(result["level"], "L2")
        self.assertTrue(Path(result["work_item"]).exists())
        self.assertIn("requirements", result["required_artifacts"])

    def test_completed_high_risk_task_does_not_raise_new_l0_task(self) -> None:
        self.commit_file()
        high = command_kickoff(self.repo, "调整 OIDC 登录权限", "new", None)
        subprocess.run(
            [sys.executable, str(SCRIPTS / "sync_tasks.py"), "--repo", str(self.repo), "done", high["task_id"]],
            check=True,
            capture_output=True,
            text=True,
        )

        low = command_kickoff(self.repo, "修改按钮文案", "new", None)

        self.assertEqual(low["level"], "L0")

    def test_active_l0_task_is_persistently_upgraded_when_risk_is_discovered(self) -> None:
        self.commit_file()
        command_kickoff(self.repo, "修改按钮文案", "new", None)

        result = command_classify(
            self.repo,
            "发现这个入口会改变 OAuth 授权行为",
            persist=True,
        )

        self.assertEqual(result["level"], "L2")
        self.assertTrue(result["level_change"]["upgraded"])
        state = json.loads((self.repo / ".codex" / "linc_codebuddy" / "state.json").read_text())
        self.assertEqual(state["active"]["level"], "L2")
        latest = state["classification_history"][-1]
        self.assertEqual(latest["previous_level"], "L0")
        self.assertEqual(latest["level"], "L2")


class LifecycleFoundationTests(TempRepoTestCase):
    def test_project_and_active_change_are_restored_from_repo(self) -> None:
        project = init_project(self.repo, "Demo Platform")
        change = create_change(self.repo, "Fix list rendering", "L1", problem="Empty values crash the list")

        restored, path = load_active_change(self.repo)

        self.assertEqual(project["id"], "PRJ-demo-platform")
        self.assertEqual(restored["id"], change["id"])
        self.assertEqual(restored["phase"], "specify")
        self.assertTrue(path.exists())
        state = json.loads((self.repo / ".codex" / "linc_codebuddy" / "state.json").read_text())
        self.assertEqual(state["active"]["level"], "L1")

    def test_l1_can_enter_implement_without_empty_design_files(self) -> None:
        init_project(self.repo, "Demo")
        change = create_change(
            self.repo,
            "Fix list rendering",
            "L1",
            problem="Empty values crash the list",
            outcome="List renders empty values safely",
            acceptance=["Empty values no longer crash the page"],
        )

        result = transition_change(self.repo, change["id"], "implement", actor="test")

        self.assertEqual(result["change"]["phase"], "implement")
        change_dir = Path(result["change_file"]).parent
        self.assertFalse((change_dir / "design.md").exists())
        self.assertFalse((change_dir / "tasks.yaml").exists())

    def test_l2_missing_acceptance_cannot_enter_implement(self) -> None:
        init_project(self.repo, "Demo")
        change = create_change(
            self.repo,
            "Adjust OIDC permissions",
            "L2",
            problem="Claims are not mapped",
            outcome="Claims are persisted",
        )

        result = transition_change(self.repo, change["id"], "implement", actor="test")

        self.assertFalse(result["transitioned"])
        self.assertEqual(result["gate"]["missing"][0]["code"], "ACCEPTANCE_MISSING")
        self.assertEqual(result["gate"]["next_action"], "add at least one acceptance scenario")

    def test_verify_can_return_to_implement(self) -> None:
        init_project(self.repo, "Demo")
        change = create_change(
            self.repo,
            "Fix list rendering",
            "L1",
            problem="Empty values crash",
            outcome="No crash",
            acceptance=["Empty value renders"],
        )
        transition_change(self.repo, change["id"], "implement", actor="test")
        update_change(self.repo, change["id"], tasks=[{"title": "Implement fix", "status": "done"}])
        transition_change(self.repo, change["id"], "verify", actor="test")

        result = transition_change(
            self.repo, change["id"], "implement", actor="test", reason="verification failed"
        )

        self.assertTrue(result["transitioned"])
        self.assertEqual(result["change"]["phase"], "implement")
        state = json.loads((self.repo / ".codex" / "linc_codebuddy" / "state.json").read_text())
        self.assertEqual(state["active"]["next_action"], "complete the active implementation tasks")

    def test_illegal_transition_is_rejected(self) -> None:
        init_project(self.repo, "Demo")
        change = create_change(self.repo, "Small fix", "L1", problem="Bug", outcome="Fixed")
        with self.assertRaises(ValueError):
            transition_change(self.repo, change["id"], "operate", actor="test")

    def test_protected_gate_cannot_be_bypassed_by_normal_override(self) -> None:
        init_project(self.repo, "Demo")
        change = create_change(
            self.repo,
            "Production permission rollout",
            "L2",
            problem="Access rules need rollout",
            outcome="Rules are live",
            acceptance=["Authorized users retain access"],
            risks=["production", "permission"],
        )
        update_change(self.repo, change["id"], phase="verify")

        gate = evaluate_gate(
            self.repo,
            change,
            "release",
            override=True,
            actor="test",
            reason="ship quickly",
        )

        self.assertFalse(gate["allowed"])
        self.assertTrue(gate["requires_approval"])
        self.assertIn("PROTECTED_APPROVAL_REQUIRED", [item["code"] for item in gate["missing"]])


class QualityClosureTests(TempRepoTestCase):
    def make_change(self):
        self.commit_file("src/app.txt")
        init_project(self.repo, "Demo")
        return create_change(
            self.repo, "Validated fix", "L2", problem="bug", outcome="fixed",
            acceptance=["valid input succeeds"],
        )

    def test_suggested_check_is_not_executed_evidence(self) -> None:
        change = self.make_change()
        update_change(self.repo, change["id"], suggested_checks=["pytest"])
        summary = verification_summary(self.repo, change["id"])
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["evidence_count"], 0)

    def test_acceptance_requires_passing_evidence(self) -> None:
        change = self.make_change()
        record_evidence(
            self.repo, change["id"], "command", "pytest passed", status="passed",
            acceptance_ids=["ACC-001"], command="pytest", exit_code=0,
        )
        summary = verification_summary(self.repo, change["id"])
        self.assertTrue(summary["passed"])
        self.assertTrue(summary["release_ready"])
        _, report = write_verification_report(self.repo, change["id"])
        self.assertIn("| ACC-001 | valid input succeeds | passed | EVD-001 |", report.read_text())

    def test_review_finding_blocks_release(self) -> None:
        change = self.make_change()
        record_evidence(self.repo, change["id"], "command", "ok", status="passed", acceptance_ids=["ACC-001"])
        record_evidence(self.repo, change["id"], "review", "authorization bypass", status="failed", severity="high")
        summary = verification_summary(self.repo, change["id"])
        self.assertFalse(summary["release_ready"])
        self.assertEqual(summary["blocking_findings"][0]["severity"], "high")

    def test_evidence_redacts_secrets_and_truncates_output(self) -> None:
        change = self.make_change()
        evidence = record_evidence(
            self.repo, change["id"], "command", "token=super-secret " + "x" * 3000,
            status="passed",
        )
        self.assertNotIn("super-secret", evidence["summary"])
        self.assertLessEqual(len(evidence["summary"]), 2000)

    def test_out_of_scope_file_is_reported(self) -> None:
        change = self.make_change()
        update_change(self.repo, change["id"], in_scope=["src/"])
        (self.repo / "outside.txt").write_text("changed\n", encoding="utf-8")
        drift = detect_drift(self.repo, change["id"])
        self.assertIn("OUT_OF_SCOPE_FILE", [item["code"] for item in drift["findings"]])

    def test_old_evidence_is_stale_after_acceptance_update(self) -> None:
        change = self.make_change()
        record_evidence(self.repo, change["id"], "manual", "confirmed", status="passed", acceptance_ids=["ACC-001"])
        update_change(self.repo, change["id"], acceptance=[{"id": "ACC-001", "scenario": "updated behavior"}])
        summary = verification_summary(self.repo, change["id"])
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["acceptance"][0]["status"], "stale")

    def test_old_evidence_is_stale_after_requirement_update(self) -> None:
        change = self.make_change()
        update_change(self.repo, change["id"], requirements=[{"id": "REQ-001", "statement": "persist company"}])
        record_evidence(
            self.repo, change["id"], "manual", "confirmed", status="passed",
            acceptance_ids=["ACC-001"], requirement_ids=["REQ-001"],
        )
        update_change(self.repo, change["id"], requirements=[{"id": "REQ-001", "statement": "persist and validate company"}])
        summary = verification_summary(self.repo, change["id"])
        drift = detect_drift(self.repo, change["id"])
        self.assertEqual(summary["requirements"][0]["status"], "stale")
        self.assertIn("STALE_REQUIREMENT_EVIDENCE", [item["code"] for item in drift["findings"]])

    def test_evidence_cli_command_option_does_not_replace_subcommand(self) -> None:
        change = self.make_change()
        result = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "run_agent.py"), "--repo", str(self.repo), "--json",
                "evidence", "record", "--change-id", change["id"], "--type", "command",
                "--status", "passed", "--summary", "ok", "--acceptance-id", "ACC-001",
                "--command", "pytest", "--exit-code", "0",
            ], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["evidence"]["command"], "pytest")


class GitLabSyncTests(TempRepoTestCase):
    def make_change(self):
        self.commit_file()
        init_project(self.repo, "Demo")
        return create_change(
            self.repo, "GitLab linked fix", "L2", problem="bug", outcome="fixed",
            acceptance=["behavior passes"],
        )

    def snapshot(self, change_id: str, updated_at: str = "2026-07-28T10:00:00Z"):
        return {
            "project": {"id": 400, "web_url": "https://gitlab.example/group/demo"},
            "issue": {"id": 99, "iid": 7, "title": f"[{change_id}] GitLab linked fix", "state": "opened", "updated_at": updated_at, "web_url": "https://gitlab.example/group/demo/-/issues/7"},
            "milestone": {"id": 12, "title": "v2.4", "state": "active", "updated_at": updated_at},
            "merge_request": {"id": 50, "iid": 3, "state": "opened", "updated_at": updated_at, "web_url": "https://gitlab.example/group/demo/-/merge_requests/3"},
            "pipeline": {"id": 80, "status": "success", "updated_at": updated_at, "web_url": "https://gitlab.example/group/demo/-/pipelines/80"},
            "task_issues": {"TASK-001": {"id": 101, "iid": 8, "title": "Implement", "state": "opened", "updated_at": updated_at, "web_url": "https://gitlab.example/group/demo/-/issues/8"}},
        }

    def test_read_only_sync_is_dry_run_then_idempotent(self) -> None:
        change = self.make_change()
        snapshot = self.snapshot(change["id"])
        snapshot["issue"]["description"] = "must not be copied"
        snapshot["issue"]["author"] = {"email": "private@example.invalid"}
        planned = plan_sync(self.repo, change["id"], snapshot)
        self.assertEqual(planned["status"], "planned")
        self.assertFalse(planned["mutated"])
        self.assertNotIn("external", find_change(self.repo, change["id"])[0])
        applied = apply_sync(self.repo, planned)
        self.assertTrue(applied["mutated"])
        self.assertNotIn("description", applied["snapshot"]["issue"])
        self.assertNotIn("author", applied["snapshot"]["issue"])
        self.assertEqual(applied["snapshot"]["task_issues"]["TASK-001"]["iid"], 8)
        repeated = plan_sync(self.repo, change["id"], self.snapshot(change["id"]))
        self.assertEqual(repeated["status"], "noop")

    def test_sync_detects_issue_binding_conflict(self) -> None:
        change = self.make_change()
        first = plan_sync(self.repo, change["id"], self.snapshot(change["id"]))
        apply_sync(self.repo, first)
        conflicting = self.snapshot(change["id"], "2026-07-28T11:00:00Z")
        conflicting["issue"]["id"] = 100
        result = plan_sync(self.repo, change["id"], conflicting)
        self.assertEqual(result["status"], "conflict")
        self.assertFalse(result["can_apply"])

    def test_stale_sync_plan_cannot_overwrite_newer_binding(self) -> None:
        change = self.make_change()
        stale_plan = plan_sync(self.repo, change["id"], self.snapshot(change["id"]))
        newer = self.snapshot(change["id"], "2026-07-28T11:00:00Z")
        newer["issue"]["id"] = 100
        apply_sync(self.repo, plan_sync(self.repo, change["id"], newer))

        with self.assertRaisesRegex(ValueError, "stale"):
            apply_sync(self.repo, stale_plan)

    def test_external_write_requires_execute_and_approval(self) -> None:
        change = self.make_change()
        preview = write_external_action(self.repo, change["id"], "create_issue", {"title": "x"})
        self.assertEqual(preview["status"], "dry_run")
        with self.assertRaises(ValueError):
            write_external_action(self.repo, change["id"], "create_issue", {"title": "x"}, execute=True)
        approved = write_external_action(
            self.repo, change["id"], "create_issue", {"title": "x"}, execute=True,
            approval_ref="APR-001", actor="test", executor=lambda action, payload: {"id": 1, "action": action},
        )
        self.assertEqual(approved["status"], "executed")
        self.assertEqual(approved["approval_ref"], "APR-001")


class WorkspaceSummaryTests(TempRepoTestCase):
    def test_workspace_summary_includes_phase_blocking_and_next(self) -> None:
        self.commit_file()
        init_project(self.repo, "Demo")
        change = create_change(self.repo, "Fix", "L1", problem="bug", outcome="fixed", acceptance=["works"])
        _, state = load_state(self.repo)
        state["blocking"] = ["waiting for API sample"]
        state_path = self.repo / ".codex" / "linc_codebuddy" / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        rows = summarize_repos([{"alias": "demo", "path": str(self.repo)}])
        self.assertEqual(rows[0]["change_id"], change["id"])
        self.assertEqual(rows[0]["phase"], "specify")
        self.assertEqual(rows[0]["blocking"], ["waiting for API sample"])
        self.assertEqual(rows[0]["next_action"], "complete the change specification")

    def test_workspace_summary_uses_current_verification_next_action(self) -> None:
        self.commit_file()
        init_project(self.repo, "Demo")
        change = create_change(
            self.repo, "Fix", "L1", problem="bug", outcome="fixed", acceptance=["works"],
        )
        transition_change(self.repo, change["id"], "implement", actor="test")
        update_change(self.repo, change["id"], tasks=[{"title": "Implement", "status": "done"}])
        transition_change(self.repo, change["id"], "verify", actor="test")
        record_evidence(
            self.repo, change["id"], "command", "passed", status="passed", acceptance_ids=["ACC-001"],
        )

        rows = summarize_repos([{"alias": "demo", "path": str(self.repo)}])

        self.assertEqual(rows[0]["next_action"], "transition to release")


class PilotEvaluationTests(TempRepoTestCase):
    def test_lightweight_successful_pilot_recommends_no_v3(self) -> None:
        init_project(self.repo, "Demo")
        change = create_change(self.repo, "Pilot", "L1", problem="test", outcome="learn", acceptance=["works"])
        record_observation(self.repo, change["id"], "recovery", 1, "state restored")
        record_observation(self.repo, change["id"], "manual_context_rebuild_minutes", 0, "none")
        record_observation(self.repo, change["id"], "false_gate_blocks", 0, "none")
        record_observation(self.repo, change["id"], "artifact_minutes", 3, "one change file")
        record_observation(self.repo, change["id"], "long_task_resume_failures", 0, "none")
        record_observation(self.repo, change["id"], "parallelizable_blocked_work", 0, "none")
        result = evaluate_pilot(self.repo, change["id"])
        self.assertEqual(result["v3_decision"], "no-go")
        self.assertEqual(result["next_action"], "continue V2 usage on real projects")

    def test_repeated_resume_and_parallel_bottlenecks_can_trigger_v3_candidate(self) -> None:
        init_project(self.repo, "Demo")
        change = create_change(self.repo, "Pilot", "L2", problem="test", outcome="learn", acceptance=["works"])
        record_observation(self.repo, change["id"], "long_task_resume_failures", 3, "three interrupted runs")
        record_observation(self.repo, change["id"], "parallelizable_blocked_work", 2, "independent reviews waited")
        result = evaluate_pilot(self.repo, change["id"])
        self.assertEqual(result["v3_decision"], "candidate")
        self.assertIn("resume", result["reasons"][0])


class TaskIdentityTests(TempRepoTestCase):
    def test_tasks_receive_stable_unique_ids_and_close_by_id(self) -> None:
        task_file = self.repo / ".codex" / "TASKS.md"
        first = add_task(task_file, "Same title", "active", None)
        second = add_task(task_file, "Another title", "active", None)

        self.assertNotEqual(first, second)
        self.assertEqual(extract_id(first), first)
        subprocess.run(
            [sys.executable, str(SCRIPTS / "sync_tasks.py"), "--repo", str(self.repo), "done", first],
            check=True,
            capture_output=True,
            text=True,
        )
        content = task_file.read_text(encoding="utf-8")
        self.assertIn(f"- [x] [{first}]", content)
        self.assertIn(f"- [ ] [{second}]", content)


class NextDecisionTests(TempRepoTestCase):
    def test_multiple_active_tasks_require_selection(self) -> None:
        self.commit_file()
        task_file = self.repo / ".codex" / "TASKS.md"
        add_task(task_file, "First", "active", None)
        add_task(task_file, "Second", "active", None)

        result = command_next(self.repo)

        self.assertIsNone(result["task_id"])
        self.assertFalse(result["can_modify_code"])
        self.assertEqual(result["next_action"], "select one active task by ID")

    def test_release_ready_active_change_beats_generic_dirty_fallback(self) -> None:
        self.commit_file()
        init_project(self.repo, "Demo")
        change = create_change(self.repo, "Fix", "L1", problem="bug", outcome="fixed", acceptance=["works"])
        update_change(self.repo, change["id"], phase="verify")
        record_evidence(self.repo, change["id"], "command", "passed", status="passed", acceptance_ids=["ACC-001"])
        (self.repo / "app.txt").write_text("changed\n", encoding="utf-8")

        result = command_next(self.repo)

        self.assertEqual(result["next_action"], "transition to release")
        self.assertEqual(result["reason"], "active change verification is release ready")


class ShipSafetyTests(TempRepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.commit_file()
        self.task_file = self.repo / ".codex" / "TASKS.md"
        self.first = add_task(self.task_file, "First", "active", None)
        self.second = add_task(self.task_file, "Second", "active", None)
        (self.repo / "app.txt").write_text("changed\n", encoding="utf-8")

    def test_executable_ship_requires_task_id(self) -> None:
        result = command_ship(self.repo, "No task", execute=True)

        self.assertFalse(result["execution"]["completed"])
        self.assertIn("task_id is required", result["execution"]["steps"]["error"])
        content = self.task_file.read_text(encoding="utf-8")
        self.assertIn(f"- [ ] [{self.first}]", content)
        self.assertIn(f"- [ ] [{self.second}]", content)

    def test_ship_closes_only_the_selected_task(self) -> None:
        result = command_ship(self.repo, "Ship first", execute=True, task_id=self.first)

        self.assertTrue(result["execution"]["completed"], result["execution"])
        content = self.task_file.read_text(encoding="utf-8")
        self.assertIn(f"- [x] [{self.first}]", content)
        self.assertIn(f"- [ ] [{self.second}]", content)
        self.assertNotEqual(git(self.repo, "log", "-1", "--format=%H").stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
