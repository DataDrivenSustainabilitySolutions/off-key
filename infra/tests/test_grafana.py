"""Guard the source → JSON → deployment contract, including nested rows."""

import re
import unittest

import yaml
from grafana_queries import panels
from support import ROOT, load_script, run

builder = load_script("build_grafana_dashboards")
runtime = load_script("observability_runtime")


class GrafanaTests(unittest.TestCase):
    def test_running_service_with_stale_or_missing_dashboard_is_rejected(self):
        model = {"configs": {"overview": {"name": "overview_current"}}}
        wanted = {
            "configs": [
                {
                    "source": "overview",
                    "target": "/etc/grafana/dashboards/overview.json",
                }
            ]
        }
        mounted = {
            "ConfigName": "overview_current",
            "File": {"Name": "/etc/grafana/dashboards/overview.json"},
        }
        runtime.verify_config_mounts(
            {"ContainerSpec": {"Configs": [mounted]}}, wanted, model
        )
        for mounts in (
            [],
            [mounted | {"ConfigName": "overview_stale"}],
            [mounted | {"File": {"Name": "/wrong.json"}}],
        ):
            with self.subTest(mounts=mounts), self.assertRaises(ValueError):
                runtime.verify_config_mounts(
                    {"ContainerSpec": {"Configs": mounts}}, wanted, model
                )

    def test_generated_json_matches_reviewed_sources(self):
        run("python3", str(ROOT / "scripts/build_grafana_dashboards.py"), "--check")

    def test_every_dashboard_is_copied_hashed_and_mounted(self):
        sources = set((ROOT / "stack").glob("grafana-dashboard-*.json"))
        config = yaml.safe_load(
            (ROOT / "stack/docker-compose.observability.yml").read_text()
        )
        role = yaml.safe_load(
            (ROOT / "ansible/roles/observability/defaults/main.yml").read_text()
        )
        mounts = {
            item["source"]: item["target"]
            for item in config["services"]["grafana"]["configs"]
        }
        for source in sources:
            self.assertIn(source.name, role["observability_files"])
            key = "grafana_dashboard_" + source.stem.removeprefix("grafana-dashboard-")
            entry = config["configs"][key]
            self.assertEqual(entry["file"], "./" + source.name)
            hash_key = re.search(r"\$\{([^}]+)\}", entry["name"])[1]
            self.assertEqual(role["observability_config_keys"][hash_key], source.name)
            self.assertTrue(mounts[key].startswith("/etc/grafana/dashboards/"))
        self.assertEqual(len(sources), len(builder.documents()))

    def test_navigation_variables_and_panel_identity_are_valid(self):
        docs = builder.documents()
        uids = {d["uid"] for d in docs.values()}
        self.assertEqual(len(uids), len(docs))
        self.assertTrue({"aberration-logs", "aberration-system-overview"} <= uids)
        for document in docs.values():
            with self.subTest(dashboard=document["uid"]):
                variables = {v["name"] for v in document["templating"]["list"]}
                ids = [p["id"] for p in panels(document)]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(
                    {link["url"].split("/")[-1] for link in document["links"]},
                    uids - {document["uid"]},
                )
                for panel in panels(document):
                    self.assertLessEqual(
                        panel["gridPos"]["x"] + panel["gridPos"]["w"], 24
                    )
                    for target in panel.get("targets", []):
                        referenced = set(re.findall(r"\$\{(\w+):", target["expr"]))
                        self.assertLessEqual(referenced, variables)
                        self.assertIn("${stack:regex}", target["expr"])
                        self.assertIn("${node:regex}", target["expr"])
                        if panel["type"] == "logs":
                            self.assertLessEqual(target["maxLines"], 200)
                        else:
                            self.assertEqual(
                                target["queryType"],
                                "instant" if panel["type"] == "stat" else "range",
                            )
                self.assertFalse(document["editable"])

    def test_renderer_always_reconciles_dashboards_after_application_verification(self):
        playbook = yaml.safe_load((ROOT / "ansible/deploy.yml").read_text())
        release = next(
            play
            for play in playbook
            if play.get("name") == "Deploy the tested production release"
        )
        tasks = release["tasks"][0]["block"]
        verify = next(
            i
            for i, task in enumerate(tasks)
            if task.get("include_role", {}).get("tasks_from") == "verify"
        )
        observation = next(
            i
            for i, task in enumerate(tasks)
            if any(
                nested.get("include_role", {}).get("name") == "observability"
                for nested in task.get("block", [])
            )
        )
        self.assertGreater(observation, verify)


if __name__ == "__main__":
    unittest.main()
