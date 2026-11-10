"""Image reuse cannot hide changes to sources, build recipes or provenance."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import load_script

sources = load_script("image_sources")


class ImageSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.project = Path(temporary)
        self.git("init", "-q", "-b", "main")
        for path in (
            "backend/app.py",
            "frontend/app.tsx",
            "docs/index.md",
            ".github/workflows/docker-images.yml",
        ):
            self.write(path, "initial\n")
        self.base = self.commit("initial inputs")

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def write(self, path, content):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def test_only_changed_components_receive_new_image_revisions(self):
        self.write("frontend/app.tsx", "new frontend\n")
        frontend = self.commit("frontend")
        expected = dict.fromkeys(sources.INPUTS, self.base)
        expected["frontend"] = frontend
        self.assertEqual(sources.revisions(frontend, self.project), expected)
        self.write("docs/index.md", "new docs\n")
        docs = self.commit("docs")
        expected["docs"] = docs
        self.assertEqual(sources.revisions(docs, self.project), expected)
        self.write("backend/app.py", "new backend\n")
        backend = self.commit("backend")
        expected.update(
            dict.fromkeys(
                {"api", "tactic", "mqtt_proxy", "mqtt_radar", "db_sync"}, backend
            )
        )
        self.assertEqual(sources.revisions(backend, self.project), expected)

    def test_build_tool_and_workflow_changes_invalidate_every_component(self):
        for path in (
            ".github/workflows/docker-images.yml",
            "infra/scripts/image_sources.py",
            "infra/tests/rehearsal_releases.py",
        ):
            self.write(path, "changed recipe\n")
            revision = self.commit(path)
            self.assertEqual(
                sources.revisions(revision, self.project),
                dict.fromkeys(sources.INPUTS, revision),
            )

    def test_deletion_rename_and_merge_inputs_cannot_retain_an_old_revision(self):
        self.git("switch", "-qc", "feature")
        self.git("mv", "backend/app.py", "backend/renamed.py")
        self.commit("rename")
        self.git("switch", "-q", "main")
        self.write("frontend/app.tsx", "independent edit\n")
        self.commit("frontend")
        self.git("merge", "--no-ff", "-qm", "merge backend", "feature")
        merged = self.git("rev-parse", "HEAD")
        self.assertEqual(sources.source_revision("api", merged, self.project), merged)
        self.git("rm", "backend/renamed.py")
        deleted = self.commit("delete")
        self.assertEqual(sources.source_revision("api", deleted, self.project), deleted)

    def test_release_metadata_must_match_the_actual_input_history(self):
        self.write("frontend/app.tsx", "changed\n")
        revision = self.commit("frontend")
        release = {
            "application_revision": revision,
            "image_revisions": sources.revisions(revision, self.project),
        }
        self.assertEqual(
            sources.expected_revisions(release, self.project),
            release["image_revisions"],
        )
        for name, value in (
            ("api", revision),
            ("frontend", self.base),
            ("unknown", self.base),
        ):
            with self.subTest(name=name):
                changed = release | {
                    "image_revisions": release["image_revisions"] | {name: value}
                }
                with self.assertRaisesRegex(ValueError, "build inputs"):
                    sources.expected_revisions(changed, self.project)
        self.assertEqual(
            sources.expected_revisions({"application_revision": revision}),
            dict.fromkeys(sources.INPUTS, revision),
        )

    def test_missing_history_disables_reuse_and_invalid_revisions_fail(self):
        with patch.object(sources, "git", return_value="true"):
            self.assertEqual(
                sources.source_revision("api", self.base, self.project), self.base
            )
        with self.assertRaises(ValueError):
            sources.source_revision("api", "main", self.project)
