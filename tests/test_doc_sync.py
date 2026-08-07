from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lifecycle import init_project, create_change, transition_change, update_change  # noqa: E402
from quality import record_evidence  # noqa: E402
from doc_sync import (  # noqa: E402
    check_doc_config,
    generate_for_phase,
    generate_requirements_doc,
    generate_test_report,
    generate_release_note,
    get_doc_config,
    set_doc_config,
    sync_docs,
)


class DocSyncTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="lcb-doc-test.")
        self.repo = Path(self.temp.name)
        init_project(self.repo, "test-project")
        self.change = create_change(
            self.repo, "test change", "L1",
            problem="something is broken",
            outcome="it works",
            acceptance=["scenario one"],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()


class ConfigTests(DocSyncTestCase):
    def test_check_returns_prompt_when_unconfigured(self) -> None:
        status = check_doc_config(self.repo)
        self.assertFalse(status["configured"])
        self.assertIsNotNone(status["prompt"])

    def test_set_and_get_doc_config(self) -> None:
        config = set_doc_config(self.repo, local_path="custom/docs", remote_target="gitlab:400/myrepo")
        self.assertEqual(config["local_path"], "custom/docs")
        self.assertEqual(config["remote_target"], "gitlab:400/myrepo")
        loaded = get_doc_config(self.repo)
        self.assertEqual(loaded["local_path"], "custom/docs")

    def test_check_returns_configured_when_local_path_set(self) -> None:
        set_doc_config(self.repo, local_path="docs/changes")
        status = check_doc_config(self.repo)
        self.assertTrue(status["configured"])
        self.assertIsNone(status["prompt"])

    def test_partial_update_keeps_existing_fields(self) -> None:
        set_doc_config(self.repo, local_path="docs/x", remote_target="gitlab:400/r")
        set_doc_config(self.repo, local_path="docs/y")
        config = get_doc_config(self.repo)
        self.assertEqual(config["local_path"], "docs/y")
        self.assertEqual(config["remote_target"], "gitlab:400/r")


class DocumentGenerationTests(DocSyncTestCase):
    def setUp(self) -> None:
        super().setUp()
        set_doc_config(self.repo, local_path="docs/changes")

    def test_requirements_doc_generated_from_change(self) -> None:
        path = generate_requirements_doc(self.repo, self.change["id"])
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("需求文档", content)
        self.assertIn("something is broken", content)
        self.assertIn("scenario one", content)

    def test_test_report_generated_with_evidence(self) -> None:
        record_evidence(
            self.repo, self.change["id"], "command", "tests passed",
            status="passed", acceptance_ids=["ACC-001"],
            command="pytest", exit_code=0,
        )
        path = generate_test_report(self.repo, self.change["id"])
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("测试报告", content)
        self.assertIn("ACC-001", content)
        self.assertIn("pytest", content)

    def test_release_note_generated(self) -> None:
        transition_change(self.repo, self.change["id"], "implement", actor="test")
        update_change(self.repo, self.change["id"], tasks=[{"id": "TASK-001", "title": "impl", "status": "done"}])
        transition_change(self.repo, self.change["id"], "verify", actor="test")
        record_evidence(
            self.repo, self.change["id"], "command", "all pass",
            status="passed", acceptance_ids=["ACC-001"],
        )
        transition_change(self.repo, self.change["id"], "release", actor="test", reason="ready")
        path = generate_release_note(self.repo, self.change["id"])
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("Release Note", content)
        self.assertIn("something is broken", content)

    def test_generate_for_phase_requirements(self) -> None:
        paths = generate_for_phase(self.repo, self.change["id"], "implement")
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].name == "requirements.md")

    def test_generate_for_phase_verify(self) -> None:
        paths = generate_for_phase(self.repo, self.change["id"], "verify")
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].name == "test-report.md")

    def test_generate_for_phase_release(self) -> None:
        paths = generate_for_phase(self.repo, self.change["id"], "release")
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].name == "release-note.md")

    def test_generate_for_phase_no_match(self) -> None:
        paths = generate_for_phase(self.repo, self.change["id"], "explore")
        self.assertEqual(len(paths), 0)


class TransitionHookTests(DocSyncTestCase):
    def test_transition_generates_docs(self) -> None:
        set_doc_config(self.repo, local_path="docs/changes")
        result = transition_change(self.repo, self.change["id"], "implement", actor="test")
        self.assertTrue(result["transitioned"])
        self.assertTrue(len(result["generated_docs"]) > 0)
        self.assertTrue(any("requirements.md" in d for d in result["generated_docs"]))

    def test_transition_works_without_doc_config(self) -> None:
        result = transition_change(self.repo, self.change["id"], "implement", actor="test")
        self.assertTrue(result["transitioned"])
        self.assertEqual(result["generated_docs"], [])


class SyncTests(DocSyncTestCase):
    def test_sync_no_remote_returns_not_synced(self) -> None:
        set_doc_config(self.repo, local_path="docs/changes")
        generate_for_phase(self.repo, self.change["id"], "implement")
        result = sync_docs(self.repo, self.change["id"])
        self.assertFalse(result["synced"])

    def test_sync_gitlab_returns_reference(self) -> None:
        set_doc_config(self.repo, local_path="docs/changes", remote_target="gitlab:400/myrepo")
        generate_for_phase(self.repo, self.change["id"], "implement")
        result = sync_docs(self.repo, self.change["id"])
        self.assertFalse(result["synced"])
        self.assertEqual(result["adapter"], "gitlab")
        self.assertEqual(result["would_push_to"], "400/myrepo")
        self.assertTrue(len(result["files"]) > 0)

    def test_sync_dingtalk_returns_reference(self) -> None:
        set_doc_config(self.repo, local_path="docs/changes", remote_target="dingtalk:space123")
        generate_for_phase(self.repo, self.change["id"], "implement")
        result = sync_docs(self.repo, self.change["id"])
        self.assertFalse(result["synced"])
        self.assertEqual(result["adapter"], "dingtalk")


if __name__ == "__main__":
    unittest.main()
