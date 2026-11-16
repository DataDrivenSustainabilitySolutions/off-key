"""Continuous WAL archiving: the overlay and the base-backup bookkeeping."""

import unittest

import yaml
from jinja2 import Environment, FileSystemLoader
from support import ROOT, load_script

backup = load_script("postgres_base_backup")


def overlay(**variables):
    environment = Environment(loader=FileSystemLoader(ROOT / "stack"))
    # Ansible's bool filter, which the template uses for inventory flags.
    environment.filters["bool"] = lambda value: (
        value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes"}
    )
    template = environment.get_template("docker-compose.persistence.yml.j2")
    return yaml.safe_load(template.render(**variables))


class WalArchiveOverlayTests(unittest.TestCase):
    def test_archiving_mounts_its_own_volume_and_never_overwrites(self):
        model = overlay(persist_postgres=True)
        postgres = model["services"]["postgres"]
        self.assertIn(
            "postgres_wal_archive:/var/lib/postgresql/wal-archive", postgres["volumes"]
        )
        self.assertEqual(
            set(model["volumes"]), {"postgres_data", "postgres_wal_archive"}
        )
        settings = dict(
            item.split("=", 1) for item in postgres["command"] if "=" in item
        )
        self.assertEqual(settings["archive_mode"], "on")
        self.assertEqual(settings["archive_timeout"], "300")
        command = settings["archive_command"]
        self.assertTrue(command.startswith("test ! -f "))
        self.assertIn(".part %p && mv ", command)
        # Compose and Swarm each interpolate once; the shell sees "$@".
        self.assertIn('"$$@"', postgres["entrypoint"][2])
        self.assertTrue(
            postgres["entrypoint"][2].endswith('exec docker-entrypoint.sh "$$@"')
        )

    def test_archiving_needs_persistent_data(self):
        model = overlay(persist_emqx_data=True)
        self.assertNotIn("postgres", model.get("services") or {})


class BaseBackupTests(unittest.TestCase):
    def test_wal_segment_names_follow_postgres(self):
        self.assertEqual(backup.wal_segment(1, "0/3000028"), "000000010000000000000003")
        self.assertEqual(
            backup.wal_segment(2, "1A/FF000000"), "000000020000001A000000FF"
        )
        with self.assertRaises(ValueError):
            backup.wal_segment(1, "not-an-lsn")

    def test_oldest_needed_segment_reads_the_manifest_start(self):
        manifest = {
            "WAL-Ranges": [
                {"Timeline": 1, "Start-LSN": "0/3000028", "End-LSN": "0/3000100"}
            ]
        }
        self.assertEqual(
            backup.oldest_needed_segment(manifest), "000000010000000000000003"
        )
        with self.assertRaises(ValueError):
            backup.oldest_needed_segment({})

    def test_keeps_the_newest_complete_backups_and_ignores_partial_ones(self):
        names = [
            "20261101T033000Z",
            "20261115T033000Z",
            "20261108T033000Z",
            "20261116T120000Z.partial",
        ]
        kept, removable = backup.split_backups(names, 2)
        self.assertEqual(kept, ["20261115T033000Z", "20261108T033000Z"])
        self.assertEqual(removable, ["20261101T033000Z"])


if __name__ == "__main__":
    unittest.main()
