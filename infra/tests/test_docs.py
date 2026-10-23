"""The published docs list every page and every workflow, and stay inside docs/."""

import importlib.util
import re
import tomllib
import unittest

import yaml
from support import ROOT

REPOSITORY = ROOT.parent
DOCS = REPOSITORY / "docs"
LINK = re.compile(r"\]\(([^)\s]+)\)|(?:src|href)=\"([^\"]+)\"")


def nav_pages(entries):
    for entry in entries:
        for value in entry.values():
            if isinstance(value, list):
                yield from nav_pages(value)
            else:
                yield value


def inventory_rows():
    text = (DOCS / "development/contributing-ci.md").read_text()
    section = text.split("## Current automated checks", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].startswith("`"):
            rows[cells[0].strip("`")] = cells
    return rows


class DocsTests(unittest.TestCase):
    def test_every_page_is_in_the_nav(self):
        config = tomllib.loads((REPOSITORY / "zensical.toml").read_text())
        nav = set(nav_pages(config["project"]["nav"]))
        pages = {str(path.relative_to(DOCS)) for path in DOCS.rglob("*.md")}
        self.assertEqual(pages, nav)

    def test_relative_links_stay_inside_the_docs(self):
        escaping = []
        for page in sorted(DOCS.rglob("*.md")):
            for match in LINK.finditer(page.read_text()):
                target = (match.group(1) or match.group(2)).split("#", 1)[0]
                if not target or re.match(r"[a-z]+:", target):
                    continue
                resolved = (page.parent / target).resolve()
                if not resolved.is_relative_to(DOCS.resolve()):
                    escaping.append(f"{page.relative_to(DOCS)}: {target}")
        self.assertEqual(escaping, [])

    def test_ci_inventory_documents_every_workflow(self):
        rows = inventory_rows()
        workflows = sorted(
            path.name for path in (REPOSITORY / ".github/workflows").glob("*.yml")
        )
        self.assertEqual(
            sorted(name for name in rows if name.endswith(".yml")), workflows
        )
        spec = importlib.util.spec_from_file_location(
            "pin_release", ROOT / "scripts/pin_release.py"
        )
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        for filename in workflows:
            with self.subTest(workflow=filename):
                workflow = yaml.load(
                    (REPOSITORY / ".github/workflows" / filename).read_text(),
                    Loader=yaml.BaseLoader,
                )
                self.assertEqual(rows[filename][1], workflow["name"])
                expected = "yes" if filename in release.REQUIRED_WORKFLOWS else "no"
                self.assertEqual(rows[filename][4], expected)


if __name__ == "__main__":
    unittest.main()
