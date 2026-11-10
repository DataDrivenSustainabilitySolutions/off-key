"""Static release inheritance must never hide application or deployment changes."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import ROOT

scripts = ROOT.parent / ".github/scripts"
spec = importlib.util.spec_from_file_location(
    "static_ci_release", scripts / "static_release.py"
)
release = importlib.util.module_from_spec(spec)
previous_path = sys.path[:]
try:
    sys.path.insert(0, str(scripts))
    spec.loader.exec_module(release)
finally:
    sys.path[:] = previous_path


class StaticReleaseTests(unittest.TestCase):
    def setUp(self):
        self.sources = dict.fromkeys(release.image_sources.INPUTS, "a" * 40)
        self.previous = {
            "application_revision": "a" * 40,
            "image_revisions": self.sources.copy(),
            "images": {
                name: f"example/{name}@sha256:{'1' * 64}" for name in self.sources
            },
        }
        self.enterContext(
            patch.object(
                release.image_sources, "expected_revisions", return_value=self.sources
            )
        )

    def carry(self, paths, sources=None, docs=None):
        return release.carried_release(
            self.previous,
            "b" * 40,
            paths,
            sources if sources is not None else self.sources.copy(),
            docs,
        )

    def test_landing_carries_exact_digests_without_mutating_baseline(self):
        result = self.carry(["infra/stack/landing.html.j2"])
        self.assertEqual(result["images"], self.previous["images"])
        self.assertEqual(result["application_revision"], "b" * 40)
        self.assertEqual(self.previous["application_revision"], "a" * 40)

    def test_docs_require_a_checked_replacement_when_their_inputs_change(self):
        sources = self.sources | {"docs": "b" * 40}
        with self.assertRaisesRegex(ValueError, "Cannot reuse changed image: docs"):
            self.carry(["docs/index.md"], sources)
        docs = f"example/docs@sha256:{'2' * 64}"
        result = self.carry(["docs/index.md"], sources, docs)
        self.assertEqual(result["images"], self.previous["images"] | {"docs": docs})
        self.assertEqual(result["image_revisions"], sources)

    def test_every_other_changed_image_is_rejected(self):
        for name in self.sources.keys() - {"docs"}:
            with (
                self.subTest(image=name),
                self.assertRaisesRegex(ValueError, f"changed image: {name}"),
            ):
                self.carry(
                    ["docs/index.md"], self.sources | {name: "b" * 40}, "checked-docs"
                )

    def test_mixed_unknown_empty_and_nonruntime_changes_cannot_create_evidence(self):
        for paths in (
            [],
            ["README.md"],
            ["infra/stack/stack.yml.j2"],
            ["infra/stack/landing.html.j2", "backend/app.py"],
            ["docs/index.md", "dev/docs/Dockerfile"],
            ["docs/../backend/app.py"],
        ):
            with (
                self.subTest(paths=paths),
                self.assertRaisesRegex(ValueError, "Only static content"),
            ):
                self.carry(paths)

    def test_ci_and_image_source_classification_both_guard_reuse(self):
        # Even a mistaken allowlist extension must not permit changed app inputs.
        with (
            patch.object(release.ci_plan, "mode_for", return_value="landing"),
            self.assertRaisesRegex(ValueError, "changed image: api"),
        ):
            self.carry(["backend/app.py"], self.sources | {"api": "b" * 40})

    def run_main(
        self, *, docs=False, bad_archive=False, bad_registry=False, event="push"
    ):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        output = directory / "production-release.json"
        self.output = output
        sources = self.sources | ({"docs": "b" * 40} if docs else {})
        local_id = "sha256:" + "2" * 64

        def docker(*args):
            if args[:2] == ("image", "inspect"):
                return json.dumps(
                    [
                        {
                            "Id": local_id,
                            "Config": {
                                "Labels": {
                                    "org.opencontainers.image.revision": "wrong"
                                    if bad_archive
                                    else sources["docs"]
                                }
                            },
                        }
                    ]
                )
            if args[:3] == ("buildx", "imagetools", "inspect"):
                return json.dumps(
                    {"config": {"digest": "wrong" if bad_registry else local_id}}
                )
            return ""

        def pin(tag):
            name = tag.split(":")[0].split("/")[-1]
            return (
                f"example/docs@sha256:{'2' * 64}"
                if name == "docs" and docs
                else self.previous["images"][name]
            )

        command = ["static_release.py", "--output", str(output)]
        if docs:
            command += ["--docs-image", "off-key-docs:checked"]
        self.docker_calls = self.enterContext(
            patch.object(release, "docker", side_effect=docker)
        )
        with (
            patch.object(sys, "argv", command),
            patch.dict(
                os.environ,
                {
                    "GITHUB_EVENT_NAME": event,
                    "GITHUB_REF": "refs/heads/main",
                    "GITHUB_SHA": "b" * 40,
                    "GITHUB_REPOSITORY": "example/repository",
                    "GITHUB_OUTPUT": str(directory / "outputs"),
                },
            ),
            patch.object(release.ci_plan, "git", return_value="b" * 40),
            patch.object(release.ci_plan, "evidenced_base", return_value="a" * 40),
            patch.object(
                release.ci_plan,
                "changed_paths",
                return_value=["docs/index.md"]
                if docs
                else ["infra/stack/landing.html.j2"],
            ),
            patch.object(
                release.pin_release, "tested_release", return_value=self.previous
            ),
            patch.object(release.image_sources, "revisions", return_value=sources),
            patch.object(release.pin_release, "pin", side_effect=pin),
            patch.object(release.pin_release, "require_image_revision"),
        ):
            release.main()
        return json.loads(output.read_text())

    def test_main_retains_unchanged_digests_and_records_the_verified_ancestor(self):
        document = self.run_main()
        self.assertEqual(document["release"]["images"], self.previous["images"])
        self.assertEqual(document["static_base"], "a" * 40)
        self.assertFalse(
            any(call.args[0] == "push" for call in self.docker_calls.call_args_list)
        )

    def test_main_publishes_only_checked_docs_and_retains_other_digests(self):
        document = self.run_main(docs=True)
        self.assertEqual(
            document["release"]["images"],
            self.previous["images"] | {"docs": f"example/docs@sha256:{'2' * 64}"},
        )
        self.assertEqual(
            [
                call.args
                for call in self.docker_calls.call_args_list
                if call.args[0] == "push"
            ],
            [("push", "example/docs:sha-bbbbbbb")],
        )

    def test_wrong_archive_or_registry_image_never_produces_release_evidence(self):
        for flags, message in (
            ({"bad_archive": True}, "another source revision"),
            ({"bad_registry": True}, "differ from the checked image"),
        ):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, message):
                self.run_main(docs=True, **flags)
            self.assertFalse(self.output.exists())

    def test_pull_requests_cannot_publish_or_create_release_evidence(self):
        with self.assertRaisesRegex(ValueError, "only produced on main pushes"):
            self.run_main(event="pull_request")
        self.docker_calls.assert_not_called()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
